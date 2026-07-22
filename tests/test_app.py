import os
from pathlib import Path
import re
import unittest

os.environ["COGNICOOK_SKIP_APP_BOOTSTRAP"] = "1"

from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.pool import StaticPool

from app import create_app
from config import BASE_DIR, resolve_project_path
from extensions import db
from models.favorite import Favorite
from models.recipe import Recipe
from models.user import User
from services.data_loader import bootstrap_recipe_data, load_dataset_rows, normalize_instructions, normalize_row, replace_recipe_rows
from services.recipe_service import get_similar_recommendations, get_strict_recommendations, parse_ingredient_query, sort_similar_matches
from utils.ingredient_cleaner import clean_ingredients
from utils.ingredient_measurements import parse_ingredient_measurements
from utils.instructions import split_instruction_block
from utils.pagination import paginate_list


class CogniCookAppTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        class TestConfig:
            TESTING = True
            SECRET_KEY = "test-secret-key"
            SQLALCHEMY_DATABASE_URI = "sqlite://"
            SQLALCHEMY_TRACK_MODIFICATIONS = False
            SQLALCHEMY_ENGINE_OPTIONS = {
                "connect_args": {"check_same_thread": False},
                "poolclass": StaticPool,
            }
            SESSION_COOKIE_HTTPONLY = True
            SESSION_COOKIE_SAMESITE = "Lax"
            SESSION_COOKIE_SECURE = False
            REMEMBER_COOKIE_HTTPONLY = True
            REMEMBER_COOKIE_SAMESITE = "Lax"
            REMEMBER_COOKIE_SECURE = False
            MAX_CONTENT_LENGTH = 1024 * 1024
            RESULTS_PER_PAGE = 2
            MAX_PER_PAGE = 10
            AUTH_ACCOUNT_LOCKOUT_WINDOW_SECONDS = 15 * 60
            AUTH_ACCOUNT_LOCKOUT_MAX_ATTEMPTS = 5
            AUTO_BOOTSTRAP_DATA = False
            TRUSTED_HOSTS = None

        cls.app = create_app(TestConfig)

    @classmethod
    def tearDownClass(cls):
        with cls.app.app_context():
            db.session.remove()
            db.engine.dispose()

    def setUp(self):
        self.client = self.app.test_client()
        with self.app.app_context():
            self.app.extensions["security_tools"]["reset_auth_rate_limits"]()
            db.drop_all()
            db.create_all()
            db.session.add_all(
                [
                    Recipe(
                        title="Simple Curry",
                        ingredients="onion,tomato,potato,salt,oil",
                        instructions="Cook everything together.",
                        diet_type="veg",
                        difficulty="easy",
                        cooking_time=20,
                    ),
                    Recipe(
                        title="Paneer Masala",
                        ingredients="onion,tomato,paneer,salt,oil",
                        instructions="Cook paneer in masala.",
                        diet_type="veg",
                        difficulty="medium",
                        cooking_time=25,
                    ),
                    Recipe(
                        title="Tomato Rice",
                        ingredients="rice,tomato,onion,salt,oil",
                        instructions="Cook rice and mix with tomato masala.",
                        diet_type="veg",
                        difficulty="easy",
                        cooking_time=18,
                    ),
                    Recipe(
                        title="Dal Fry",
                        ingredients="onion,tomato,lentil,cumin,salt,oil",
                        instructions="Cook lentils and temper with spices.",
                        diet_type="veg",
                        difficulty="medium",
                        cooking_time=30,
                    ),
                    Recipe(
                        title="Vegetable Korma",
                        ingredients="onion,tomato,potato,paneer,cream,cashew,salt,oil",
                        instructions="Cook vegetables in rich gravy.",
                        diet_type="veg",
                        difficulty="hard",
                        cooking_time=40,
                    ),
                    Recipe(
                        title="Masala Omelette",
                        ingredients="egg,onion,tomato,green chilli,salt,oil",
                        instructions="Whisk eggs and cook with vegetables.",
                        diet_type="non_veg",
                        difficulty="easy",
                        cooking_time=10,
                    ),
                ]
            )
            db.session.commit()

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()

    def get_csrf_token(self, path="/login"):
        self.client.get(path)
        with self.client.session_transaction() as session:
            return session["_csrf_token"]

    def register_user(self, username="tester_user", email="tester@example.com", password="SecurePass8"):
        token = self.get_csrf_token("/register")
        return self.client.post(
            "/register",
            data={
                "username": username,
                "email": email,
                "password": password,
                "confirm_password": password,
                "csrf_token": token,
            },
            follow_redirects=True,
        )

    def login_user(self, username="tester_user", password="SecurePass8"):
        token = self.get_csrf_token("/login")
        return self.client.post(
            "/login",
            data={"username": username, "password": password, "csrf_token": token},
            follow_redirects=True,
        )

    def test_relative_configuration_paths_resolve_from_project_root(self):
        self.assertEqual(
            resolve_project_path("instance/test.db", "unused"),
            BASE_DIR / "instance" / "test.db",
        )
        absolute_path = BASE_DIR / "dataset" / "recipes.csv"
        self.assertEqual(resolve_project_path(absolute_path, "unused"), absolute_path)

    def test_register_requires_csrf(self):
        response = self.client.post(
            "/register",
            data={"username": "tester_user", "email": "tester@example.com", "password": "SecurePass8"},
        )
        self.assertEqual(response.status_code, 400)

    def test_register_validates_email_username_and_password_strength(self):
        response = self.register_user(email="invalid-email")
        self.assertIn("Please enter a valid email address.", response.get_data(as_text=True))

        response = self.register_user(email="user@domain.c")
        self.assertIn("Please enter a valid email address.", response.get_data(as_text=True))

        response = self.register_user(email=".user@example.com")
        self.assertIn("Please enter a valid email address.", response.get_data(as_text=True))

        response = self.register_user(email="amban@gmail.co")
        self.assertIn("Please enter a valid email address.", response.get_data(as_text=True))

        response = self.register_user(email="person@example.co")
        self.assertIn("Welcome, tester_user", response.get_data(as_text=True))

        response = self.register_user(username="ab", email="another@example.com")
        self.assertIn("Username must be 3 to 30 characters", response.get_data(as_text=True))

        response = self.register_user(password="weakpass")
        text = response.get_data(as_text=True)
        self.assertIn("Password must include at least one uppercase letter.", text)
        self.assertIn("Password must include at least one number.", text)

        response = self.register_user(password="AAAA1111")
        self.assertIn("Password cannot contain simple repeated sequences", response.get_data(as_text=True))

        response = self.register_user(password="Abcd1234")
        self.assertIn("Password cannot contain obvious sequential patterns", response.get_data(as_text=True))

        response = self.register_user(password="Safe9876Pass")
        self.assertIn("Password cannot contain obvious sequential patterns", response.get_data(as_text=True))

        response = self.register_user(password="Password123")
        self.assertIn("Password is too common", response.get_data(as_text=True))

    def test_register_rejects_mismatched_confirmation_and_unavailable_identity(self):
        token = self.get_csrf_token("/register")
        response = self.client.post(
            "/register",
            data={
                "username": "tester_user",
                "email": "tester@example.com",
                "password": "SecurePass8",
                "confirm_password": "SecurePass9",
                "csrf_token": token,
            },
            follow_redirects=True,
        )
        self.assertIn("Password confirmation does not match.", response.get_data(as_text=True))

        self.register_user()

        response = self.register_user(username="second_user")
        self.assertIn(
            "Email address already in use. Please log in instead.",
            response.get_data(as_text=True),
        )

        response = self.register_user(username="TESTER_USER", email="second@example.com")
        self.assertIn("Username not available.", response.get_data(as_text=True))

    def test_register_rejects_overlong_username_without_truncating(self):
        response = self.register_user(username="a" * 31)
        self.assertIn("Username must be 3 to 30 characters", response.get_data(as_text=True))

        with self.app.app_context():
            self.assertIsNone(User.query.filter_by(email="tester@example.com").first())

    def test_registration_rate_limit_blocks_repeated_invalid_submissions(self):
        original_ip_limit = self.app.config.get("AUTH_REGISTER_RATE_LIMIT_MAX_ATTEMPTS")
        original_account_limit = self.app.config.get("AUTH_REGISTER_ACCOUNT_LOCKOUT_MAX_ATTEMPTS")
        self.app.config["AUTH_REGISTER_RATE_LIMIT_MAX_ATTEMPTS"] = 2
        self.app.config["AUTH_REGISTER_ACCOUNT_LOCKOUT_MAX_ATTEMPTS"] = 2
        try:
            for _ in range(2):
                response = self.register_user(email="invalid-email")
                self.assertEqual(response.status_code, 200)

            response = self.register_user(email="invalid-email")
            self.assertEqual(response.status_code, 429)
            self.assertIn("Too many registration attempts", response.get_data(as_text=True))
        finally:
            if original_ip_limit is None:
                self.app.config.pop("AUTH_REGISTER_RATE_LIMIT_MAX_ATTEMPTS", None)
            else:
                self.app.config["AUTH_REGISTER_RATE_LIMIT_MAX_ATTEMPTS"] = original_ip_limit
            if original_account_limit is None:
                self.app.config.pop("AUTH_REGISTER_ACCOUNT_LOCKOUT_MAX_ATTEMPTS", None)
            else:
                self.app.config["AUTH_REGISTER_ACCOUNT_LOCKOUT_MAX_ATTEMPTS"] = original_account_limit

    def test_register_and_login_flow_uses_expected_success_message(self):
        response = self.register_user(email="USER@Example.com")
        registration_text = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn("Welcome, tester_user", registration_text)
        self.assertIn("<h2>Login</h2>", registration_text)
        self.assertNotIn("Welcome Back", registration_text)

        response = self.login_user(username="tester@example.com")
        self.assertIn("Invalid username or password.", response.get_data(as_text=True))

        response = self.login_user()
        text = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn("Welcome, tester_user", text)
        self.assertIn("Search Recipes", text)
        self.assertNotIn("Recipe Explorer", text)

        with self.app.app_context():
            user = User.query.filter_by(email="user@example.com").first()
            self.assertIsNotNone(user)
            self.assertEqual(user.username, "tester_user")

    def test_login_rotates_csrf_token_after_authentication(self):
        self.register_user()
        original_token = self.get_csrf_token("/login")

        response = self.client.post(
            "/login",
            data={"username": "tester_user", "password": "SecurePass8", "csrf_token": original_token},
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 302)
        with self.client.session_transaction() as session:
            self.assertNotEqual(session["_csrf_token"], original_token)

    def test_dashboard_requires_at_least_one_valid_ingredient(self):
        self.register_user()
        self.login_user()
        token = self.get_csrf_token("/dashboard")

        response = self.client.post(
            "/dashboard",
            data={"ingredients": "12345", "csrf_token": token},
            follow_redirects=True,
        )

        self.assertIn("at least one valid ingredient", response.get_data(as_text=True))
        self.assertIn('role="alert"', response.get_data(as_text=True))

    def test_dashboard_only_shows_ingredient_input_before_search(self):
        self.register_user()
        response = self.login_user(username="tester@example.com")
        self.assertIn("Invalid username or password.", response.get_data(as_text=True))

        response = self.login_user()
        text = response.get_data(as_text=True)

        self.assertIn("Welcome, tester_user", text)
        self.assertIn("Available ingredients", text)
        self.assertIn("Example: bread, egg, milk, cardamom powder, butter, vanilla extract", text)
        self.assertIn("Search Recipes", text)
        self.assertNotIn("Recipe Explorer", text)
        self.assertNotIn("Simple Curry", text)

    def test_ingredient_cleaner_expands_common_aliases_and_compounds(self):
        self.assertEqual(
            clean_ingredients("ginger garlic paste, cumin, green chilies, curd, cilantro"),
            ["ginger", "garlic", "cumin seeds", "green chilli", "yogurt", "coriander leaves"],
        )
        self.assertEqual(
            clean_ingredients("finely chopped carrots, soaked lentils, cashews"),
            ["carrot", "lentil", "cashew nuts"],
        )
        self.assertEqual(
            clean_ingredients("1 cup rice, 2 tbsp oil, 250 grams tomatoes"),
            ["rice", "oil", "tomato"],
        )
        self.assertEqual(
            clean_ingredients("2 cups green gram, 250 grams tomatoes"),
            ["green gram", "tomato"],
        )
        self.assertEqual(
            clean_ingredients("onion/tomato/potato"),
            ["onion", "tomato", "potato"],
        )
        self.assertEqual(
            clean_ingredients("ginger-garlic paste"),
            ["ginger", "garlic"],
        )
        self.assertEqual(
            clean_ingredients("cashew nuts, cashew, cashews"),
            ["cashew nuts"],
        )

    def test_relevance_value_uses_proposal_weights_and_bounds(self):
        from services.recipe_service import relevance_value

        score = relevance_value(0.5, 0.5, 0.5, 5, 5, 0.5)
        self.assertAlmostEqual(score, 7.5)

        score_at_max_missing = relevance_value(1.0, 1.0, 1.0, 5, 5, 1.0)
        self.assertAlmostEqual(score_at_max_missing, 15.0)

        score_one_missing = relevance_value(1.0, 1.0, 1.0, 1, 5, 1.0)
        self.assertAlmostEqual(score_one_missing, 83.0)
        self.assertGreater(score_one_missing, score_at_max_missing)

        self.assertEqual(relevance_value(1.0, 1.0, 1.0, -1, 5, 1.0), 100.0)
        self.assertEqual(relevance_value(0.0, 0.0, 0.0, 10, 5, 0.0), 0.0)

    def test_dashboard_requires_at_least_three_valid_ingredients(self):
        self.register_user()
        self.login_user()
        token = self.get_csrf_token("/dashboard")

        response = self.client.post(
            "/dashboard",
            data={"ingredients": "onion, tomato", "csrf_token": token},
            follow_redirects=True,
        )

        text = response.get_data(as_text=True)
        self.assertIn("Enter at least 3 valid ingredients", text)
        self.assertIn("Available ingredients", text)

    def test_instruction_parser_preserves_single_action_phrases(self):
        self.assertEqual(
            split_instruction_block("Add oil and heat the pan."),
            ["Add oil and heat the pan."],
        )

    def test_instruction_parser_strips_dataset_step_labels(self):
        self.assertEqual(
            split_instruction_block("Step 1: Heat oil. Step 2: Add onion."),
            ["Heat oil.", "Add onion."],
        )

    def test_instruction_parser_preserves_compact_explicit_steps(self):
        self.assertEqual(
            split_instruction_block(
                "Step 1: Boil potato until soft.Peel and mash completely."
                "Step 2: Heat oil.Add onion and saute until soft."
            ),
            [
                "Boil potato until soft.Peel and mash completely.",
                "Heat oil.Add onion and saute until soft.",
            ],
        )

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

    def test_ingredient_measurement_parser_accepts_future_dataset_shapes(self):
        records = parse_ingredient_measurements(
            '[{"ingredient":"Onion","quantity":"1","unit":"cup"},{"ingredient":"Tomato","measurement":"2 medium"}]',
            known_ingredients="onion,tomato,salt",
        )

        self.assertEqual(records[0].ingredient, "onion")
        self.assertEqual(records[0].display_measurement, "1 cup")
        self.assertEqual(records[1].ingredient, "tomato")
        self.assertEqual(records[1].display_measurement, "2 medium")

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

    def test_auth_pages_use_contextual_greetings_without_security_hint(self):
        login_response = self.client.get("/login")
        login_text = login_response.get_data(as_text=True)
        self.assertIn("Welcome", login_text)
        self.assertIn('href="/register"', login_text)
        self.assertIn('class="brandmark" href="/dashboard"', login_text)
        self.assertIn('href="/dashboard" class="btn btn-neon-secondary"', login_text)
        self.assertIn('href="/login" class="btn btn-neon-secondary"', login_text)
        self.assertIn('name="username"', login_text)
        self.assertIn('data-password-toggle', login_text)
        self.assertIn('aria-label="Show password"', login_text)
        self.assertIn('aria-label="Primary navigation"', login_text)
        self.assertNotIn("bootstrap.bundle.min.js", login_text)
        self.assertNotIn("welcome back", login_text.lower())
        self.assertNotIn("Repeated failed logins are rate limited automatically", login_text)

        register_response = self.client.get("/register")
        register_text = register_response.get_data(as_text=True)
        self.assertIn("Create your account", register_text)
        self.assertIn('action="/register"', register_text)
        self.assertEqual(register_text.count('data-password-toggle'), 2)

    def test_recommendations_page_shows_only_strict_results_and_similar_button(self):
        self.register_user()
        self.login_user()
        token = self.get_csrf_token("/dashboard")

        response = self.client.post(
            "/dashboard",
            data={"ingredients": "onion, tomato, potato, oil", "csrf_token": token},
            follow_redirects=True,
        )

        text = response.get_data(as_text=True)
        self.assertIn("Exact Recipe Matches", text)
        self.assertIn("Simple Curry", text)
        self.assertIn("0 extras needed", text)
        self.assertIn("View Similar Recipes", text)
        self.assertNotIn("Similar Matches", text)

    def test_free_text_ingredient_query_splits_known_ingredients(self):
        with self.app.app_context():
            db.session.add(
                Recipe(
                    title="Chicken Demo",
                    ingredients="chicken,onion,tomato,salt,oil",
                    instructions="Cook chicken.",
                    diet_type="non_veg",
                    difficulty="easy",
                    cooking_time=20,
                )
            )
            db.session.commit()

            ingredients, normalized_text = parse_ingredient_query("chicken onion tomato")

        self.assertEqual(ingredients, ["chicken", "onion", "tomato"])
        self.assertEqual(normalized_text, "chicken, onion, tomato")

    def test_strict_recommendations_rank_more_complete_exact_matches_first(self):
        with self.app.app_context():
            db.session.add_all(
                [
                    Recipe(
                        title="Onion Tomato Curry",
                        ingredients="onion,tomato,salt,oil",
                        instructions="Cook onion and tomato.",
                        diet_type="veg",
                        difficulty="easy",
                        cooking_time=15,
                    ),
                    Recipe(
                        title="Chicken Onion Tomato Curry",
                        ingredients="chicken,onion,tomato,salt,oil",
                        instructions="Cook chicken with onion and tomato.",
                        diet_type="non_veg",
                        difficulty="easy",
                        cooking_time=25,
                    ),
                ]
            )
            db.session.commit()

            results = get_strict_recommendations("chicken onion tomato oil", page=1, per_page=10)
            titles = [recipe.title for recipe in results["strict"].items]

        self.assertLess(titles.index("Chicken Onion Tomato Curry"), titles.index("Onion Tomato Curry"))

    def test_similar_recommendations_prioritize_exact_title_intent(self):
        with self.app.app_context():
            db.session.add_all(
                [
                    Recipe(
                        title="Egg Roast",
                        ingredients="egg,pepper,salt,oil",
                        instructions="Roast boiled eggs in masala.",
                        diet_type="non_veg",
                        difficulty="easy",
                        cooking_time=35,
                    ),
                    Recipe(
                        title="Egg Curry",
                        ingredients="egg,coconut milk,salt,water",
                        instructions="Cook eggs in curry.",
                        diet_type="non_veg",
                        difficulty="easy",
                        cooking_time=40,
                    ),
                ]
            )
            db.session.commit()

            results = get_similar_recommendations(
                "egg roast oil",
                {"diet": None, "difficulty": None, "sort": "relevance"},
                page=1,
                per_page=10,
            )
            titles = [item["recipe"].title for item in results["similar"].items]

        self.assertIn("Egg Roast", titles)
        self.assertEqual(titles[0], "Egg Roast")

    def test_similar_recommendations_include_short_primary_ingredient_queries(self):
        with self.app.app_context():
            db.session.add(
                Recipe(
                    title="Chicken Roast",
                    ingredients="chicken,onion,salt,oil",
                    instructions="Roast chicken with masala.",
                    diet_type="non_veg",
                    difficulty="medium",
                    cooking_time=45,
                )
            )
            db.session.commit()

            results = get_similar_recommendations(
                "chicken curry",
                {"diet": None, "difficulty": None, "sort": "relevance"},
                page=1,
                per_page=10,
            )
            titles = [item["recipe"].title for item in results["similar"].items]

        self.assertIn("Chicken Roast", titles)

    def test_similar_recommendations_exclude_title_matches_with_too_many_missing_ingredients(self):
        with self.app.app_context():
            db.session.add(
                Recipe(
                    title="Chicken Roast",
                    ingredients="chicken,onion,tomato,green chilli,ginger,garlic,curry leaves,chilli powder,coriander powder,turmeric powder,garam masala,salt,oil",
                    instructions="Roast chicken with masala.",
                    diet_type="non_veg",
                    difficulty="medium",
                    cooking_time=45,
                )
            )
            db.session.commit()

            results = get_similar_recommendations(
                "chicken roast",
                {"diet": None, "difficulty": None, "sort": "relevance"},
                page=1,
                per_page=10,
                max_missing=5,
            )
            titles = [item["recipe"].title for item in results["similar"].items]

        self.assertNotIn("Chicken Roast", titles)

    def test_similar_recommendations_rank_complete_query_matches_above_partial_matches(self):
        with self.app.app_context():
            db.session.add_all(
                [
                    Recipe(
                        title="Chicken Onion Tomato Masala",
                        ingredients="chicken,onion,tomato,ginger,garlic,chilli powder,salt,oil",
                        instructions="Cook chicken with onion and tomato.",
                        diet_type="non_veg",
                        difficulty="medium",
                        cooking_time=35,
                    ),
                    Recipe(
                        title="Onion Tomato Masala",
                        ingredients="onion,tomato,ginger,salt,oil",
                        instructions="Cook onion and tomato.",
                        diet_type="veg",
                        difficulty="easy",
                        cooking_time=20,
                    ),
                ]
            )
            db.session.commit()

            results = get_similar_recommendations(
                "chicken onion tomato",
                {"diet": None, "difficulty": None, "sort": "relevance"},
                page=1,
                per_page=10,
            )
            titles = [item["recipe"].title for item in results["similar"].items]

        self.assertLess(titles.index("Onion Tomato Masala"), titles.index("Chicken Onion Tomato Masala"))

    def test_similar_relevance_percent_follows_default_ranking(self):
        with self.app.app_context():
            results = get_similar_recommendations(
                "onion tomato potato",
                {"diet": None, "difficulty": None, "sort": "relevance"},
                page=1,
                per_page=10,
            )
            items = results["similar"].items
            missing_counts = [item["missing_count"] for item in items]

        self.assertGreaterEqual(len(missing_counts), 2)
        self.assertEqual(missing_counts, sorted(missing_counts))
        for previous, current in zip(items, items[1:]):
            if previous["missing_count"] == current["missing_count"]:
                self.assertGreaterEqual(previous["relevance_value"], current["relevance_value"])
                self.assertEqual(previous["relevance_score"], previous["relevance_value"])

    def test_similar_relevance_orders_target_query_by_matches_then_raw_score(self):
        with self.app.app_context():
            replace_recipe_rows(load_dataset_rows(BASE_DIR / "dataset" / "recipes.csv"), preserve_favorites=False)
            results = get_similar_recommendations(
                "onion, tomato, chicken, fish, rice, egg, maida",
                {"diet": "", "difficulty": "", "sort": "relevance"},
                page=1,
                per_page=30,
            )
            items = results["similar"].items

        self.assertGreaterEqual(len(items), 10)
        missing_counts = [item["missing_count"] for item in items]
        self.assertEqual(missing_counts, sorted(missing_counts))
        for previous, current in zip(items, items[1:]):
            if previous["missing_count"] == current["missing_count"]:
                self.assertGreaterEqual(previous["relevance_value"], current["relevance_value"])
                self.assertGreaterEqual(previous["relevance_percent"], current["relevance_percent"])
                self.assertEqual(previous["relevance_score"], previous["relevance_value"])

    def test_similar_recommendations_do_not_overmatch_bacalhau_ingredients(self):
        with self.app.app_context():
            replace_recipe_rows(load_dataset_rows(BASE_DIR / "dataset" / "recipes.csv"), preserve_favorites=False)
            results = get_similar_recommendations(
                "Garlic,onion,fish,potato,egg,parsley",
                {"diet": "", "difficulty": "", "sort": "relevance"},
                page=1,
                per_page=30,
            )
            bacalhau_title = "bacalhau " + chr(0x00E0) + " br" + chr(0x00E1) + "s"
            bacalhau_match = next(
                item for item in results["similar"].items if item["recipe"].title == bacalhau_title
            )

        self.assertEqual(bacalhau_match["match_count"], 4)
        self.assertEqual(bacalhau_match["required_count"], 9)
        self.assertEqual(
            bacalhau_match["matched"],
            ["egg", "garlic", "onion", "parsley"],
        )
        self.assertEqual(
            bacalhau_match["missing"],
            ["black olives", "black pepper", "olive oil", "potato sticks", "salted cod"],
        )

    def test_similar_recommendations_match_bacalhau_when_cod_is_entered(self):
        with self.app.app_context():
            replace_recipe_rows(load_dataset_rows(BASE_DIR / "dataset" / "recipes.csv"), preserve_favorites=False)
            results = get_similar_recommendations(
                "Garlic,onion,cod,egg,parsley",
                {"diet": "", "difficulty": "", "sort": "relevance"},
                page=1,
                per_page=30,
            )
            bacalhau_title = "bacalhau " + chr(0x00E0) + " br" + chr(0x00E1) + "s"
            bacalhau_match = next(
                item for item in results["similar"].items if item["recipe"].title == bacalhau_title
            )

        self.assertEqual(bacalhau_match["match_count"], 5)
        self.assertEqual(
            bacalhau_match["matched"],
            ["egg", "garlic", "onion", "parsley", "salted cod"],
        )
        self.assertEqual(bacalhau_match["missing"], ["black olives", "black pepper", "olive oil", "potato sticks"])

    def test_similar_recommendations_match_chocolate_family_ingredients(self):
        with self.app.app_context():
            replace_recipe_rows(load_dataset_rows(BASE_DIR / "dataset" / "recipes.csv"), preserve_favorites=False)
            parsed, normalized = parse_ingredient_query("bread, milk, chocolate")
            results = get_similar_recommendations(
                "bread, milk, chocolate",
                {"diet": "", "difficulty": "", "sort": "relevance"},
                page=1,
                per_page=30,
            )
            items_by_title = {item["recipe"].title: item for item in results["similar"].items}

        self.assertEqual(parsed, ["bread", "milk", "chocolate"])
        self.assertEqual(normalized, "bread, milk, chocolate")
        self.assertIn("chocolate pudding", items_by_title)
        self.assertIn("oreo milkshake", items_by_title)
        self.assertNotIn("hot chocolate", items_by_title)
        self.assertIn("chocolate chips", items_by_title["chocolate pudding"]["matched"])
        self.assertIn("chocolate syrup", items_by_title["oreo milkshake"]["matched"])
        self.assertNotIn("cocoa powder", items_by_title["chocolate pudding"]["matched"])

    def test_generic_olives_and_oil_match_variants_without_unsafe_potato_overmatch(self):
        with self.app.app_context():
            replace_recipe_rows(load_dataset_rows(BASE_DIR / "dataset" / "recipes.csv"), preserve_favorites=False)
            results = get_similar_recommendations(
                "oil,olives,onion,garlic,egg,parsley,cod,potato",
                {"diet": "", "difficulty": "", "sort": "relevance"},
                page=1,
                per_page=30,
            )
            bacalhau_title = "bacalhau " + chr(0x00E0) + " br" + chr(0x00E1) + "s"
            bacalhau_match = next(
                item for item in results["similar"].items if item["recipe"].title == bacalhau_title
            )

        self.assertIn("black olives", bacalhau_match["matched"])
        self.assertNotIn("olive oil", bacalhau_match["matched"])
        self.assertIn("olive oil", bacalhau_match["missing"])
        self.assertIn("potato sticks", bacalhau_match["missing"])
        self.assertNotIn("potato sticks", bacalhau_match["matched"])

    def test_recipe_discovery_is_available_before_login_but_save_requires_login(self):
        response = self.client.get("/recommendations?ingredients=onion,tomato,potato,oil")
        text = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn("Simple Curry", text)
        self.assertIn("Log in to Save", text)
        self.assertNotIn(">Save</button>", text)

    def test_pagination_marks_current_and_disabled_controls_for_screen_readers(self):
        self.register_user()
        self.login_user()

        response = self.client.get("/similar?ingredients=onion,tomato,potato,oil&per_page=2")
        text = response.get_data(as_text=True)

        self.assertIn('aria-current="page"', text)
        self.assertIn('aria-disabled="true">Previous</span>', text)

    def test_pagination_clamps_page_numbers_above_last_page(self):
        pagination = paginate_list(["one", "two", "three"], page=99, per_page=2)

        self.assertEqual(pagination.page, 2)
        self.assertEqual(pagination.items, ["three"])
        self.assertFalse(pagination.has_next)

    def test_strict_matching_allows_only_common_basics_to_be_missing(self):
        self.register_user()
        self.login_user()

        response = self.client.get("/recommendations?ingredients=rice,onion,beans")
        text = response.get_data(as_text=True)

        self.assertIn("No exact recipes found for these ingredients.", text)

        with self.app.app_context():
            db.session.add(
                Recipe(
                    title="Rice Kanji",
                    ingredients="rice,water,salt",
                    instructions="Wash rice. Cook with water. Add salt.",
                    diet_type="veg",
                    difficulty="easy",
                    cooking_time=25,
                )
            )
            db.session.commit()

        response = self.client.get("/recommendations?ingredients=rice,onion,beans")
        text = response.get_data(as_text=True)
        self.assertIn("Rice Kanji", text)

    def test_strict_matching_accepts_slash_separated_ingredients(self):
        response = self.client.get("/recommendations?ingredients=onion/tomato/potato/oil")
        text = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn("Simple Curry", text)
        self.assertIn("onion", text)
        self.assertIn("tomato", text)
        self.assertIn("potato", text)

    def test_recommendations_page_shows_empty_state_when_no_strict_match_exists(self):
        self.register_user()
        self.login_user()

        response = self.client.get("/recommendations?ingredients=spinach,lentil,beans")
        text = response.get_data(as_text=True)

        self.assertIn("No exact recipes found for these ingredients.", text)
        self.assertIn("View Similar Recipes", text)

    def test_similar_page_limits_results_to_five_missing_ingredients(self):
        self.register_user()
        self.login_user()

        with self.app.app_context():
            db.session.add(
                Recipe(
                    title="Five Extra Masala",
                    ingredients="onion,tomato,ginger,garlic,curry leaves,chilli powder,coriander powder,salt,oil",
                    instructions="Cook onion and tomato with spices.",
                    diet_type="veg",
                    difficulty="medium",
                    cooking_time=30,
                )
            )
            db.session.commit()

        response = self.client.get("/similar?ingredients=onion,tomato,potato,oil&per_page=10")
        text = response.get_data(as_text=True)

        self.assertIn("Paneer Masala", text)
        self.assertIn("Tomato Rice", text)
        self.assertIn("Dal Fry", text)
        self.assertIn("Vegetable Korma", text)
        self.assertIn("Five Extra Masala", text)
        self.assertIn("<strong>Missing extras:</strong> chilli powder, coriander powder, curry leaves, garlic, ginger", text)
        self.assertNotIn("No similar recipes found.", text)

    def test_similar_page_default_sort_is_relevance(self):
        self.register_user()
        self.login_user()

        response = self.client.get("/similar?ingredients=onion,tomato,potato,oil&per_page=10")
        text = response.get_data(as_text=True)

        self.assertIn('value="relevance" selected', text)
        self.assertIn("Relevance", text)
        self.assertIn("<strong>Ingredient match:</strong>", text)
        self.assertLess(text.index("Paneer Masala"), text.index("Dal Fry"))
        self.assertLess(text.index("Tomato Rice"), text.index("Dal Fry"))
        self.assertLess(text.index("Dal Fry"), text.index("Vegetable Korma"))

    def test_similar_page_prioritizes_higher_overlap_before_weaker_matches(self):
        self.register_user()
        self.login_user()

        with self.app.app_context():
            db.session.add_all(
                [
                    Recipe(
                        title="Idli",
                        ingredients="rice,urad dal,salt,water",
                        instructions="Soak and steam.",
                        diet_type="veg",
                        difficulty="medium",
                        cooking_time=30,
                    ),
                    Recipe(
                        title="Dosa",
                        ingredients="rice,urad dal,salt,water",
                        instructions="Ferment and roast.",
                        diet_type="veg",
                        difficulty="medium",
                        cooking_time=35,
                    ),
                    Recipe(
                        title="Uttapam",
                        ingredients="rice,onion,urad dal,green chilli,salt,water",
                        instructions="Ferment batter and cook.",
                        diet_type="veg",
                        difficulty="medium",
                        cooking_time=35,
                    ),
                ]
            )
            db.session.commit()

        response = self.client.get("/similar?ingredients=onion,rice,tomato&per_page=10")
        text = response.get_data(as_text=True)

        self.assertLess(text.index("Idli"), text.index("Uttapam"))
        self.assertLess(text.index("Dosa"), text.index("Uttapam"))
        self.assertIn("<strong>Ingredient match:</strong> 2 of 4", text)
        self.assertIn("<strong>Matched:</strong> onion, rice", text)
        self.assertIn("<strong>Missing extras:</strong> green chilli, urad dal", text)

    def test_similar_page_handles_recipes_with_only_basic_ingredients(self):
        self.register_user()
        self.login_user()

        with self.app.app_context():
            Favorite.query.delete()
            Recipe.query.delete()
            db.session.add(
                Recipe(
                    title="Seasoned Water",
                    ingredients="salt,water,oil",
                    instructions="Mix and serve.",
                    diet_type="veg",
                    difficulty="easy",
                    cooking_time=1,
                )
            )
            db.session.commit()

        response = self.client.get("/similar?ingredients=onion,tomato,potato,oil")
        text = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn("No similar recipes found.", text)

    def test_similar_page_supports_filtering_and_alternate_sort(self):
        self.register_user()
        self.login_user()

        response = self.client.get("/similar?ingredients=onion,tomato,potato,oil&diet=non_veg")
        text = response.get_data(as_text=True)
        self.assertIn("Masala Omelette", text)
        self.assertNotIn("Paneer Masala", text)

        response = self.client.get("/similar?ingredients=onion,tomato,potato,oil,paneer&difficulty=easy&sort=time_desc&per_page=10")
        text = response.get_data(as_text=True)
        self.assertIn("Tomato Rice", text)
        self.assertIn("Masala Omelette", text)
        self.assertLess(text.index("Tomato Rice"), text.index("Masala Omelette"))

    def test_similar_title_desc_keeps_relevance_tiebreaker_for_same_title(self):
        matches = [
            {"recipe": Recipe(title="Shared Dish"), "relevance_score": 5, "missing_count": 2},
            {"recipe": Recipe(title="Shared Dish"), "relevance_score": 10, "missing_count": 1},
            {"recipe": Recipe(title="Alpha Dish"), "relevance_score": 100, "missing_count": 1},
        ]

        sort_similar_matches(matches, "title_desc")

        self.assertEqual(
            [(item["recipe"].title, item["relevance_score"]) for item in matches],
            [("Shared Dish", 10), ("Shared Dish", 5), ("Alpha Dish", 100)],
        )

    def test_favorite_requires_post_and_toggles_saved_state(self):
        self.register_user()
        self.login_user()

        get_response = self.client.get("/favorite/1")
        self.assertEqual(get_response.status_code, 405)

        token = self.get_csrf_token("/recommendations?ingredients=onion,tomato,potato")
        self.client.post("/favorite/1", data={"csrf_token": token}, follow_redirects=True)
        token = self.get_csrf_token("/recommendations?ingredients=onion,tomato,potato")
        self.client.post("/favorite/1", data={"csrf_token": token}, follow_redirects=True)

        with self.app.app_context():
            self.assertEqual(Favorite.query.count(), 0)

    def test_recommendations_show_saved_state_for_existing_favorites(self):
        self.register_user()
        self.login_user()

        token = self.get_csrf_token("/recommendations?ingredients=onion,tomato,potato")
        self.client.post("/favorite/1", data={"csrf_token": token}, follow_redirects=True)

        response = self.client.get("/recommendations?ingredients=onion,tomato,potato,oil")
        text = response.get_data(as_text=True)
        self.assertIn(">Remove<", text)

    def test_recommendation_pages_include_back_navigation(self):
        self.register_user()
        self.login_user()

        response = self.client.get("/recommendations?ingredients=onion,tomato,potato,oil")
        text = response.get_data(as_text=True)
        self.assertIn("Back to Dashboard", text)

        response = self.client.get("/similar?ingredients=onion,tomato,potato,oil")
        text = response.get_data(as_text=True)
        self.assertIn("Back to Exact Matches", text)
        self.assertIn("Back to Dashboard", text)

    def test_favorite_redirect_rejects_external_referrer(self):
        self.register_user()
        self.login_user()

        token = self.get_csrf_token("/recommendations?ingredients=onion,tomato,potato")
        response = self.client.post(
            "/favorite/1",
            data={"csrf_token": token},
            headers={"Referer": "https://evil.example/hijack"},
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers.get("Location"), "/favorites")

    def test_favorite_redirect_rejects_network_path_referrer(self):
        self.register_user()
        self.login_user()

        token = self.get_csrf_token("/recommendations?ingredients=onion,tomato,potato")
        response = self.client.post(
            "/favorite/1",
            data={"csrf_token": token},
            headers={"Referer": "http://localhost//evil.example/hijack"},
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers.get("Location"), "/favorites")

    def test_post_only_actions_reject_unknown_query_parameters(self):
        self.register_user()
        self.login_user()

        token = self.get_csrf_token("/recommendations?ingredients=onion,tomato,potato")
        response = self.client.post(
            "/favorite/1?unexpected=1",
            data={"csrf_token": token},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 400)

        token = self.get_csrf_token("/dashboard")
        response = self.client.post(
            "/logout?unexpected=1",
            data={"csrf_token": token},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 400)

    def test_favorites_page_and_remove_action_work(self):
        self.register_user()
        self.login_user()

        token = self.get_csrf_token("/recommendations?ingredients=onion,tomato,potato")
        self.client.post("/favorite/1", data={"csrf_token": token}, follow_redirects=True)
        token = self.get_csrf_token("/similar?ingredients=onion,tomato,potato,oil")
        self.client.post("/favorite/2", data={"csrf_token": token}, follow_redirects=True)

        response = self.client.get("/favorites?page=1")
        text = response.get_data(as_text=True)
        self.assertIn("Your favorite recipes", text)
        self.assertIn("Remove", text)
        self.assertIn("Back to Dashboard", text)

        response = self.client.get("/favorites?page=2&per_page=1")
        page_two_text = response.get_data(as_text=True)
        self.assertIn("Simple Curry", page_two_text)
        self.assertNotIn("Paneer Masala", page_two_text)

        token = self.get_csrf_token("/favorites")
        self.client.post("/favorite/1/remove", data={"csrf_token": token}, follow_redirects=True)

        with self.app.app_context():
            self.assertEqual(Favorite.query.count(), 1)

    def test_logout_requires_post(self):
        self.register_user()
        self.login_user()

        response = self.client.get("/logout")
        self.assertEqual(response.status_code, 405)

        token = self.get_csrf_token("/dashboard")
        response = self.client.post("/logout", data={"csrf_token": token}, follow_redirects=True)
        self.assertIn("Login", response.get_data(as_text=True))

        response = self.client.get("/dashboard", follow_redirects=False)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Welcome to CogniCook", response.data)

    def test_login_rate_limit_blocks_repeated_failures(self):
        self.register_user()

        for _ in range(5):
            response = self.client.post(
                "/login",
                data={
                    "username": "tester_user",
                    "password": "wrong-password",
                    "csrf_token": self.get_csrf_token("/login"),
                },
                follow_redirects=False,
            )
            self.assertEqual(response.status_code, 200)

        response = self.client.post(
            "/login",
            data={
                "username": "tester_user",
                "password": "wrong-password",
                "csrf_token": self.get_csrf_token("/login"),
            },
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 429)
        self.assertIn("Too many login attempts", response.get_data(as_text=True))

    def test_login_account_lockout_blocks_rotating_remote_addresses(self):
        self.register_user()

        for index in range(5):
            response = self.client.post(
                "/login",
                data={
                    "username": "tester_user",
                    "password": "wrong-password",
                    "csrf_token": self.get_csrf_token("/login"),
                },
                environ_overrides={"REMOTE_ADDR": f"10.0.0.{index + 1}"},
                follow_redirects=False,
            )
            self.assertEqual(response.status_code, 200)

        response = self.client.post(
            "/login",
            data={
                "username": "tester_user",
                "password": "SecurePass8",
                "csrf_token": self.get_csrf_token("/login"),
            },
            environ_overrides={"REMOTE_ADDR": "10.0.0.99"},
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 429)
        self.assertIn("Too many login attempts", response.get_data(as_text=True))

    def test_rate_limit_ignores_untrusted_forwarded_for_header(self):
        self.register_user()

        for value in ["1.1.1.1", "2.2.2.2", "3.3.3.3", "4.4.4.4", "5.5.5.5"]:
            response = self.client.post(
                "/login",
                data={
                    "username": "tester_user",
                    "password": "wrong-password",
                    "csrf_token": self.get_csrf_token("/login"),
                },
                headers={"X-Forwarded-For": value},
                follow_redirects=False,
            )
            self.assertEqual(response.status_code, 200)

        response = self.client.post(
            "/login",
            data={
                "username": "tester_user",
                "password": "wrong-password",
                "csrf_token": self.get_csrf_token("/login"),
            },
            headers={"X-Forwarded-For": "6.6.6.6"},
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 429)

    def test_replace_recipe_rows_preserves_matching_favorites(self):
        self.register_user()
        self.login_user()

        token = self.get_csrf_token("/recommendations?ingredients=onion,tomato,potato")
        self.client.post("/favorite/1", data={"csrf_token": token}, follow_redirects=True)

        with self.app.app_context():
            imported = replace_recipe_rows(
                [
                    {
                        "title": "Simple Curry",
                        "ingredients": "onion,tomato,potato,salt,oil",
                        "instructions": "Updated instructions.",
                        "diet_type": "veg",
                        "difficulty": "easy",
                        "cooking_time": 22,
                    },
                    {
                        "title": "New Dish",
                        "ingredients": "lentil,onion,salt,oil",
                        "instructions": "Cook gently.",
                        "diet_type": "veg",
                        "difficulty": "medium",
                        "cooking_time": 30,
                    },
                ]
            )

            self.assertEqual(imported, 2)
            self.assertEqual(Favorite.query.count(), 1)
            favorite = Favorite.query.first()
            recipe = db.session.get(Recipe, favorite.recipe_id)
            self.assertEqual(recipe.title, "Simple Curry")

    def test_sqlite_enforces_foreign_keys_for_favorites(self):
        with self.app.app_context():
            db.session.add(Favorite(user_id=999, recipe_id=999))

            with self.assertRaises(IntegrityError):
                db.session.commit()

            db.session.rollback()

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

    def test_dataset_loader_rejects_traversal_paths(self):
        with self.assertRaisesRegex(ValueError, "Dataset path is invalid"):
            load_dataset_rows("../dataset/recipes.csv")

    def test_query_schema_rejects_unknown_duplicate_and_xss_parameters(self):
        self.register_user()
        self.login_user()

        response = self.client.get("/recommendations?ingredients=onion,tomato,potato&unexpected=1")
        self.assertEqual(response.status_code, 400)

        response = self.client.get("/recommendations?ingredients=onion,tomato,potato&page=1&page=2")
        self.assertEqual(response.status_code, 400)

        response = self.client.get("/recommendations?ingredients=onion,tomato,potato%3Cscript%3E")
        self.assertEqual(response.status_code, 400)

    def test_query_schema_rejects_traversal_in_url_parameters(self):
        self.register_user()
        self.login_user()

        response = self.client.get("/recommendations?ingredients=onion,tomato,..%2Fsecret")
        self.assertEqual(response.status_code, 400)

    def test_security_headers_are_present(self):
        response = self.client.get("/")
        self.assertEqual(response.headers.get("X-Content-Type-Options"), "nosniff")
        self.assertEqual(response.headers.get("X-Frame-Options"), "DENY")
        self.assertEqual(response.headers.get("Referrer-Policy"), "strict-origin-when-cross-origin")
        self.assertEqual(response.headers.get("Cache-Control"), "no-store, no-cache, must-revalidate, max-age=0")
        self.assertEqual(response.headers.get("Pragma"), "no-cache")
        self.assertEqual(response.headers.get("Expires"), "0")
        self.assertEqual(response.headers.get("Cross-Origin-Opener-Policy"), "same-origin")
        self.assertEqual(response.headers.get("Cross-Origin-Resource-Policy"), "same-origin")
        self.assertEqual(response.headers.get("X-Permitted-Cross-Domain-Policies"), "none")
        self.assertEqual(response.headers.get("Permissions-Policy"), "camera=(), microphone=(), geolocation=()")
        self.assertIn("Content-Security-Policy", response.headers)
        self.assertIn("connect-src 'self'", response.headers["Content-Security-Policy"])
        self.assertIn("script-src 'self'", response.headers["Content-Security-Policy"])
        self.assertNotIn("script-src 'self' https://cdn.jsdelivr.net", response.headers["Content-Security-Policy"])
        self.assertNotIn("'unsafe-inline'", response.headers["Content-Security-Policy"])

    def test_hsts_header_is_configurable_for_production_like_environments(self):
        original_enabled = self.app.config.get("SECURITY_HSTS_ENABLED")
        original_max_age = self.app.config.get("SECURITY_HSTS_MAX_AGE")
        self.app.config["SECURITY_HSTS_ENABLED"] = True
        self.app.config["SECURITY_HSTS_MAX_AGE"] = 123
        try:
            response = self.client.get("/")
            self.assertEqual(
                response.headers.get("Strict-Transport-Security"),
                "max-age=123; includeSubDomains",
            )
        finally:
            if original_enabled is None:
                self.app.config.pop("SECURITY_HSTS_ENABLED", None)
            else:
                self.app.config["SECURITY_HSTS_ENABLED"] = original_enabled
            if original_max_age is None:
                self.app.config.pop("SECURITY_HSTS_MAX_AGE", None)
            else:
                self.app.config["SECURITY_HSTS_MAX_AGE"] = original_max_age

    def test_trusted_hosts_reject_unexpected_host_headers(self):
        original_trusted_hosts = self.app.config.get("TRUSTED_HOSTS")
        self.app.config["TRUSTED_HOSTS"] = ["good.test"]
        try:
            response = self.client.get("/", headers={"Host": "evil.test"})
            self.assertEqual(response.status_code, 400)

            response = self.client.get("/", headers={"Host": "good.test"})
            self.assertEqual(response.status_code, 302)
            self.assertEqual(response.headers.get("Location"), "/dashboard")
        finally:
            self.app.config["TRUSTED_HOSTS"] = original_trusted_hosts

    def test_error_pages_return_visitors_to_public_dashboard(self):
        response = self.client.get("/missing-page")
        text = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 404)
        self.assertIn('href="/dashboard"', text)
        self.assertIn("Go to Dashboard", text)

    def test_method_not_allowed_uses_consistent_error_view(self):
        response = self.client.get("/logout")
        text = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 405)
        self.assertIn("Method Not Allowed", text)
        self.assertIn("This action is not available for the requested method.", text)

    def test_request_too_large_uses_consistent_error_view(self):
        original_limit = self.app.config.get("MAX_CONTENT_LENGTH")
        self.app.config["MAX_CONTENT_LENGTH"] = 64
        try:
            response = self.client.post(
                "/dashboard",
                data={"ingredients": "x" * 512, "csrf_token": "token"},
                follow_redirects=False,
            )
            text = response.get_data(as_text=True)

            self.assertEqual(response.status_code, 413)
            self.assertIn("Request Too Large", text)
            self.assertIn("The submitted data is too large.", text)
        finally:
            self.app.config["MAX_CONTENT_LENGTH"] = original_limit

    def test_static_assets_are_cacheable_but_keep_security_headers(self):
        response = self.client.get("/static/js/theme-init.js")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers.get("Cache-Control"), "public, max-age=31536000, immutable")
        self.assertEqual(response.headers.get("X-Content-Type-Options"), "nosniff")
        self.assertNotEqual(response.headers.get("Pragma"), "no-cache")
        response.close()

        response = self.client.get("/static/js/cognicook.js")
        script_text = response.get_data(as_text=True)
        self.assertNotIn("window.location.reload", script_text)
        self.assertNotIn("cognicook-history-reload", script_text)
        response.close()

    def test_search_history_is_not_stored_or_exposed(self):
        self.register_user()
        self.login_user()
        self.client.get("/recommendations?ingredients=onion,tomato,potato")

        response = self.client.get("/activity", follow_redirects=False)
        self.assertEqual(response.status_code, 404)

        dashboard_text = self.client.get("/dashboard").get_data(as_text=True)
        self.assertNotIn(">Activity</a>", dashboard_text)

        with self.app.app_context():
            self.assertFalse(inspect(db.engine).has_table("search_activity"))

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

    def test_instruction_parser_keeps_to_remove_phrase_together(self):
        self.assertEqual(
            split_instruction_block("Soak in 4 cup water for 15 minutes to remove excess starch and drain completely."),
            [
                "Soak in 4 cup water for 15 minutes to remove excess starch.",
                "Drain completely.",
            ],
        )

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

    def test_instruction_parser_splits_dataset_style_text_into_multiple_steps(self):
        with self.app.app_context():
            recipe = Recipe(
                title="Parser Demo",
                ingredients="rice,water,salt",
                instructions=(
                    "wash rice thoroughly add rice and water to a pot and cook on medium flame "
                    "until soft add salt mix well cook for a few more minutes turn off the stove "
                    "allow it to cool slightly and serve warm"
                ),
                diet_type="veg",
                difficulty="easy",
                cooking_time=20,
            )

            steps = recipe.instruction_steps()

        self.assertGreaterEqual(len(steps), 4)
        self.assertEqual(steps[0], "Wash rice thoroughly.")
        self.assertTrue(any(step == "Add rice and water to a pot." for step in steps))
        self.assertTrue(any(step.startswith("Cook on medium flame until soft") for step in steps))
        self.assertTrue(any(step == "Add salt mix well." for step in steps))
        self.assertTrue(any(step == "Turn off the stove." for step in steps))
        self.assertTrue(any(step == "Serve warm." for step in steps))

    def test_root_redirects_visitors_to_dashboard(self):
        response = self.client.get("/", follow_redirects=False)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers.get("Location"), "/dashboard")

    def test_production_configuration_fails_closed(self):
        class ProductionConfig:
            TESTING = True
            IS_PRODUCTION = True
            SECRET_KEY = "x" * 48
            SECRET_KEY_FROM_ENV = True
            REQUIRE_SECRET_KEY_FROM_ENV = True
            SESSION_COOKIE_SECURE = True
            TRUSTED_HOSTS = ["cognicook.example"]
            SQLALCHEMY_DATABASE_URI = "sqlite://"
            SQLALCHEMY_TRACK_MODIFICATIONS = False
            SQLALCHEMY_ENGINE_OPTIONS = {
                "connect_args": {"check_same_thread": False},
                "poolclass": StaticPool,
            }
            AUTO_BOOTSTRAP_DATA = False

        class WeakSecretConfig(ProductionConfig):
            SECRET_KEY = "short"

        class InsecureCookieConfig(ProductionConfig):
            SESSION_COOKIE_SECURE = False

        class MissingHostsConfig(ProductionConfig):
            TRUSTED_HOSTS = None

        class WildcardHostsConfig(ProductionConfig):
            TRUSTED_HOSTS = ["*"]

        with self.assertRaisesRegex(RuntimeError, "at least 32 characters"):
            create_app(WeakSecretConfig)
        with self.assertRaisesRegex(RuntimeError, "SESSION_COOKIE_SECURE"):
            create_app(InsecureCookieConfig)
        with self.assertRaisesRegex(RuntimeError, "explicit production hostnames"):
            create_app(MissingHostsConfig)
        with self.assertRaisesRegex(RuntimeError, "explicit production hostnames"):
            create_app(WildcardHostsConfig)

        production_app = create_app(ProductionConfig)
        try:
            response = production_app.test_client().get("/", headers={"Host": "cognicook.example"})
            self.assertEqual(response.status_code, 302)
            self.assertEqual(response.headers.get("Location"), "/dashboard")
        finally:
            with production_app.app_context():
                db.session.remove()
                db.engine.dispose()


    def test_static_assets_use_versioned_urls_with_immutable_cache_headers(self):
        response = self.client.get("/dashboard")
        body = response.get_data(as_text=True)
        self.assertRegex(body, r'/static/js/theme-init\.js\?v=[0-9a-f]{12}')
        self.assertRegex(body, r'/static/css/cognicook\.css\?v=[0-9a-f]{12}')
        self.assertRegex(body, r'/static/js/cognicook\.js\?v=[0-9a-f]{12}')

    def test_email_uniqueness_is_case_insensitive(self):
        self.register_user(email="case@example.com")
        response = self.register_user(username="different_user", email="CASE@example.com")
        self.assertIn(b"Email address already in use.", response.data)

    def test_malformed_password_hash_is_rejected_without_server_error(self):
        with self.app.app_context():
            db.session.add(
                User(
                    name="legacy_user",
                    email="legacy@example.com",
                    password_hash="invalid-password-hash",
                )
            )
            db.session.commit()

        response = self.login_user(username="legacy_user", password="SecurePass8")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Invalid username or password.", response.data)


if __name__ == "__main__":
    unittest.main()
