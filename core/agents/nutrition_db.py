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
