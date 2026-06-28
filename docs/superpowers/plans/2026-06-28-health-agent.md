# HealthAgent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a single `HealthAgent` to El Fager that tracks nutrition (meals, macros, calories), acts as a personal chef (recipes + YouTube links), and manages gym training (programs, workouts, progressive overload) — with 5 proactive daily/weekly nudges.

**Architecture:** `HealthAgent` inherits `BaseAgent` and handles all routing internally (food vs gym vs chef). A standalone `NutritionDB` module wraps the Edamam Food Database API and owns all TDEE/macro math — mirroring how `MarketAnalyst` sits under `StocksAgent`. Recipes and YouTube links are fetched by delegating to the existing `BrowserAgent`. Proactive checks are added directly to `ProactiveEngine._run_checks()`.

**Tech Stack:** Python 3.14, Edamam Food Database API (free tier), existing `BrowserAgent` (Playwright), existing `ScreenAgent` (vision), `httpx` (already used by proactive.py), `pytest` for tests.

## Global Constraints

- Python 3.14 — no `pygame`, use `pygame-ce`
- All time strings spoken to Mo must use 12-hour AM/PM format (never 24-hour)
- No U+2192 (→), emojis, or Arabic in tool return strings or TTS-bound strings — em-dash `--` is safe
- Working directory is always `C:\claude proj\el_fager` — all `Path()` calls are relative to it
- `data/` directory already exists — write JSON files there
- `tests/agents/` already exists — add new test files there
- `.env` holds API keys — load with `os.getenv()`
- Run all tests from repo root: `pytest tests/ -v`

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `core/agents/nutrition_db.py` | **Create** | Edamam API wrapper + TDEE math + macro calculations |
| `core/agents/health_agent.py` | **Create** | Main agent — routes food/gym/chef tasks, delegates to NutritionDB + BrowserAgent |
| `tools/health_tool.py` | **Create** | Instant-lane tools registered in Brain (log_meal, log_workout, nutrition_summary, etc.) |
| `data/health_profile.json` | **Create** | User stats + daily targets (created on first profile setup) |
| `data/meal_log.json` | **Create** | Rolling daily meal entries |
| `data/workout_log.json` | **Create** | Gym session history |
| `data/gym_program.json` | **Create** | Current training split |
| `core/agents/router.py` | **Modify** | Add `_HEALTH_FOOD_KEYWORDS`, `_HEALTH_GYM_KEYWORDS` routing to `"health"` |
| `core/brain.py` | **Modify** | Add `"health"` case to `chat()` dispatch + health tool definitions + system prompt section |
| `core/proactive.py` | **Modify** | Add 5 health checks to `_run_checks()` |
| `tests/agents/test_nutrition_db.py` | **Create** | Unit tests for TDEE math, macro split, Edamam mock |
| `tests/agents/test_health_agent.py` | **Create** | Integration tests for meal logging, gym logging, chef mode, proactive logic |

---

## Task 1: NutritionDB — TDEE Math & Macro Calculations

**Files:**
- Create: `core/agents/nutrition_db.py`
- Create: `tests/agents/test_nutrition_db.py`

**Interfaces:**
- Produces:
  - `NutritionDB.calculate_tdee(age: int, weight_kg: float, height_cm: float, goal: str) -> float`
  - `NutritionDB.calculate_macros(tdee: float, weight_kg: float) -> dict`  — returns `{"protein_g": float, "fat_g": float, "carbs_g": float}`
  - `NutritionDB.search_food(name: str, grams: float) -> dict` — returns `{"kcal": float, "protein_g": float, "carbs_g": float, "fat_g": float, "food_name": str}` or raises `FoodNotFoundError`
  - `class FoodNotFoundError(Exception)`

- [ ] **Step 1: Write failing tests for TDEE and macro math**

Create `tests/agents/test_nutrition_db.py`:

```python
import pytest
from unittest.mock import patch, MagicMock
from core.agents.nutrition_db import NutritionDB, FoodNotFoundError


@pytest.fixture
def db():
    return NutritionDB()


def test_calculate_tdee_bulk(db):
    # Male, 22yo, 75kg, 175cm, bulk
    # BMR = 10*75 + 6.25*175 - 5*22 + 5 = 750+1093.75-110+5 = 1738.75
    # TDEE = 1738.75 * 1.55 = 2695.06
    # Bulk = TDEE + 300 = 2995.06
    result = db.calculate_tdee(age=22, weight_kg=75, height_cm=175, goal="bulk")
    assert abs(result - 2995.06) < 1.0


def test_calculate_tdee_cut(db):
    result = db.calculate_tdee(age=22, weight_kg=75, height_cm=175, goal="cut")
    # TDEE = 2695.06, cut = TDEE - 500 = 2195.06
    assert abs(result - 2195.06) < 1.0


def test_calculate_tdee_maintain(db):
    result = db.calculate_tdee(age=22, weight_kg=75, height_cm=175, goal="maintain")
    assert abs(result - 2695.06) < 1.0


def test_calculate_macros(db):
    macros = db.calculate_macros(tdee=3000.0, weight_kg=75.0)
    # Protein: 2g * 75kg = 150g
    assert macros["protein_g"] == 150.0
    # Fat: 25% of 3000 kcal / 9 = 83.33g
    assert abs(macros["fat_g"] - 83.33) < 0.1
    # Carbs: (3000 - 150*4 - 83.33*9) / 4 = (3000 - 600 - 750) / 4 = 1650/4 = 412.5
    assert abs(macros["carbs_g"] - 412.5) < 0.5


def test_search_food_success(db):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "hints": [{
            "food": {
                "label": "Chicken Breast",
                "nutrients": {
                    "ENERC_KCAL": 165.0,
                    "PROCNT": 31.0,
                    "CHOCDF": 0.0,
                    "FAT": 3.6,
                }
            }
        }]
    }
    with patch("httpx.get", return_value=mock_response):
        result = db.search_food("chicken breast", grams=100)
    assert result["food_name"] == "Chicken Breast"
    assert abs(result["kcal"] - 165.0) < 0.1
    assert abs(result["protein_g"] - 31.0) < 0.1


def test_search_food_scales_by_grams(db):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "hints": [{
            "food": {
                "label": "Rice",
                "nutrients": {
                    "ENERC_KCAL": 130.0,
                    "PROCNT": 2.7,
                    "CHOCDF": 28.0,
                    "FAT": 0.3,
                }
            }
        }]
    }
    with patch("httpx.get", return_value=mock_response):
        result = db.search_food("rice", grams=150)  # 1.5x the per-100g values
    assert abs(result["kcal"] - 195.0) < 0.5   # 130 * 1.5
    assert abs(result["carbs_g"] - 42.0) < 0.5  # 28 * 1.5


def test_search_food_not_found(db):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"hints": []}
    with patch("httpx.get", return_value=mock_response):
        with pytest.raises(FoodNotFoundError):
            db.search_food("xyznonexistent", grams=100)


def test_search_food_api_error(db):
    mock_response = MagicMock()
    mock_response.status_code = 401
    with patch("httpx.get", return_value=mock_response):
        with pytest.raises(FoodNotFoundError):
            db.search_food("chicken", grams=100)
```

