# HealthAgent Design — El Fager
**Date:** 2026-06-28  
**Status:** Approved

---

## Overview

A single `HealthAgent` that is expert in both nutrition tracking and gym/training. It mirrors the `StocksAgent` / `MarketAnalyst` pattern: a focused agent class backed by a standalone data module (`NutritionDB`). The agent handles all food and gym tasks — meal logging, macro tracking, recipe lookup, YouTube video fetching, training program generation, workout logging, progressive overload, and proactive nudges.

---

## Files

```
core/agents/health_agent.py          — main agent (inherits BaseAgent)
core/agents/nutrition_db.py          — Edamam API wrapper + TDEE/macro math
tools/health_tool.py                 — instant-lane tools exposed to Brain
data/health_profile.json             — user stats + daily targets
data/meal_log.json                   — daily meal entries with macros
data/workout_log.json                — gym sessions, exercises, sets/reps/weight
data/gym_program.json                — current training split/program
tests/agents/test_health_agent.py
tests/agents/test_nutrition_db.py
```

---

## Integration with Existing Architecture

- `router.py` gets two new keyword lists:
  - `_HEALTH_FOOD_KEYWORDS` — food, meal, eat, recipe, cook, calories, protein, macros, breakfast, lunch, dinner, chef, ingredient, nutrition, diet, bulk, cut, maintain, grams, chicken, rice...
  - `_HEALTH_GYM_KEYWORDS` — gym, workout, training, exercise, chest day, push day, pull day, leg day, bench, squat, deadlift, sets, reps, progressive overload, split, rest day...
  - Both route to label `"health"`
- `Brain.chat()` gets a `"health"` case that instantiates and calls `HealthAgent`
- `ProactiveEngine` gains 5 new scheduled checks (see Proactive section)

---

## Section 1: Nutrition Features

### Profile Setup
- User says: "My stats: 22 years old, 75kg, 175cm, goal is bulk"
- `NutritionDB.calculate_tdee()` computes daily calorie target
- `NutritionDB.calculate_macros()` splits into protein/carbs/fat grams
- Stored in `data/health_profile.json`
- All targets overridable anytime: "set my daily protein to 200g"

### Meal Logging — Voice
- "I just ate 200g chicken breast, 150g rice, and a banana"
- `NutritionDB.search_food()` hits Edamam for each item
- Logged to `meal_log.json` under today's date
- El Fager replies: "Logged. You're at 1200/3000 kcal, protein 80/180g."

### Meal Logging — Screen Photo
- "What did I just eat?" + screenshot/photo on screen
- Delegates to `ScreenAgent` vision to identify food items
- Same logging flow as voice

### Meal Logging — Text Input
- User types meal details in the El Fager text box
- Same parsing and logging flow as voice

### 3-Meal Check
- Tracks which of breakfast/lunch/dinner have been logged today
- Feeds into proactive reminders

### Chef Mode
- "What can I make for dinner that's high protein and easy?"
- El Fager knows your remaining macro budget for the day
- Suggests 2-3 beginner-friendly recipes that fit your macros
- Gives step-by-step instructions + fetches YouTube video link via BrowserAgent

### Recipe Lookup
- "Give me a recipe for shakshuka"
- Full recipe with ingredient list, steps, macros per serving
- YouTube video link fetched via BrowserAgent

---

## Section 2: Gym Features

### Program Setup
- **Generate:** "Generate me a 4-day push/pull split for hypertrophy" → El Fager builds full program with exercises, sets, reps, rest times
- **Import own split:** "My split is: Monday chest, Tuesday back, Wednesday legs, Thursday shoulders" → stored as-is
- Stored in `data/gym_program.json`

### Workout Logging
- "Just finished chest day: bench 4x8 at 80kg, incline 3x10 at 60kg, cable fly 3x15"
- Parsed and stored in `workout_log.json` with date and session name

### Progressive Overload Tracking
- Per exercise, tracks weight and reps over time
- When target reps hit for 2 consecutive sessions → nudges to increase weight
- "Last week you did 80kg bench for 8 reps twice — try 82.5kg today"

### Training Advice
- "What should I do today?" → pulls today's session from program, lists exercises with recommended weight based on history
- "How's my bench press progressing?" → shows weight/rep history

---

## Section 3: NutritionDB Module

**`core/agents/nutrition_db.py` responsibilities:**

