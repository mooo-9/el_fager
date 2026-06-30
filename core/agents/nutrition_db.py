import os
import httpx

_EDAMAM_URL    = "https://api.edamam.com/api/food-database/v2/parser"
_USDA_URL      = "https://api.nal.usda.gov/fdc/v1/foods/search"
_USDA_DEMO_KEY = "DEMO_KEY"  # public, rate-limited -- works with no signup


class FoodNotFoundError(Exception):
    pass


class NutritionDB:
    """Food nutrition lookup. Tries Edamam first, falls back to USDA
    FoodData Central (free, no-approval API) if Edamam is unconfigured
    or rejects the request."""

    def __init__(self):
        self._app_id   = os.getenv("EDAMAM_APP_ID", "")
        self._app_key  = os.getenv("EDAMAM_APP_KEY", "")
        self._usda_key = os.getenv("USDA_API_KEY", _USDA_DEMO_KEY)

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
        Raises FoodNotFoundError if not found by either backend.
        """
        try:
            return self._search_edamam(name, grams)
        except FoodNotFoundError:
            return self._search_usda(name, grams)

    def _search_edamam(self, name: str, grams: float) -> dict:
        if not (self._app_id and self._app_key):
            raise FoodNotFoundError("Edamam not configured")
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

    # Generic processed/packaged terms that should disqualify a match unless
    # the user actually asked for them -- avoids "chicken breast" matching
    # "Lunchmeat, Chicken Breast, Sliced".
    _PENALTY_WORDS = {
        "lunchmeat", "cracker", "crackers", "chips", "frozen", "breaded",
        "fried", "roll", "deli", "glazed", "seasoned", "prepackaged",
        "mesquite", "rotisserie", "oscar mayer", "honey", "cake", "cakes",
        "bran", "flour", "oil", "bread", "snacks", "vermicelli",
    }

    def _usda_query(self, query: str) -> list[dict]:
        resp = httpx.get(
            _USDA_URL,
            params={
                "api_key": self._usda_key,
                "query": query,
                "dataType": "Foundation,SR Legacy",
                "pageSize": 15,
            },
            timeout=8,
        )
        if resp.status_code != 200:
            raise FoodNotFoundError(f"USDA API returned {resp.status_code}")
        return resp.json().get("foods", [])

    def _search_usda(self, name: str, grams: float) -> dict:
        try:
            # Plain single-word terms (e.g. "rice") rank snacks/flour ahead of
            # the actual cooked staple in USDA's relevance ranking -- a
            # "cooked" qualifier query surfaces the real food alongside it.
            foods = self._usda_query(name)
            foods += self._usda_query(f"{name} cooked")
        except Exception as exc:
            raise FoodNotFoundError(f"Network error: {exc}") from exc

        seen, merged = set(), []
        for f in foods:
            if f["fdcId"] not in seen:
                seen.add(f["fdcId"])
                merged.append(f)
        if not merged:
            raise FoodNotFoundError(f"No results for '{name}'")

        best = self._best_usda_match(name, merged)

        # USDA SR Legacy / Foundation nutrient values are always per 100g.
        nutrients = {}
        for n in best.get("foodNutrients", []):
            nm = n.get("nutrientName")
            if nm == "Energy" and n.get("unitName") != "KCAL":
                continue
            nutrients[nm] = n.get("value", 0)

        factor = grams / 100.0
        return {
            "food_name": best["description"].title(),
            "kcal":      round(nutrients.get("Energy", 0) * factor, 1),
            "protein_g": round(nutrients.get("Protein", 0) * factor, 1),
            "carbs_g":   round(nutrients.get("Carbohydrate, by difference", 0) * factor, 1),
            "fat_g":     round(nutrients.get("Total lipid (fat)", 0) * factor, 1),
        }

    def _best_usda_match(self, query: str, foods: list[dict]) -> dict:
        """Score candidates by word overlap with the query, penalize
        processed/packaged terms, and prefer Foundation over SR Legacy data."""
        query_words = set(query.lower().split())

        def score(food: dict) -> float:
            desc_words = set(food["description"].lower().replace(",", " ").split())
            overlap = len(query_words & desc_words)
            penalty = len(desc_words & self._PENALTY_WORDS) * 2
            type_bonus = 1 if food.get("dataType") == "Foundation" else 0
            length_penalty = len(desc_words) * 0.05  # shorter, simpler names win ties
            return overlap + type_bonus - penalty - length_penalty

        return max(foods, key=score)