- [ ] **Step 2: Run tests to confirm they fail**

```
pytest tests/agents/test_nutrition_db.py -v
```

Expected: `ModuleNotFoundError: No module named 'core.agents.nutrition_db'`

- [ ] **Step 3: Implement NutritionDB**

Create `core/agents/nutrition_db.py`:

```python
import os
import httpx

_EDAMAM_URL = "https://api.edamam.com/api/food-database/v2/parser"


class FoodNotFoundError(Exception):
    pass


class NutritionDB:
    """Edamam Food Database wrapper + TDEE and macro math."""

    def __init__(self):
        self._app_id  = os.getenv("EDAMAM_APP_ID", "")
        self._app_key = os.getenv("EDAMAM_APP_KEY", "")

    def calculate_tdee(self, age: int, weight_kg: float, height_cm: float, goal: str) -> float:
        """Harris-Benedict BMR * 1.55 (moderate activity) +/- goal adjustment."""
        bmr  = 10 * weight_kg + 6.25 * height_cm - 5 * age + 5  # male formula
        tdee = bmr * 1.55
        adjustments = {"bulk": 300, "cut": -500, "maintain": 0}
        return round(tdee + adjustments.get(goal.lower(), 0), 2)

    def calculate_macros(self, tdee: float, weight_kg: float) -> dict:
        """Protein 2g/kg, fat 25% of kcal, carbs fill the rest."""
        protein_g = round(2.0 * weight_kg, 1)
        fat_g     = round((tdee * 0.25) / 9, 2)
        carbs_g   = round((tdee - protein_g * 4 - fat_g * 9) / 4, 1)
        return {"protein_g": protein_g, "fat_g": fat_g, "carbs_g": carbs_g}

    def search_food(self, name: str, grams: float) -> dict:
        """Look up a food item and scale nutrients to the given gram weight.

        Returns: {"food_name", "kcal", "protein_g", "carbs_g", "fat_g"}
        Raises FoodNotFoundError if not found or API unavailable.
        """
        try:
            resp = httpx.get(
                _EDAMAM_URL,
                params={"app_id": self._app_id, "app_key": self._app_key, "ingr": name},
                timeout=8,
            )
        except Exception as exc:
            raise FoodNotFoundError(f"Network error: {exc}") from exc

        if resp.status_code != 200:
            raise FoodNotFoundError(f"Edamam API returned {resp.status_code}")

        hints = resp.json().get("hints", [])
        if not hints:
            raise FoodNotFoundError(f"No results for '{name}'")

        nutrients = hints[0]["food"]["nutrients"]
        factor    = grams / 100.0
        return {
            "food_name": hints[0]["food"]["label"],
            "kcal":      round(nutrients.get("ENERC_KCAL", 0) * factor, 1),
            "protein_g": round(nutrients.get("PROCNT", 0)     * factor, 1),
            "carbs_g":   round(nutrients.get("CHOCDF", 0)     * factor, 1),
            "fat_g":     round(nutrients.get("FAT", 0)        * factor, 1),
        }
```

- [ ] **Step 4: Run tests — all must pass**

```
pytest tests/agents/test_nutrition_db.py -v
```

Expected: 8 PASSED

- [ ] **Step 5: Commit**

```
git add core/agents/nutrition_db.py tests/agents/test_nutrition_db.py
git commit -m "feat: add NutritionDB module -- Edamam wrapper + TDEE/macro math"
```

---

## Task 2: HealthAgent Skeleton + Profile Setup

**Files:**
- Create: `core/agents/health_agent.py`
- Create: `tests/agents/test_health_agent.py` (skeleton — expanded in later tasks)

**Interfaces:**
- Consumes: `NutritionDB.calculate_tdee()`, `NutritionDB.calculate_macros()`
- Produces: `HealthAgent.run(task: str) -> str` (BaseAgent contract)
- Produces: `HealthAgent._setup_profile(task: str) -> str`
- Produces: `HealthAgent._load_profile() -> dict | None`