- Wraps Edamam Food Database API (free tier)
- Requires `EDAMAM_APP_ID` and `EDAMAM_APP_KEY` in `.env`

**Key methods:**
```python
search_food(name: str, grams: float) -> MacroResult
calculate_tdee(age: int, weight_kg: float, height_cm: float, goal: str) -> float
calculate_macros(tdee: float, goal: str, weight_kg: float) -> MacroTargets
```

**TDEE formula:** Harris-Benedict BMR × 1.55 (moderate activity). Adjustments: bulk +300 kcal, cut -500 kcal, maintain ±0.

**Macro split:**
- Protein: 2g × bodyweight_kg
- Fat: 25% of total calories ÷ 9
- Carbs: remaining calories ÷ 4

---

## Section 4: Data Shapes

### `data/health_profile.json`
```json
{
  "age": 22,
  "weight_kg": 75,
  "height_cm": 175,
  "goal": "bulk",
  "tdee": 3000,
  "targets": {
    "kcal": 3000,
    "protein_g": 150,
    "carbs_g": 350,
    "fat_g": 83
  },
  "overrides": {},
  "weekly_report_time": "08:00 AM"
}
```

### `data/meal_log.json` — daily entry
```json
{
  "date": "2026-06-28",
  "meals": {
    "breakfast": [{"food": "eggs", "grams": 150, "kcal": 215, "protein": 18, "carbs": 1, "fat": 14}],
    "lunch": [],
    "dinner": []
  },
  "totals": {"kcal": 215, "protein": 18, "carbs": 1, "fat": 14}
}
```

### `data/workout_log.json` — session entry
```json
{
  "date": "2026-06-28",
  "session": "chest",
  "duration_min": 60,
  "exercises": [
    {
      "name": "bench press",
      "sets": [
        {"reps": 8, "weight_kg": 80},
        {"reps": 8, "weight_kg": 80},
        {"reps": 7, "weight_kg": 80}
      ]
    }
  ]
}
```

---

## Section 5: Proactive Checks (ProactiveEngine)

| Trigger | Time | Action |
|---|---|---|
| Daily nutrition summary | 6:00 PM | Calories + protein status, suggests what to eat to hit targets |
| Lunch reminder | 1:00 PM | If lunch not logged: "Haven't seen lunch yet" |
| Gym day workout check | 8:00 PM | If today is a gym day and no workout logged: nudge |
| Weekly gym report | Configurable (default 8:00 AM Monday) | Sessions hit last week, PRs, focus areas |
| Rest day suggestion | After 4 consecutive training days | Suggests rest |

All times in 12-hour format. Weekly report time stored in `health_profile.json` and changeable via voice: "set my weekly report to 10:00 AM Monday".

---

## Section 6: Recipe & YouTube Flow

1. User asks for a recipe (voice, text, or chef suggestion)
2. `HealthAgent` calls `BrowserAgent` → searches recipe site → scrapes ingredients + steps
3. `BrowserAgent` separately searches YouTube → returns top video URL
4. `HealthAgent` computes macros per serving via `NutritionDB`
5. El Fager replies with: recipe name, ingredients, steps, macros per serving, YouTube link

---

## Section 7: Error Handling

| Scenario | Behaviour |
|---|---|
| Edamam food not found | "Couldn't find that food — try being more specific, e.g. '150g basmati rice' or list ingredients separately" |
| Edamam API down | Falls back to asking user for manual macro input |
| Screen photo food not recognized | Falls back to asking user to describe verbally |
| Missing `.env` keys | Clear startup error: "HealthAgent needs EDAMAM_APP_ID and EDAMAM_APP_KEY in .env" |
| YouTube link not found | Returns recipe without video, notes "couldn't find a video for this one" |
| No health profile set up | Agent prompts setup before any logging: "Let's set up your profile first — what are your stats?" |

---

## Section 8: Testing

**Target: ~40 new tests (256 → ~296 total)**

- `test_nutrition_db.py` — TDEE math, macro split, Edamam mocked responses, food search
- `test_health_agent.py`:
  - Meal logging: single food, multi-food sentence, grams parsing
  - Workout logging: full session parsing, progressive overload detection
  - Proactive check logic: daily summary, 3-meal tracking, gym day detection, consecutive day count
  - Chef suggestions: macro budget calculation, recipe format
  - Router: all health/gym keywords correctly route to `"health"`
