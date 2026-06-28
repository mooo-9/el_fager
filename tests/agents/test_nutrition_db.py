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