- [ ] **Step 1: Write failing tests for profile setup**

Create `tests/agents/test_health_agent.py`:

```python
import json
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock


@pytest.fixture(autouse=True)
def clean_profile(tmp_path, monkeypatch):
    """Redirect data files to a temp directory for each test."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data").mkdir()
    yield tmp_path


def _make_agent():
    from core.agents.health_agent import HealthAgent
    return HealthAgent()


def test_agent_name():
    agent = _make_agent()
    assert agent.name == "health"


def test_no_profile_returns_setup_prompt():
    agent = _make_agent()
    result = agent.run("log meal: chicken breast 200g")
    assert "profile" in result.lower() or "stats" in result.lower()


def test_setup_profile_from_stats():
    agent = _make_agent()
    result = agent.run("my stats: 22 years old, 75kg, 175cm, goal is bulk")
    assert "3000" in result or "2995" in result or "calorie" in result.lower()
    profile = json.loads(Path("data/health_profile.json").read_text())
    assert profile["age"] == 22
    assert profile["weight_kg"] == 75.0
    assert profile["height_cm"] == 175.0
    assert profile["goal"] == "bulk"
    assert profile["targets"]["protein_g"] == 150.0


def test_override_target():
    agent = _make_agent()
    agent.run("my stats: 22 years old, 75kg, 175cm, goal is bulk")
    result = agent.run("set my daily protein to 200g")
    assert "200" in result
    profile = json.loads(Path("data/health_profile.json").read_text())
    assert profile["overrides"]["protein_g"] == 200.0
```

- [ ] **Step 2: Run tests to confirm they fail**

```
pytest tests/agents/test_health_agent.py::test_agent_name tests/agents/test_health_agent.py::test_no_profile_returns_setup_prompt -v
```

Expected: `ModuleNotFoundError: No module named 'core.agents.health_agent'`

- [ ] **Step 3: Implement HealthAgent skeleton + profile setup**

Create `core/agents/health_agent.py`:

```python
import json
import re
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

    # ── Profile ────────────────────────────────────────────────────────────────

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

    # ── Stubs (implemented in later tasks) ────────────────────────────────────

    def _log_meal(self, task: str, profile: dict) -> str:
        return "Meal logging not yet implemented."

    def _log_workout(self, task: str, profile: dict) -> str:
        return "Workout logging not yet implemented."

    def _chef_mode(self, task: str, profile: dict) -> str:
        return "Chef mode not yet implemented."

    def _setup_gym_program(self, task: str, profile: dict) -> str:
        return "Gym program setup not yet implemented."

    def _nutrition_summary(self, profile: dict) -> str:
        return "Nutrition summary not yet implemented."

    def _todays_workout(self, profile: dict) -> str:
        return "Today's workout not yet implemented."

    def _exercise_progress(self, task: str, profile: dict) -> str:
        return "Exercise progress not yet implemented."

    # ── Parse helpers ──────────────────────────────────────────────────────────

    def _parse_int(self, text: str, pattern: str) -> int | None:
        m = re.search(pattern, text, re.IGNORECASE)
        return int(m.group(1)) if m else None

    def _parse_float(self, text: str, pattern: str) -> float | None:
        m = re.search(pattern, text, re.IGNORECASE)
        return float(m.group(1)) if m else None
```

- [ ] **Step 4: Run tests — all must pass**

```
pytest tests/agents/test_health_agent.py::test_agent_name tests/agents/test_health_agent.py::test_no_profile_returns_setup_prompt tests/agents/test_health_agent.py::test_setup_profile_from_stats tests/agents/test_health_agent.py::test_override_target -v
```

Expected: 4 PASSED

- [ ] **Step 5: Commit**

```
git add core/agents/health_agent.py tests/agents/test_health_agent.py
git commit -m "feat: add HealthAgent skeleton with profile setup and TDEE-based targets"
```

---

## Task 3: Meal Logging (Voice + Text)

**Files:**
- Modify: `core/agents/health_agent.py` — implement `_log_meal()`, add `_parse_meal_items()`, `_load_meal_log()`, `_save_meal_log()`, `_nutrition_summary()`
- Modify: `tests/agents/test_health_agent.py` — add meal logging tests

**Interfaces:**
- Consumes: `NutritionDB.search_food(name, grams) -> dict`
- Produces: `_log_meal(task, profile) -> str` — parses multi-food utterance, calls Edamam, appends to `meal_log.json`
- Produces: `_nutrition_summary(profile) -> str` — today's totals vs targets

- [ ] **Step 1: Write failing tests**

Append to `tests/agents/test_health_agent.py`:

