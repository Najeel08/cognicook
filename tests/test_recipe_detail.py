from tests.base import (
    CogniCookTestCase,
    BASE_DIR,
    db,
    Recipe,
    load_dataset_rows,
    replace_recipe_rows,
)


class TestRecipeDetail(CogniCookTestCase):
    def test_recipe_detail_is_available_before_login_with_login_save_prompt(self):
        response = self.client.get("/recipe/1", follow_redirects=False)
        text = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn("Simple Curry", text)
        self.assertIn("Log in to Save", text)
        self.assertIn("Back", text)
        self.assertNotIn("Back to Dashboard", text)
        self.assertNotIn("Open Favorites", text)

    def test_updated_recipe_details_render_expected_content(self):
        expected = {
            "french toast": {
                "ingredients": ["bread", "egg", "milk", "sugar", "cardamom powder", "vanilla extract", "butter", "salt"],
                "measurements": ["4", "2", "1/2 cup", "2 tbsp", "1/2 tsp", "1/2 tsp", "2 tbsp", "1/4 tsp"],
                "steps": ["Beat 2 eggs", "Add the remaining 1 tbsp butter", "Rest for 1 minute"],
            },
            "ragi kanji": {
                "ingredients": ["ragi flour", "water", "milk", "jaggery", "cardamom"],
                "measurements": ["1/2 cup", "2 cups", "1 cup", "1/4 cup", "1/4 tsp (powder)"],
                "steps": ["Mix the ragi flour", "strained jaggery syrup", "serve warm"],
            },
            "cabbage thoran": {
                "ingredients": ["cabbage", "coconut", "green chilli", "onion", "curry leaves", "mustard seeds", "coconut oil", "turmeric powder", "salt"],
                "measurements": ["4 cups", "1 cup", "2", "1 cup", "8-10 leaves", "1 tsp", "3 tbsp", "1/2 tsp", "1 tsp"],
                "steps": ["Wash the cabbage", "mustard seeds", "freshly grated coconut"],
            },
            "bread omelette": {
                "ingredients": ["bread", "egg", "onion", "tomato", "green chilli", "coriander leaves", "butter", "salt", "black pepper"],
                "measurements": ["4", "3", "1/2 cup", "1/4 cup", "2", "1/4 cup", "2 tbsp", "3/4 tsp", "1/2 tsp"],
                "steps": ["Crack 3 eggs", "place 2 bread slices", "Rest for 1 minute"],
            },
        }

        with self.app.app_context():
            replace_recipe_rows(load_dataset_rows(BASE_DIR / "dataset" / "recipes.csv"), preserve_favorites=False)
            recipe_ids = {
                recipe.title: recipe.id
                for recipe in Recipe.query.filter(db.func.lower(Recipe.title).in_(expected)).all()
            }

        self.assertEqual(set(recipe_ids), set(expected))
        for title, detail in expected.items():
            response = self.client.get(f"/recipe/{recipe_ids[title]}")
            text = response.get_data(as_text=True)
            self.assertEqual(response.status_code, 200)
            self.assertIn(title, text)
            self.assertIn("Easy", text)
            self.assertIn("20 min", text)
            self.assertEqual(text.count('class="instruction-step"'), 6)
            for value in detail["ingredients"] + detail["measurements"] + detail["steps"]:
                self.assertIn(value, text)

    def test_recipe_detail_back_link_uses_safe_return_target(self):
        response = self.client.get(
            "/recipe/1?next=%2Frecommendations%3Fingredients%3Donion%2Ctomato%2Cpotato%26page%3D2",
            follow_redirects=False,
        )
        text = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn('href="/recommendations?ingredients=onion,tomato,potato&amp;page=2"', text)

        response = self.client.get("/recipe/1?next=https%3A%2F%2Fevil.example%2Fhijack", follow_redirects=False)
        text = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn('href="/dashboard"', text)
        self.assertNotIn("evil.example", text)

        response = self.client.get("/recipe/1?next=%2F%5Cevil.example%2Fhijack", follow_redirects=False)
        text = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn('href="/dashboard"', text)
        self.assertNotIn("evil.example", text)

    def test_tampered_user_session_does_not_raise_server_error(self):
        with self.client.session_transaction() as session:
            session["_user_id"] = "not-an-integer"

        response = self.client.get("/dashboard", follow_redirects=False)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Find recipes", response.data)

    def test_recipe_detail_uses_step_cards_for_instructions(self):
        self.register_user()
        self.login_user()

        with self.app.app_context():
            recipe = db.session.get(Recipe, 1)
            recipe.instructions = "Heat oil in a pan. Add onion and tomato. Serve hot."
            db.session.commit()

        response = self.client.get("/recipe/1")
        text = response.get_data(as_text=True)

        self.assertIn("instruction-steps", text)
        self.assertIn("Step 1", text)
        self.assertIn("Heat oil in a pan.", text)
        self.assertIn("Step 2", text)
        self.assertIn("Add onion and tomato.", text)
        self.assertIn("Step 3", text)
        self.assertIn("Serve hot.", text)

    def test_recipe_detail_hides_retired_metadata_and_shows_measurement_fallback(self):
        self.register_user()
        self.login_user()

        response = self.client.get("/recipe/1")
        text = response.get_data(as_text=True)

        self.assertIn("Ingredient Measurements", text)
        self.assertIn("Measurement data is not available yet.", text)
        self.assertNotIn("North Indian", text)
        self.assertNotIn("Delhi", text)

    def test_recipe_detail_renders_future_ingredient_measurements(self):
        self.register_user()
        self.login_user()

        with self.app.app_context():
            recipe = db.session.get(Recipe, 1)
            recipe.ingredient_measurements = "onion: 1 cup; tomato: 2 medium"
            db.session.commit()

        response = self.client.get("/recipe/1")
        text = response.get_data(as_text=True)

        self.assertIn("Ingredient Measurements", text)
        self.assertIn("onion", text)
        self.assertIn("1 cup", text)
        self.assertIn("tomato", text)
        self.assertIn("2 medium", text)
        self.assertNotIn("Measurement data is not available yet.", text)

