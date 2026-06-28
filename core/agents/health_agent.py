import json
import re
from datetime import date as _date, datetime as _datetime
from pathlib import Path

from core.agents.base_agent import BaseAgent
from core.agents.nutrition_db import NutritionDB, FoodNotFoundError

_PROFILE_PATH     = Path("data/health_profile.json")
_MEAL_LOG_PATH    = Path("data/meal_log.json")
_WORKOUT_LOG_PATH = Path("data/workout_log.json")
_GYM_PROGRAM_PATH = Path("data/gym_program.json")

_SETUP_TRIGGERS = [
    "my stats", "i am", "i weigh", "i'm", "years old", "goal is",
    "my goal", "set up my profile", "setup profile",
]
_OVERRIDE_TRIGGERS = [
    "set my daily", "change my", "update my target", "my target is",
]


class HealthAgent(BaseAgent):
    def __init__(self):
        self._db = NutritionDB()

    @property
    def name(self) -> str:
        return "health"

    @property
    def description(self) -> str:
        return "Personal nutrition tracker, chef, and gym coach."

    def run(self, task: str) -> str:
        task_lower = task.lower()

        # Profile setup / override
        if any(kw in task_lower for kw in _SETUP_TRIGGERS):
            return self._setup_profile(task)
        if any(kw in task_lower for kw in _OVERRIDE_TRIGGERS):
            return self._override_target(task)

        # All other actions require a profile
        profile = self._load_profile()
        if profile is None:
            return (
                "Let's set up your profile first -- what are your stats? "
                "Say something like: my stats: 22 years old, 75kg, 175cm, goal is bulk"
            )

        # Screen-based meal logging (before generic "log meal" check)
        if any(kw in task_lower for kw in ["what did i just eat", "what did i eat", "log what i ate"]):
            return self._log_meal_from_screen(task, profile)

        # Routing to sub-handlers (filled in later tasks)
        if any(kw in task_lower for kw in ["log meal", "i ate", "i just ate", "i had", "ate"]):
            return self._log_meal(task, profile)
        if any(kw in task_lower for kw in ["log workout", "finished", "just finished", "chest day", "back day", "leg day", "push day", "pull day", "shoulder day"]):
            return self._log_workout(task, profile)
        if any(kw in task_lower for kw in ["recipe", "how do i make", "how to make", "give me a recipe", "what can i make", "suggest", "chef"]):
            return self._chef_mode(task, profile)
        if any(kw in task_lower for kw in ["generate", "create program", "my split is", "my training", "training plan"]):
            return self._setup_gym_program(task, profile)
        if any(kw in task_lower for kw in ["nutrition", "calories today", "how am i doing", "macro", "summary", "what did i eat"]):
            return self._nutrition_summary(profile)
        if any(kw in task_lower for kw in ["what should i do today", "today's workout", "today's session", "what's my workout"]):
            return self._todays_workout(profile)
        if any(kw in task_lower for kw in ["progress", "how's my", "how is my", "bench press progress", "squat progress"]):
            return self._exercise_progress(task, profile)

        return "I can help with meals, recipes, workouts, and your training program. What do you need?"

    # -- Profile ----------------------------------------------------------------

    def _setup_profile(self, task: str) -> str:
        age    = self._parse_int(task, r"(\d+)\s*years?\s*old")
        weight = self._parse_float(task, r"(\d+(?:\.\d+)?)\s*kg")
        height = self._parse_float(task, r"(\d+(?:\.\d+)?)\s*cm")
        goal   = "maintain"
        for g in ("bulk", "cut", "maintain"):
            if g in task.lower():
                goal = g
                break

        if not all([age, weight, height]):
            return "I need your age, weight (kg), height (cm), and goal (bulk/cut/maintain). Try: my stats: 22 years old, 75kg, 175cm, goal is bulk"

        tdee   = self._db.calculate_tdee(age, weight, height, goal)
        macros = self._db.calculate_macros(tdee, weight)

        profile = {
            "age": age, "weight_kg": weight, "height_cm": height, "goal": goal,
            "tdee": tdee,
            "targets": {
                "kcal": tdee,
                "protein_g": macros["protein_g"],
                "carbs_g":   macros["carbs_g"],
                "fat_g":     macros["fat_g"],
            },
            "overrides": {},
            "weekly_report_time": "08:00 AM",
        }
        _PROFILE_PATH.parent.mkdir(parents=True, exist_ok=True)
        _PROFILE_PATH.write_text(json.dumps(profile, indent=2))

        return (
            f"Profile saved. Daily target: {tdee:.0f} kcal -- "
            f"{macros['protein_g']:.0f}g protein, {macros['carbs_g']:.0f}g carbs, {macros['fat_g']:.0f}g fat."
        )

    def _override_target(self, task: str) -> str:
        profile = self._load_profile()
        if profile is None:
            return "Set up your profile first."
        task_lower = task.lower()
        field_map = {
            "protein": "protein_g", "carbs": "carbs_g",
            "fat": "fat_g", "calories": "kcal", "calorie": "kcal",
        }
        value = self._parse_float(task, r"(\d+(?:\.\d+)?)")
        for word, field in field_map.items():
            if word in task_lower and value:
                profile["overrides"][field] = value
                _PROFILE_PATH.write_text(json.dumps(profile, indent=2))
                return f"Got it -- daily {word} target updated to {value:.0f}{'g' if field != 'kcal' else ' kcal'}."
        return "I didn't catch what to update. Try: set my daily protein to 200g"

    def _load_profile(self) -> dict | None:
        if not _PROFILE_PATH.exists():
            return None
        try:
            return json.loads(_PROFILE_PATH.read_text())
        except Exception:
            return None

    def _effective_targets(self, profile: dict) -> dict:
        """Merge base targets with any manual overrides."""
        targets = dict(profile["targets"])
        targets.update(profile.get("overrides", {}))
        return targets

    # -- Stubs (implemented in later tasks) ------------------------------------

    def _log_meal(self, task: str, profile: dict) -> str:
        items = self._parse_meal_items(task)
        if not items:
            return "I couldn't find any food items with gram amounts. Try: I ate 200g chicken breast and 150g rice"

        log   = self._load_meal_log()
        today = _date.today().isoformat()
        entry = next((e for e in log["entries"] if e["date"] == today), None)
        if entry is None:
            entry = {"date": today, "items": [], "totals": {"kcal": 0, "protein_g": 0, "carbs_g": 0, "fat_g": 0}}
            log["entries"].append(entry)

        logged, errors = [], []
        for name, grams in items:
            try:
                food = self._db.search_food(name, grams)
                entry["items"].append(food)
                for key in ("kcal", "protein_g", "carbs_g", "fat_g"):
                    entry["totals"][key] = round(entry["totals"][key] + food[key], 1)
                logged.append(food["food_name"])
            except FoodNotFoundError:
                errors.append(name)

        self._save_meal_log(log)

        targets = self._effective_targets(profile)
        totals  = entry["totals"]
        parts   = [f"Logged: {', '.join(logged)}." if logged else ""]
        if errors:
            parts.append(f"Couldn't find: {', '.join(errors)} -- try being more specific.")
        parts.append(
            f"Today: {totals['kcal']:.0f}/{targets['kcal']:.0f} kcal, "
            f"protein {totals['protein_g']:.0f}/{targets['protein_g']:.0f}g."
        )
        return " ".join(p for p in parts if p)

    def _log_meal_from_screen(self, task: str, profile: dict) -> str:
        try:
            from core.agents.screen_agent import ScreenAgent
            screen_result = ScreenAgent().run("What food items can you see? List them with approximate portions.")
        except Exception as exc:
            return f"Couldn't read the screen: {exc}. Describe what you ate instead."

        # Feed the screen description back through meal logging
        return self._log_meal(screen_result, profile)

    def _parse_meal_items(self, task: str) -> list[tuple[str, float]]:
        """Extract (food_name, grams) pairs from a sentence like '200g chicken breast and 150g rice'."""
        pattern = r"(\d+(?:\.\d+)?)\s*g\s+([a-zA-Z ]+?)(?=\s+and\s+\d|\s*,\s*\d|$)"
        matches = re.findall(pattern, task, re.IGNORECASE)
        return [(name.strip(), float(grams)) for grams, name in matches]

    def _log_workout(self, task: str, profile: dict) -> str:
        session_name = self._parse_session_name(task)
        exercises    = self._parse_exercises(task)

        if not exercises:
            return "I couldn't parse any exercises. Try: finished chest day: bench press 4x8 at 80kg"

        log   = self._load_workout_log()
        today = _date.today().isoformat()
        session = {
            "date": today,
            "session": session_name,
            "exercises": exercises,
        }
        log["sessions"].append(session)
        self._save_workout_log(log)

        overload_hint = self._check_overload(session_name, exercises, log)
        names = ", ".join(e["name"] for e in exercises)
        reply = f"Logged {session_name} day -- {names}."
        if overload_hint:
            reply += f" {overload_hint}"
        return reply

    def _parse_session_name(self, task: str) -> str:
        for day_type in ["chest", "back", "legs", "leg", "shoulders", "shoulder",
                         "arms", "push", "pull", "upper", "lower", "full body"]:
            if day_type in task.lower():
                return day_type.replace("leg", "legs").replace("shoulder", "shoulders")
        return "workout"

    def _parse_exercises(self, task: str) -> list:
        """Parse 'bench press 4x8 at 80kg' patterns."""
        pattern = r"([a-zA-Z ]+?)\s+(\d+)x(\d+)\s+(?:at\s+)?(\d+(?:\.\d+)?)\s*kg"
        matches = re.findall(pattern, task, re.IGNORECASE)
        exercises = []
        for name, sets_count, reps, weight in matches:
            sets = [{"reps": int(reps), "weight_kg": float(weight)}] * int(sets_count)
            exercises.append({"name": name.strip(), "sets": sets})
        return exercises

    def _check_overload(self, session: str, exercises: list, log: dict) -> str:
        """If the same exercise was logged at same weight and same/more reps 2+ times, suggest increasing."""
        hints = []
        # All sessions except the last one just added (which is already appended)
        prior_sessions = log["sessions"][:-1]
        # Take at most the last 3 prior sessions of the same type
        same_type_sessions = [s for s in prior_sessions if s["session"] == session]
        last_three = same_type_sessions[-3:]

        for exercise in exercises:
            name   = exercise["name"].lower()
            weight = exercise["sets"][0]["weight_kg"]
            reps   = exercise["sets"][0]["reps"]
            matches_count = 0
            for s in last_three:
                for e in s["exercises"]:
                    if (e["name"].lower() == name
                            and e["sets"][0]["weight_kg"] == weight
                            and e["sets"][0]["reps"] >= reps):
                        matches_count += 1
                        break
            if matches_count >= 2:
                next_weight = weight + 2.5
                hints.append(
                    f"You've hit {weight}kg on {exercise['name']} twice -- try {next_weight}kg next session."
                )
        return " ".join(hints)

    def _load_workout_log(self) -> dict:
        if _WORKOUT_LOG_PATH.exists():
            try:
                return json.loads(_WORKOUT_LOG_PATH.read_text())
            except Exception:
                pass
        return {"sessions": []}

    def _save_workout_log(self, log: dict) -> None:
        _WORKOUT_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        _WORKOUT_LOG_PATH.write_text(json.dumps(log, indent=2))

    def _chef_mode(self, task: str, profile: dict) -> str:
        targets = self._effective_targets(profile)
        log     = self._load_meal_log()
        today   = _date.today().isoformat()
        entry   = next((e for e in log["entries"] if e["date"] == today), None)
        totals  = entry["totals"] if entry else {"kcal": 0, "protein_g": 0, "carbs_g": 0, "fat_g": 0}

        remaining_protein = max(0, targets["protein_g"] - totals["protein_g"])
        remaining_kcal    = max(0, targets["kcal"] - totals["kcal"])

        context = (
            f"Mo needs easy beginner-friendly recipes. "
            f"He still needs {remaining_kcal:.0f} kcal and {remaining_protein:.0f}g protein today. "
            f"Original request: {task}. "
            f"Find a recipe, list ingredients and steps simply, then search YouTube for a video tutorial and include the link."
        )

        try:
            from core.agents.browser_agent import BrowserAgent
            result = BrowserAgent().run(context)
        except Exception as exc:
            return f"Couldn't fetch a recipe right now: {exc}"

        return result

    def _setup_gym_program(self, task: str, profile: dict) -> str:
        task_lower = task.lower()
        split = {}

        if "my split is" in task_lower or "my training" in task_lower:
            days = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
            for day in days:
                pattern = (
                    rf"{day}\s*[:\-]?\s*([a-zA-Z /]+?)"
                    rf"(?=,\s*(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)|$)"
                )
                m = re.search(pattern, task_lower)
                if m:
                    split[day] = m.group(1).strip().rstrip(",")

            if not split:
                return "I couldn't parse your split. Try: my split is: Monday chest, Tuesday back, Wednesday legs"

            program = {"type": "custom", "split": split, "exercises": {}}
            _GYM_PROGRAM_PATH.parent.mkdir(parents=True, exist_ok=True)
            _GYM_PROGRAM_PATH.write_text(json.dumps(program, indent=2))
            days_listed = ", ".join(f"{d.capitalize()} ({s})" for d, s in split.items())
            return f"Program saved -- {days_listed}."

        return "Tell me your split (e.g. my split is: Monday chest, Tuesday back) and I'll track it."

    def _nutrition_summary(self, profile: dict) -> str:
        log   = self._load_meal_log()
        today = _date.today().isoformat()
        entry = next((e for e in log["entries"] if e["date"] == today), None)
        if entry is None or not entry["items"]:
            return "Nothing logged today yet."
        totals  = entry["totals"]
        targets = self._effective_targets(profile)
        return (
            f"Today: {totals['kcal']:.0f}/{targets['kcal']:.0f} kcal -- "
            f"protein {totals['protein_g']:.0f}/{targets['protein_g']:.0f}g, "
            f"carbs {totals['carbs_g']:.0f}/{targets['carbs_g']:.0f}g, "
            f"fat {totals['fat_g']:.0f}/{targets['fat_g']:.0f}g."
        )

    def _load_meal_log(self) -> dict:
        if _MEAL_LOG_PATH.exists():
            try:
                return json.loads(_MEAL_LOG_PATH.read_text())
            except Exception:
                pass
        return {"entries": []}

    def _save_meal_log(self, log: dict) -> None:
        _MEAL_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        _MEAL_LOG_PATH.write_text(json.dumps(log, indent=2))

    def _todays_workout(self, profile: dict) -> str:
        if not _GYM_PROGRAM_PATH.exists():
            return "No program set up yet. Tell me your split or ask me to generate one."
        program = json.loads(_GYM_PROGRAM_PATH.read_text())
        today   = _datetime.now().strftime("%A").lower()
        session = program.get("split", {}).get(today)
        if not session:
            return f"No session scheduled for {today.capitalize()} in your program -- rest day."
        return f"Today is {session} day. Say 'finished {session} day: [exercises]' when done."

    def _exercise_progress(self, task: str, profile: dict) -> str:
        log = self._load_workout_log()
        stop_words = {"progress", "how", "is", "my", "how's", "doing", "strength"}
        words      = [w for w in task.lower().split() if w not in stop_words]
        query      = " ".join(words).strip()
        history    = []
        for session in log["sessions"]:
            for exercise in session["exercises"]:
                if query in exercise["name"].lower():
                    top_set = max(exercise["sets"], key=lambda s: s["weight_kg"])
                    history.append(f"{session['date']}: {top_set['weight_kg']}kg x {top_set['reps']} reps")
        if not history:
            return f"No history found for '{query}'."
        return f"{query.title()} history -- " + ", ".join(history[-5:])

    # -- Parse helpers ---------------------------------------------------------

    def _parse_int(self, text: str, pattern: str) -> int | None:
        m = re.search(pattern, text, re.IGNORECASE)
        return int(m.group(1)) if m else None

    def _parse_float(self, text: str, pattern: str) -> float | None:
        m = re.search(pattern, text, re.IGNORECASE)
        return float(m.group(1)) if m else None