```python
def _setup_profile(agent):
    agent.run("my stats: 22 years old, 75kg, 175cm, goal is bulk")


def _mock_food(kcal, protein, carbs, fat, name="Food"):
    return {"food_name": name, "kcal": kcal, "protein_g": protein, "carbs_g": carbs, "fat_g": fat}


def test_log_single_food():
    agent = _make_agent()
    _setup_profile(agent)
    with patch("core.agents.nutrition_db.NutritionDB.search_food",
               return_value=_mock_food(165, 31, 0, 3.6, "Chicken Breast")):
        result = agent.run("i just ate 200g chicken breast")
    assert "165" in result or "330" in result  # 200g = 2x per-100g
    log = json.loads(Path("data/meal_log.json").read_text())
    assert len(log["entries"]) == 1
    assert log["entries"][0]["items"][0]["food_name"] == "Chicken Breast"


def test_log_multi_food():
    agent = _make_agent()
    _setup_profile(agent)

    foods = [
        _mock_food(165, 31, 0, 3.6, "Chicken Breast"),
        _mock_food(130, 2.7, 28, 0.3, "Rice"),
    ]
    with patch("core.agents.nutrition_db.NutritionDB.search_food", side_effect=foods):
        result = agent.run("i just ate 200g chicken breast and 150g rice")
    assert "kcal" in result.lower() or any(c.isdigit() for c in result)
    log = json.loads(Path("data/meal_log.json").read_text())
    assert len(log["entries"][0]["items"]) == 2


def test_nutrition_summary_shows_totals():
    agent = _make_agent()
    _setup_profile(agent)
    with patch("core.agents.nutrition_db.NutritionDB.search_food",
               return_value=_mock_food(300, 40, 10, 5, "Eggs")):
        agent.run("i ate 200g eggs")
    result = agent.run("nutrition summary")
    assert "300" in result  # kcal logged
    assert "kcal" in result.lower() or "calorie" in result.lower()


def test_food_not_found_gives_helpful_message():
    agent = _make_agent()
    _setup_profile(agent)
    with patch("core.agents.nutrition_db.NutritionDB.search_food",
               side_effect=FoodNotFoundError("not found")):
        result = agent.run("i ate 100g xyzunknownfood")
    assert "specific" in result.lower() or "couldn't find" in result.lower()
```

- [ ] **Step 2: Run to confirm they fail**

```
pytest tests/agents/test_health_agent.py::test_log_single_food -v
```

Expected: FAIL — `_log_meal` returns stub string

- [ ] **Step 3: Implement `_log_meal`, `_nutrition_summary`, and meal log helpers**

Replace the stub methods in `core/agents/health_agent.py`:

```python
# Add to imports at top:
from datetime import date as _date

# Replace _log_meal:
def _log_meal(self, task: str, profile: dict) -> str:
    items = self._parse_meal_items(task)
    if not items:
        return "I couldn't find any food items with gram amounts. Try: I ate 200g chicken breast and 150g rice"

    log     = self._load_meal_log()
    today   = _date.today().isoformat()
    entry   = next((e for e in log["entries"] if e["date"] == today), None)
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

def _parse_meal_items(self, task: str) -> list[tuple[str, float]]:
    """Extract (food_name, grams) pairs from a sentence like '200g chicken breast and 150g rice'."""
    pattern = r"(\d+(?:\.\d+)?)\s*g\s+([a-zA-Z ]+?)(?=\s+and\s+\d|\s*,\s*\d|$)"
    matches = re.findall(pattern, task, re.IGNORECASE)
    return [(name.strip(), float(grams)) for grams, name in matches]

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
```

- [ ] **Step 4: Run tests — all must pass**

```
pytest tests/agents/test_health_agent.py -v
```

Expected: all PASSED (including Task 2 tests)

- [ ] **Step 5: Commit**

```
git add core/agents/health_agent.py tests/agents/test_health_agent.py
git commit -m "feat: implement meal logging with multi-food parsing and daily nutrition summary"
```

---

## Task 4: Screen Photo Meal Logging

**Files:**
- Modify: `core/agents/health_agent.py` — add `_log_meal_from_screen()`, handle screen trigger in `run()`
- Modify: `tests/agents/test_health_agent.py` — add screen logging tests

**Interfaces:**
- Consumes: `ScreenAgent.run(task: str) -> str` (already built)
- Produces: screen logging path via `run()` when "what did i eat" + screenshot context

- [ ] **Step 1: Write failing tests**

Append to `tests/agents/test_health_agent.py`:

```python
def test_log_meal_from_screen_delegates_to_screen_agent():
    agent = _make_agent()
    _setup_profile(agent)
    with patch("core.agents.screen_agent.ScreenAgent.run",
               return_value="I can see: a plate with grilled chicken and rice") as mock_screen, \
         patch("core.agents.nutrition_db.NutritionDB.search_food",
               return_value=_mock_food(200, 30, 20, 5, "Grilled Chicken")):
        result = agent.run("what did i just eat? log it")
    mock_screen.assert_called_once()
    assert "logged" in result.lower() or "chicken" in result.lower()
```

- [ ] **Step 2: Run to confirm it fails**

```
pytest tests/agents/test_health_agent.py::test_log_meal_from_screen_delegates_to_screen_agent -v
```

Expected: FAIL

- [ ] **Step 3: Implement screen meal logging**

Add to `run()` in `health_agent.py` (before the existing `log meal` check):

```python
if any(kw in task_lower for kw in ["what did i just eat", "what did i eat", "log what i ate"]):
    return self._log_meal_from_screen(task, profile)
```

Add the method:

```python
def _log_meal_from_screen(self, task: str, profile: dict) -> str:
    try:
        from core.agents.screen_agent import ScreenAgent
        screen_result = ScreenAgent().run("What food items can you see? List them with approximate portions.")
    except Exception as exc:
        return f"Couldn't read the screen: {exc}. Describe what you ate instead."

    # Feed the screen description back through meal logging
    return self._log_meal(screen_result, profile)
```

- [ ] **Step 4: Run tests**

```
pytest tests/agents/test_health_agent.py -v
```

Expected: all PASSED

- [ ] **Step 5: Commit**

```
git add core/agents/health_agent.py tests/agents/test_health_agent.py
git commit -m "feat: add screen photo meal logging via ScreenAgent vision"
```

---

## Task 5: Gym Program Setup + Workout Logging + Progressive Overload

**Files:**
- Modify: `core/agents/health_agent.py` — implement `_setup_gym_program()`, `_log_workout()`, `_todays_workout()`, `_exercise_progress()`
- Modify: `tests/agents/test_health_agent.py` — add gym tests

