from tests.base import (
    CogniCookTestCase,
    Path,
    re,
    BASE_DIR,
    db,
    Recipe,
    bootstrap_recipe_data,
    load_dataset_rows,
    normalize_instructions,
    normalize_row,
    parse_ingredient_measurements,
    split_instruction_block,
)


class TestDatasetImport(CogniCookTestCase):
    def test_all_dataset_step_labels_create_clean_step_cards(self):
        rows = load_dataset_rows(BASE_DIR / "dataset" / "recipes.csv")
        step_label_pattern = re.compile(
            r"(?:^|(?<=[.!?]))\s*step\s*\d+\s*[:.)-]\s*",
            re.IGNORECASE,
        )

        for row in rows:
            labels = step_label_pattern.findall(row["instructions"])
            steps = split_instruction_block(row["instructions"])
            if labels:
                self.assertEqual(
                    len(steps),
                    len(labels),
                    f"{row['title']} did not preserve its explicit step count",
                )
            self.assertFalse(
                any(step_label_pattern.search(step) for step in steps),
                f"{row['title']} retained an embedded step label",
            )

        chicken_cutlet = next(row for row in rows if row["title"] == "chicken cutlet")
        cutlet_steps = split_instruction_block(chicken_cutlet["instructions"])
        self.assertEqual(len(cutlet_steps), 7)
        self.assertTrue(cutlet_steps[3].startswith("Add shredded chicken"))
        self.assertTrue(cutlet_steps[-1].startswith("Drain excess oil"))

    def test_raw_and_canonical_datasets_normalize_identically(self):
        raw_rows = load_dataset_rows(BASE_DIR / "dataset" / "raw_recipes.csv")
        canonical_rows = load_dataset_rows(BASE_DIR / "dataset" / "recipes.csv")

        self.assertEqual(raw_rows, canonical_rows)
        self.assertEqual(len(canonical_rows), 333)

        for row in canonical_rows:
            measurement_text = row["ingredient_measurements"]
            self.assertNotIn("number", measurement_text.lower())
            self.assertIsNone(re.search(r"(?<![/\d.])\b(?:[2-9]\d*|1\.\d+|[2-9]\d*\.\d+) cup\b", measurement_text))
            self.assertIsNone(re.search(r"\b\d+(?:\.\d+)? liter\b", measurement_text, re.IGNORECASE))
            self.assertNotIn("to taste", measurement_text)
            ingredients = [ingredient for ingredient in row["ingredients"].split(",") if ingredient]
            measurements = parse_ingredient_measurements(
                row["ingredient_measurements"],
                known_ingredients=row["ingredients"],
            )
            self.assertEqual(
                len(measurements),
                len(ingredients),
                f"{row['title']} should include one measurement per ingredient",
            )

    def test_data_loader_preserves_multiline_instruction_boundaries(self):
        self.assertEqual(
            normalize_instructions("Wash rice\nCook with water\nServe hot"),
            "Wash rice. Cook with water. Serve hot.",
        )

    def test_data_loader_normalizes_optional_future_measurements(self):
        row = normalize_row(
            {
                "title": "Measured Curry",
                "ingredients": "onion,tomato,salt",
                "ingredient_measurements": "onion: 1 cup; tomato: 2 medium",
                "instructions": "Cook everything.",
                "diet_type": "veg",
                "difficulty": "easy",
                "cooking_time": "20",
            }
        )

        records = parse_ingredient_measurements(row["ingredient_measurements"])
        self.assertEqual(row["cleaned_ingredients"], "onion,tomato,salt")
        self.assertEqual(records[0].ingredient, "onion")
        self.assertEqual(records[0].display_measurement, "1 cup")
        self.assertEqual(records[1].ingredient, "tomato")
        self.assertEqual(records[1].display_measurement, "2 medium")

    def test_recipe_model_keeps_cleaned_ingredients_in_sync(self):
        with self.app.app_context():
            recipe = Recipe(
                title="Sync Demo",
                ingredients="Tomatoes, finely chopped onions, salt",
                instructions="Cook everything.",
                diet_type="veg",
                difficulty="easy",
                cooking_time=15,
            )
            db.session.add(recipe)
            db.session.commit()

            self.assertEqual(recipe.cleaned_ingredients, "tomato,onion,salt")

            recipe.ingredients = "ginger garlic paste, curd, cumin"
            db.session.commit()

            self.assertEqual(recipe.cleaned_ingredients, "ginger,garlic,yogurt,cumin seeds")
            self.assertEqual(recipe.ingredient_list(), ["ginger", "garlic", "yogurt", "cumin seeds"])

            recipe.ingredients = "cashew, cream"
            db.session.commit()

            self.assertEqual(recipe.cleaned_ingredients, "cashew nuts,cream")
            self.assertEqual(recipe.ingredient_list(), ["cashew nuts", "cream"])

    def test_data_loader_accepts_supported_diet_labels(self):
        vegetarian = normalize_row(
            {
                "title": "Vegetable Demo",
                "ingredients": "onion,tomato,salt",
                "instructions": "Cook everything.",
                "diet_type": "Vegetarian",
                "difficulty": "Easy",
                "cooking_time": "20",
            }
        )
        non_vegetarian = normalize_row(
            {
                "title": "Chicken Demo",
                "ingredients": "chicken,onion,salt",
                "instructions": "Cook everything.",
                "diet_type": "Non-Vegetarian",
                "difficulty": "Medium",
                "cooking_time": "25",
            }
        )

        self.assertEqual(vegetarian["diet_type"], "veg")
        self.assertEqual(non_vegetarian["diet_type"], "non_veg")

    def test_data_loader_rejects_unsupported_gluten_free_label(self):
        row = normalize_row(
            {
                "title": "Gluten Free Demo",
                "ingredients": "rice,coconut,salt",
                "instructions": "Cook everything.",
                "diet_type": "Gluten-Free",
                "difficulty": "Medium",
                "cooking_time": "25",
            }
        )

        self.assertIsNone(row)

    def test_bootstrap_recipe_data_refreshes_stale_database_and_deduplicates_dataset(self):
        dataset_path = Path(__file__).parent / "fixtures" / "bootstrap_recipes.csv"

        with self.app.app_context():
            imported = bootstrap_recipe_data(str(dataset_path))

            self.assertEqual(imported, 2)
            self.assertEqual(Recipe.query.count(), 2)
            self.assertEqual(
                sorted(recipe.title for recipe in Recipe.query.all()),
                ["Alpha Rice", "Beta Curry"],
            )

