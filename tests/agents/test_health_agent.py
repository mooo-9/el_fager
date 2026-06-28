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