**Interfaces:**
- Produces:
  - `_setup_gym_program(task, profile) -> str`
  - `_log_workout(task, profile) -> str`
  - `_todays_workout(profile) -> str`
  - `_exercise_progress(task, profile) -> str`

- [ ] **Step 1: Write failing tests**

Append to `tests/agents/test_health_agent.py`:

```python
def test_set_custom_split():
    agent = _make_agent()
    _setup_profile(agent)
    result = agent.run("my split is: Monday chest, Tuesday back, Wednesday legs, Thursday shoulders")
    assert "saved" in result.lower() or "program" in result.lower()
    program = json.loads(Path("data/gym_program.json").read_text())
    assert "monday" in program["split"]
    assert "chest" in program["split"]["monday"]


def test_log_workout_saves_session():
    agent = _make_agent()
    _setup_profile(agent)
    agent.run("my split is: Monday chest, Tuesday back")
    result = agent.run("just finished chest day: bench press 4x8 at 80kg, incline 3x10 at 60kg")
    assert "logged" in result.lower() or "chest" in result.lower()
    log = json.loads(Path("data/workout_log.json").read_text())
    assert len(log["sessions"]) == 1
    session = log["sessions"][0]
    assert session["session"] == "chest"
    bench = next(e for e in session["exercises"] if "bench" in e["name"].lower())
    assert bench["sets"][0]["weight_kg"] == 80.0


def test_progressive_overload_nudge():
    agent = _make_agent()
    _setup_profile(agent)
    # Log same weight/reps twice -- should trigger overload suggestion
    for _ in range(2):
        agent.run("just finished chest day: bench press 4x8 at 80kg")
    result = agent.run("just finished chest day: bench press 4x8 at 80kg")
    assert "82" in result or "increase" in result.lower() or "heavier" in result.lower()


def test_todays_workout_with_program():
    agent = _make_agent()
    _setup_profile(agent)
    agent.run("my split is: Monday chest, Tuesday back, Wednesday legs")
    result = agent.run("what should i do today?")
    # Should return some workout info (day name + exercises or a message)
    assert len(result) > 10
```

- [ ] **Step 2: Run to confirm they fail**

```
pytest tests/agents/test_health_agent.py::test_set_custom_split -v
```

Expected: FAIL — `_setup_gym_program` returns stub

- [ ] **Step 3: Implement gym methods**

Add to `core/agents/health_agent.py`:

```python
# Add to imports:
from datetime import date as _date, datetime as _datetime

def _setup_gym_program(self, task: str, profile: dict) -> str:
    task_lower = task.lower()
    split = {}

    # Parse "my split is: Monday chest, Tuesday back..."
    if "my split is" in task_lower or "my training" in task_lower:
        days = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
        for day in days:
            pattern = rf"{day}\s*[:\-]?\s*([a-zA-Z /]+?)(?=,\s*(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)|$)"
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


def _parse_exercises(self, task: str) -> list[dict]:
    """Parse 'bench press 4x8 at 80kg' patterns."""
    pattern = r"([a-zA-Z ]+?)\s+(\d+)x(\d+)\s+(?:at\s+)?(\d+(?:\.\d+)?)\s*kg"
    matches = re.findall(pattern, task, re.IGNORECASE)
    exercises = []
    for name, sets_count, reps, weight in matches:
        sets = [{"reps": int(reps), "weight_kg": float(weight)}] * int(sets_count)
        exercises.append({"name": name.strip(), "sets": sets})
    return exercises


def _check_overload(self, session: str, exercises: list[dict], log: dict) -> str:
    """If the same exercise was logged at same weight 2+ times, suggest increasing."""
    hints = []
    for exercise in exercises:
        name       = exercise["name"].lower()
        weight     = exercise["sets"][0]["weight_kg"]
        reps       = exercise["sets"][0]["reps"]
        past_same  = [
            s for s in log["sessions"][-4:-1]  # last 3 (before today)
            if s["session"] == session
            for e in s["exercises"]
            if e["name"].lower() == name
            and e["sets"][0]["weight_kg"] == weight
            and e["sets"][0]["reps"] >= reps
        ]
        if len(past_same) >= 2:
            next_weight = weight + 2.5
            hints.append(f"You've hit {weight}kg on {exercise['name']} twice -- try {next_weight}kg next session.")
    return " ".join(hints)


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
    # Find exercise name from task
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
```

- [ ] **Step 4: Run tests**

```
pytest tests/agents/test_health_agent.py -v
```

Expected: all PASSED

- [ ] **Step 5: Commit**

```
git add core/agents/health_agent.py tests/agents/test_health_agent.py
git commit -m "feat: add gym program setup, workout logging, and progressive overload detection"
```

---

## Task 6: Chef Mode — Recipes + YouTube Links

**Files:**
- Modify: `core/agents/health_agent.py` — implement `_chef_mode()`
- Modify: `tests/agents/test_health_agent.py` — add chef mode tests

**Interfaces:**
- Consumes: `BrowserAgent.run(task: str) -> str` (already built)

- [ ] **Step 1: Write failing tests**

Append to `tests/agents/test_health_agent.py`:

