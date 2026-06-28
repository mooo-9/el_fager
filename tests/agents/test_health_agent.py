import json
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from core.agents.nutrition_db import FoodNotFoundError


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


# -- Meal logging tests --------------------------------------------------------

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


# -- Gym tests -----------------------------------------------------------------

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
    # Log same weight/reps twice -- should trigger overload suggestion on third
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


# -- Chef mode tests -----------------------------------------------------------

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
