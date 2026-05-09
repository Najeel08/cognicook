# seed_recipes.py
# This script is retained only for quick demo data experiments.
# The final project uses the canonical CSV dataset loader.

import os
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(BASE_DIR)

from app import create_app
from extensions import db
from models.recipe import Recipe


def seed_recipes():
    if os.environ.get("COGNICOOK_ALLOW_DEMO_SEED") != "1":
        raise RuntimeError(
            "Demo seeding replaces all recipe rows. Set COGNICOOK_ALLOW_DEMO_SEED=1 to run it intentionally."
        )

    app = create_app()

    with app.app_context():
        db.session.query(Recipe).delete()

        recipes = [
            Recipe(
                title="Spicy Onion-Chilli Egg Bhurji",
                ingredients="egg,onion,green chilli,oil,salt",
                instructions=(
                    "Heat oil in a pan.\n"
                    "Add chopped onions and saute until golden.\n"
                    "Add green chillies and stir well.\n"
                    "Add beaten eggs and scramble on low heat.\n"
                    "Add salt and cook until fluffy."
                ),
                diet_type="non_veg",
                difficulty="easy",
                cooking_time=15,
                servings=2,
            ),
            Recipe(
                title="Aloo Tomato Sabzi",
                ingredients="potato,tomato,oil,salt,turmeric",
                instructions=(
                    "Heat oil in a pan.\n"
                    "Add potatoes and saute for 5 minutes.\n"
                    "Add tomatoes, turmeric, and salt.\n"
                    "Cover and cook until soft."
                ),
                diet_type="veg",
                difficulty="easy",
                cooking_time=20,
                servings=2,
            ),
            Recipe(
                title="Simple Chicken Rice",
                ingredients="chicken,rice,oil,salt,garlic",
                instructions=(
                    "Cook rice separately.\n"
                    "Heat oil and saute garlic.\n"
                    "Add chicken and cook thoroughly.\n"
                    "Mix rice with chicken and season with salt."
                ),
                diet_type="non_veg",
                difficulty="medium",
                cooking_time=30,
                servings=2,
            ),
            Recipe(
                title="Paneer Masala",
                ingredients="paneer,onion,tomato,oil,salt,garam masala",
                instructions=(
                    "Heat oil and saute onions.\n"
                    "Add tomatoes and cook into gravy.\n"
                    "Add paneer and garam masala.\n"
                    "Simmer for 5 minutes."
                ),
                diet_type="veg",
                difficulty="medium",
                cooking_time=25,
                servings=2,
            ),
            Recipe(
                title="Dal Tadka",
                ingredients="dal,garlic,oil,salt,red chilli powder",
                instructions=(
                    "Boil dal until soft.\n"
                    "Heat oil and saute garlic.\n"
                    "Add chilli powder and mix with dal.\n"
                    "Season with salt and simmer."
                ),
                diet_type="veg",
                difficulty="easy",
                cooking_time=25,
                servings=3,
            ),
        ]

        db.session.bulk_save_objects(recipes)
        db.session.commit()
        print("Indian recipes inserted successfully.")


if __name__ == "__main__":
    seed_recipes()