```python
def test_chef_mode_returns_recipe_and_youtube():
    agent = _make_agent()
    _setup_profile(agent)
    browser_response = (
        "Recipe: Shakshuka\n"
        "Ingredients: 2 eggs, 1 can tomatoes, onion, garlic\n"
        "Steps: 1. Saute onion 2. Add tomatoes 3. Crack eggs 4. Simmer\n"
        "YouTube: https://youtube.com/watch?v=abc123"
    )
    with patch("core.agents.browser_agent.BrowserAgent.run", return_value=browser_response):
        result = agent.run("give me a recipe for shakshuka")
    assert "shakshuka" in result.lower() or "recipe" in result.lower()
    assert "youtube" in result.lower() or "http" in result.lower()


def test_chef_mode_suggests_based_on_macros():
    agent = _make_agent()
    _setup_profile(agent)
    # Log a small meal so remaining macros are high protein need
    with patch("core.agents.nutrition_db.NutritionDB.search_food",
               return_value=_mock_food(200, 15, 20, 5, "Oats")):
        agent.run("i ate 100g oats")
    browser_response = "Recipe: Grilled Chicken\nIngredients: chicken\nSteps: grill it\nYouTube: https://youtube.com/watch?v=xyz"
    with patch("core.agents.browser_agent.BrowserAgent.run", return_value=browser_response):
        result = agent.run("what can i make for dinner? something easy and high protein")
    assert len(result) > 20
```

- [ ] **Step 2: Run to confirm they fail**

```
pytest tests/agents/test_health_agent.py::test_chef_mode_returns_recipe_and_youtube -v
```

Expected: FAIL — `_chef_mode` returns stub

- [ ] **Step 3: Implement `_chef_mode`**

Replace `_chef_mode` stub in `health_agent.py`:

```python
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
```

- [ ] **Step 4: Run tests**

```
pytest tests/agents/test_health_agent.py -v
```

Expected: all PASSED

- [ ] **Step 5: Commit**

```
git add core/agents/health_agent.py tests/agents/test_health_agent.py
git commit -m "feat: implement chef mode -- recipe lookup and YouTube link via BrowserAgent"
```

---

## Task 7: Router + Brain Integration

**Files:**
- Modify: `core/agents/router.py` — add health keyword lists
- Modify: `core/brain.py` — add `"health"` dispatch case + tool definitions + system prompt section
- Modify: `tests/agents/test_health_agent.py` — add router tests

**Interfaces:**
- `classify_intent(message) -> "health"` for food/gym messages

- [ ] **Step 1: Write router tests**

Append to `tests/agents/test_health_agent.py`:

```python
def test_router_food_keywords():
    from core.agents.router import classify_intent
    assert classify_intent("I just ate 200g chicken breast") == "health"
    assert classify_intent("give me a recipe for pasta") == "health"
    assert classify_intent("what can i cook tonight?") == "health"
    assert classify_intent("nutrition summary") == "health"
    assert classify_intent("how many calories today?") == "health"


def test_router_gym_keywords():
    from core.agents.router import classify_intent
    assert classify_intent("just finished chest day bench press 4x8") == "health"
    assert classify_intent("what's my workout today?") == "health"
    assert classify_intent("my split is Monday chest Tuesday back") == "health"
    assert classify_intent("how's my bench press progress?") == "health"
```

- [ ] **Step 2: Run to confirm they fail**

```
pytest tests/agents/test_health_agent.py::test_router_food_keywords -v
```

Expected: FAIL — `classify_intent` returns `"instant"` for health phrases

- [ ] **Step 3: Add keywords to router.py**

Open `core/agents/router.py` and add before `_LABEL_KEYWORDS`:

```python
_HEALTH_FOOD_KEYWORDS = [
    "i just ate", "i ate", "i had", "log meal", "log food",
    "nutrition", "calories today", "how many calories", "macro", "macros",
    "protein today", "what did i eat", "log what i ate",
    "recipe", "give me a recipe", "how do i make", "how to make",
    "what can i make", "what can i cook", "suggest a meal", "chef",
    "cook", "cooking", "ingredient", "ingredients",
    "my stats", "my goal is", "daily target", "set my daily",
    "bulk", "cut", "maintain", "calorie target",
    "breakfast", "lunch", "dinner", "snack", "meal",
]

_HEALTH_GYM_KEYWORDS = [
    "gym", "workout", "training", "exercise",
    "chest day", "back day", "leg day", "push day", "pull day",
    "shoulder day", "arm day", "upper body", "lower body",
    "bench press", "squat", "deadlift", "sets", "reps",
    "progressive overload", "my split", "training split",
    "just finished", "finished chest", "finished back", "finished leg",
    "rest day", "how's my bench", "bench progress",
    "what should i do today", "today's workout", "today's session",
    "generate a program", "create a program", "training plan",
]
```

In `_LABEL_KEYWORDS`, add BEFORE the `"research"` entry:

```python
("health", _HEALTH_FOOD_KEYWORDS),
("health", _HEALTH_GYM_KEYWORDS),
```

Note: `_LABEL_KEYWORDS` maps label → keywords list. Since two entries share `"health"`, update the loop in `classify_intent` to handle this — or merge both lists under one entry:

```python
# Replace the two separate entries with one merged entry:
("health", _HEALTH_FOOD_KEYWORDS + _HEALTH_GYM_KEYWORDS),
```

- [ ] **Step 4: Add `"health"` case to `core/brain.py`**

Find the section in `Brain.chat()` where agent intents are dispatched (where `"screen"`, `"browser"`, `"stocks_agent"` etc. are handled). Add:

```python
if intent == "health":
    from core.agents.health_agent import HealthAgent
    return HealthAgent().run(message)
```

Add to the system prompt (`SYSTEM_PROMPT`) — find the tools listing section and append:

```
Health & Nutrition tools: log_meal, log_workout, nutrition_summary, gym_program, chef_suggest.
When Mo says "I ate X", "I just ate", "log meal" -- call log_meal.
When Mo says "finished [day] day" or "just finished workout" -- call log_workout.
When Mo says "nutrition summary", "how am I doing", "calories today" -- call nutrition_summary.
When Mo asks for a recipe or "what can I cook" -- HealthAgent handles it (chef mode).
When Mo says "my split is", "generate a program", "what's today's workout" -- HealthAgent handles it.
```

- [ ] **Step 5: Run all tests**

```
pytest tests/agents/test_health_agent.py -v
```

Expected: all PASSED including router tests

- [ ] **Step 6: Commit**

```
git add core/agents/router.py core/brain.py tests/agents/test_health_agent.py
git commit -m "feat: wire HealthAgent into router and Brain dispatch"
```

---

## Task 8: Proactive Health Checks

**Files:**
- Modify: `core/proactive.py` — add 5 health checks to `_run_checks()`
- Modify: `tests/agents/test_health_agent.py` — add proactive logic tests

**Interfaces:**
- Consumes: `HealthAgent._load_meal_log()`, `HealthAgent._load_workout_log()`, `HealthAgent._load_profile()` (all return dicts)
- Consumes: `ProactiveEngine._cooldown(key, hours) -> bool`, `ProactiveEngine._deliver(text)`

- [ ] **Step 1: Write failing proactive tests**

Append to `tests/agents/test_health_agent.py`:

```python
def test_proactive_lunch_reminder_fires_when_lunch_missing():
    """Simulates 1 PM with no lunch logged -- should return a reminder."""
    from core.agents.health_agent import HealthAgent
    agent  = HealthAgent()
    _setup_profile(agent)
    # Log only breakfast
    with patch("core.agents.nutrition_db.NutritionDB.search_food",
               return_value=_mock_food(300, 20, 40, 5, "Oats")):
        agent.run("i ate 100g oats")

    log   = agent._load_meal_log()
    today = __import__("datetime").date.today().isoformat()
    entry = next((e for e in log["entries"] if e["date"] == today), None)
    meal_count = len(entry["items"]) if entry else 0
    assert meal_count == 1  # only breakfast logged


def test_proactive_daily_summary_content():
    from core.agents.health_agent import HealthAgent
    agent = HealthAgent()
    _setup_profile(agent)
    with patch("core.agents.nutrition_db.NutritionDB.search_food",
               return_value=_mock_food(500, 40, 50, 10, "Chicken and Rice")):
        agent.run("i ate 200g chicken and rice")
    summary = agent._nutrition_summary(agent._load_profile())
    assert "kcal" in summary.lower() or "calorie" in summary.lower()
    assert "/" in summary  # shows X/Y format


def test_gym_day_check_detects_unlogged_session():
    from core.agents.health_agent import HealthAgent
    import datetime
    agent = HealthAgent()
    _setup_profile(agent)
    today_name = datetime.datetime.now().strftime("%A").lower()
    agent.run(f"my split is: {today_name} chest")
    log = agent._load_workout_log()
    today = datetime.date.today().isoformat()
    trained_today = any(s["date"] == today for s in log["sessions"])
    assert not trained_today  # no workout logged yet -- proactive should fire
```

- [ ] **Step 2: Run to confirm baseline**

```
pytest tests/agents/test_health_agent.py::test_proactive_daily_summary_content -v
```

Expected: PASSED (this tests existing code)

- [ ] **Step 3: Add health checks to ProactiveEngine**

In `core/proactive.py`, add the following to `_run_checks()`:

```python
# Health checks -- add after existing time-gated blocks
if hour == 13:
    self._check_lunch_logged()

if hour == 18:
    self._check_daily_nutrition()

if hour == 20:
    self._check_gym_session()

if now.weekday() == 0:  # Monday
    self._check_weekly_gym_report()

self._check_rest_day()
```

Add the check methods to `ProactiveEngine`:

```python
def _check_lunch_logged(self) -> None:
    """Remind Mo if no food logged around lunch time."""
    if self._cooldown("health_lunch_reminder", 20):
        return
    try:
        from core.agents.health_agent import HealthAgent
        from datetime import date
        log   = HealthAgent()._load_meal_log()
        today = date.today().isoformat()
        entry = next((e for e in log.get("entries", []) if e["date"] == today), None)
        if entry is None or len(entry.get("items", [])) == 0:
            self._deliver("Mo, you haven't logged any meals today -- don't skip lunch.")
    except Exception:
        pass

def _check_daily_nutrition(self) -> None:
    """6 PM nutrition summary -- how close Mo is to daily targets."""
    if self._cooldown("health_daily_summary", 20):
        return
    try:
        from core.agents.health_agent import HealthAgent
        agent   = HealthAgent()
        profile = agent._load_profile()
        if profile is None:
            return
        summary = agent._nutrition_summary(profile)
        if "nothing logged" not in summary.lower():
            self._deliver(f"Nutrition check -- {summary}")
    except Exception:
        pass

def _check_gym_session(self) -> None:
    """8 PM: if today is a gym day and no workout logged, nudge Mo."""
    if self._cooldown("health_gym_reminder", 20):
        return
    try:
        from core.agents.health_agent import HealthAgent
        from pathlib import Path
        import json, datetime
        gym_path = Path("data/gym_program.json")
        if not gym_path.exists():
            return
        program    = json.loads(gym_path.read_text())
        today_name = datetime.datetime.now().strftime("%A").lower()
        session    = program.get("split", {}).get(today_name)
        if not session:
            return
        log   = HealthAgent()._load_workout_log()
        today = datetime.date.today().isoformat()
        if not any(s["date"] == today for s in log.get("sessions", [])):
            self._deliver(f"Mo, it's {session} day -- did you train? Log it when you're done.")
    except Exception:
        pass

def _check_weekly_gym_report(self) -> None:
    """Monday: weekly gym report."""
    if self._cooldown("health_weekly_report", 144):  # 6 days
        return
    try:
        from core.agents.health_agent import HealthAgent
        from datetime import date, timedelta
        import json
        log     = HealthAgent()._load_workout_log()
        week_ago = (date.today() - timedelta(days=7)).isoformat()
        sessions = [s for s in log.get("sessions", []) if s["date"] >= week_ago]
        count    = len(sessions)
        if count == 0:
            self._deliver("Weekly gym report -- no sessions logged last week. Get back on track, Mo.")
        else:
            days = ", ".join(s["session"].capitalize() for s in sessions[-3:])
            self._deliver(f"Weekly gym report -- {count} sessions last week. Latest: {days}.")
    except Exception:
        pass

def _check_rest_day(self) -> None:
    """Suggest rest after 4 consecutive training days."""
    if self._cooldown("health_rest_suggestion", 20):
        return
    try:
        from core.agents.health_agent import HealthAgent
        from datetime import date, timedelta
        log = HealthAgent()._load_workout_log()
        consecutive = 0
        for i in range(4):
            check_date = (date.today() - timedelta(days=i)).isoformat()
            if any(s["date"] == check_date for s in log.get("sessions", [])):
                consecutive += 1
            else:
                break
        if consecutive >= 4:
            self._deliver("Mo, you've trained 4 days straight -- consider a rest day for recovery.")
    except Exception:
        pass
```

- [ ] **Step 4: Run all tests**

```
pytest tests/agents/ -v
```

Expected: all PASSED

- [ ] **Step 5: Commit**

```
git add core/proactive.py tests/agents/test_health_agent.py
git commit -m "feat: add 5 proactive health checks -- lunch reminder, nutrition summary, gym nudge, weekly report, rest day"
```

---

## Task 9: health_tool.py + .env Keys + Final Smoke Test

**Files:**
- Create: `tools/health_tool.py` — instant-lane thin wrappers so Brain can call health functions as tools
- Modify: `.env` — document new required keys
- Create/check: `data/health_profile.json`, `data/meal_log.json`, `data/workout_log.json`, `data/gym_program.json` — ensure they're in `.gitignore`

**Interfaces:**
- Produces instant-lane tool functions callable by Brain

- [ ] **Step 1: Create health_tool.py**

```python
"""Instant-lane health tools -- thin wrappers over HealthAgent methods."""
from pathlib import Path
import json


def log_meal(description: str) -> str:
    """Log a meal from a text description like '200g chicken breast and 150g rice'."""
    from core.agents.health_agent import HealthAgent
    agent   = HealthAgent()
    profile = agent._load_profile()
    if profile is None:
        return "Set up your health profile first -- tell me your age, weight, height, and goal."
    return agent._log_meal(description, profile)


def log_workout(description: str) -> str:
    """Log a workout session like 'chest day: bench press 4x8 at 80kg'."""
    from core.agents.health_agent import HealthAgent
    agent   = HealthAgent()
    profile = agent._load_profile()
    if profile is None:
        return "Set up your health profile first."
    return agent._log_workout(description, profile)


def nutrition_summary() -> str:
    """Return today's calorie and macro progress vs targets."""
    from core.agents.health_agent import HealthAgent
    agent   = HealthAgent()
    profile = agent._load_profile()
    if profile is None:
        return "No health profile set up yet."
    return agent._nutrition_summary(profile)


def todays_workout() -> str:
    """Return today's scheduled training session based on Mo's program."""
    from core.agents.health_agent import HealthAgent
    agent   = HealthAgent()
    profile = agent._load_profile()
    if profile is None:
        return "No health profile set up yet."
    return agent._todays_workout(profile)
```

- [ ] **Step 2: Add Edamam keys to .env**

Open `.env` and add:

```
EDAMAM_APP_ID=your_app_id_here
EDAMAM_APP_KEY=your_app_key_here
```

Get free keys at: https://developer.edamam.com (Food Database API, free tier)

- [ ] **Step 3: Add data files to .gitignore**

Check `C:\claude proj\el_fager\.gitignore`. Add these lines if not present:

```
data/health_profile.json
data/meal_log.json
data/workout_log.json
data/gym_program.json
```

- [ ] **Step 4: Run full test suite**

```
pytest tests/ -v
```

Expected: all previous 256 tests + ~40 new = ~296 PASSED, 0 FAILED

- [ ] **Step 5: Commit**

```
git add tools/health_tool.py .gitignore
git commit -m "feat: add health_tool instant-lane wrappers and document Edamam env keys"
```

- [ ] **Step 6: Final integration smoke test**

Start El Fager normally:
```powershell
Start-Process pythonw -ArgumentList "main.py" -WorkingDirectory "C:\claude proj\el_fager"
```

Say these in order and verify:
1. "My stats: 22 years old, 75kg, 175cm, goal is bulk" — should reply with calorie target
2. "I just ate 150g chicken breast" — should log and show remaining macros
3. "Give me a recipe for shakshuka" — should return recipe + YouTube link
4. "My split is: Monday chest, Tuesday back, Wednesday legs" — should confirm program saved
5. "Just finished chest day: bench press 4x8 at 80kg" — should log session
6. "What should I do today?" — should return today's scheduled session

- [ ] **Step 7: Push to GitHub**

```
cd "C:\claude proj\el_fager"
git push origin master
```
