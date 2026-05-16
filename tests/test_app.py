import os
from pathlib import Path
import unittest

os.environ["COGNICOOK_SKIP_APP_BOOTSTRAP"] = "1"

from database.seed_recipes import seed_recipes
from sqlalchemy.exc import IntegrityError
from sqlalchemy.pool import StaticPool

from app import create_app
from extensions import db
from models.favorite import Favorite
from models.recipe import Recipe
from models.user import User
from services.data_loader import bootstrap_recipe_data, normalize_instructions, normalize_row, replace_recipe_rows
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
            AUTO_BOOTSTRAP_DATA = False

        cls.app = create_app(TestConfig)

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

    def get_csrf_token(self, path="/"):
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

    def login_user(self, email="tester@example.com", password="SecurePass8"):
        token = self.get_csrf_token("/")
        return self.client.post(
            "/",
            data={"email": email, "password": password, "csrf_token": token},
            follow_redirects=True,
        )

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

        response = self.register_user(username="ab")
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

    def test_register_rejects_mismatched_confirmation_and_duplicate_email(self):
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
        self.assertIn("Email already registered. Please use a different email address.", response.get_data(as_text=True))

    def test_register_and_login_flow_uses_expected_success_message(self):
        response = self.register_user(email="USER@Example.com")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Registration successful. Account created successfully. Please log in.", response.get_data(as_text=True))

        response = self.login_user(email="user@example.com")
        text = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn("Search Recipes", text)
        self.assertNotIn("Recipe Explorer", text)

        with self.app.app_context():
            user = User.query.filter_by(email="user@example.com").first()
            self.assertIsNotNone(user)
            self.assertEqual(user.username, "tester_user")

    def test_login_rotates_csrf_token_after_authentication(self):
        self.register_user()
        original_token = self.get_csrf_token("/")

        response = self.client.post(
            "/",
            data={"email": "tester@example.com", "password": "SecurePass8", "csrf_token": original_token},
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 302)
        with self.client.session_transaction() as session:
            self.assertNotEqual(session["_csrf_token"], original_token)

    def test_dashboard_requires_three_ingredients(self):
        self.register_user()
        self.login_user()
        token = self.get_csrf_token("/dashboard")

        response = self.client.post(
            "/dashboard",
            data={"ingredients": "onion, tomato", "csrf_token": token},
            follow_redirects=True,
        )

        self.assertIn("at least 3 ingredients", response.get_data(as_text=True))

    def test_dashboard_only_shows_ingredient_input_before_search(self):
        self.register_user()
        response = self.login_user()
        text = response.get_data(as_text=True)

        self.assertIn("Welcome back, tester_user", text)
        self.assertIn("Available ingredients", text)
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

    def test_instruction_parser_preserves_single_action_phrases(self):
        self.assertEqual(
            split_instruction_block("Add oil and heat the pan."),
            ["Add oil and heat the pan."],
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
        self.assertEqual(records[0].ingredient, "onion")
        self.assertEqual(records[0].display_measurement, "1 cup")
        self.assertEqual(records[1].ingredient, "tomato")
        self.assertEqual(records[1].display_measurement, "2 medium")

    def test_auth_pages_use_contextual_greetings_without_security_hint(self):
        login_response = self.client.get("/")
        login_text = login_response.get_data(as_text=True)
        self.assertIn("Welcome", login_text)
        self.assertIn('href="/register"', login_text)
        self.assertNotIn("Welcome Back", login_text)
        self.assertNotIn("Repeated failed logins are rate limited automatically", login_text)

        register_response = self.client.get("/register")
        register_text = register_response.get_data(as_text=True)
        self.assertIn("Create your account", register_text)
        self.assertIn('action="/register"', register_text)

    def test_recommendations_page_shows_only_strict_results_and_similar_button(self):
        self.register_user()
        self.login_user()
        token = self.get_csrf_token("/dashboard")

        response = self.client.post(
            "/dashboard",
            data={"ingredients": "onion, tomato, potato", "csrf_token": token},
            follow_redirects=True,
        )

        text = response.get_data(as_text=True)
        self.assertIn("Exact Recipe Matches", text)
        self.assertIn("Simple Curry", text)
        self.assertIn("0 extras needed", text)
        self.assertIn("View Similar Recipes", text)
        self.assertNotIn("Similar Matches", text)

    def test_pagination_marks_current_and_disabled_controls_for_screen_readers(self):
        self.register_user()
        self.login_user()

        response = self.client.get("/similar?ingredients=onion,tomato,potato&per_page=2")
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

    def test_recommendations_page_shows_empty_state_when_no_strict_match_exists(self):
        self.register_user()
        self.login_user()

        response = self.client.get("/recommendations?ingredients=spinach,lentil,beans")
        text = response.get_data(as_text=True)

        self.assertIn("No exact recipes found for these ingredients.", text)
        self.assertIn("View Similar Recipes", text)

    def test_similar_page_limits_results_to_one_to_three_missing_ingredients(self):
        self.register_user()
        self.login_user()

        response = self.client.get("/similar?ingredients=onion,tomato,potato&per_page=10")
        text = response.get_data(as_text=True)

        self.assertIn("Paneer Masala", text)
        self.assertIn("Tomato Rice", text)
        self.assertIn("Dal Fry", text)
        self.assertIn("Vegetable Korma", text)
        self.assertNotIn("No similar recipes found.", text)

    def test_similar_page_default_sort_is_relevance(self):
        self.register_user()
        self.login_user()

        response = self.client.get("/similar?ingredients=onion,tomato,potato&per_page=10")
        text = response.get_data(as_text=True)

        self.assertIn('value="relevance" selected', text)
        self.assertIn("Relevance", text)
        self.assertIn("<strong>Ingredient match:</strong>", text)
        self.assertLess(text.index("Paneer Masala"), text.index("Dal Fry"))
        self.assertLess(text.index("Tomato Rice"), text.index("Dal Fry"))
        self.assertLess(text.index("Vegetable Korma"), text.index("Dal Fry"))

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

        self.assertLess(text.index("Uttapam"), text.index("Idli"))
        self.assertLess(text.index("Uttapam"), text.index("Dosa"))
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

        response = self.client.get("/similar?ingredients=onion,tomato,potato")
        text = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn("No similar recipes found.", text)

    def test_similar_page_supports_filtering_and_alternate_sort(self):
        self.register_user()
        self.login_user()

        response = self.client.get("/similar?ingredients=onion,tomato,potato&diet=non_veg")
        text = response.get_data(as_text=True)
        self.assertIn("Masala Omelette", text)
        self.assertNotIn("Paneer Masala", text)

        response = self.client.get("/similar?ingredients=onion,tomato,potato,paneer&difficulty=easy&sort=time_desc&per_page=10")
        text = response.get_data(as_text=True)
        self.assertIn("Tomato Rice", text)
        self.assertIn("Masala Omelette", text)
        self.assertLess(text.index("Tomato Rice"), text.index("Masala Omelette"))

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

        response = self.client.get("/recommendations?ingredients=onion,tomato,potato")
        text = response.get_data(as_text=True)
        self.assertIn(">Remove<", text)

    def test_recommendation_pages_include_back_navigation(self):
        self.register_user()
        self.login_user()

        response = self.client.get("/recommendations?ingredients=onion,tomato,potato")
        text = response.get_data(as_text=True)
        self.assertIn("Back to Dashboard", text)

        response = self.client.get("/similar?ingredients=onion,tomato,potato")
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

    def test_favorites_page_and_remove_action_work(self):
        self.register_user()
        self.login_user()

        token = self.get_csrf_token("/recommendations?ingredients=onion,tomato,potato")
        self.client.post("/favorite/1", data={"csrf_token": token}, follow_redirects=True)
        token = self.get_csrf_token("/similar?ingredients=onion,tomato,potato")
        self.client.post("/favorite/2", data={"csrf_token": token}, follow_redirects=True)

        response = self.client.get("/favorites?page=1")
        text = response.get_data(as_text=True)
        self.assertIn("Your favorite recipes", text)
        self.assertIn("Remove", text)
        self.assertIn("Back to Dashboard", text)

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
        self.assertEqual(response.status_code, 302)
        self.assertIn("/", response.headers.get("Location"))

    def test_login_rate_limit_blocks_repeated_failures(self):
        self.register_user()

        for _ in range(5):
            response = self.client.post(
                "/",
                data={
                    "email": "tester@example.com",
                    "password": "wrong-password",
                    "csrf_token": self.get_csrf_token("/"),
                },
                follow_redirects=False,
            )
            self.assertEqual(response.status_code, 200)

        response = self.client.post(
            "/",
            data={
                "email": "tester@example.com",
                "password": "wrong-password",
                "csrf_token": self.get_csrf_token("/"),
            },
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 429)
        self.assertIn("Too many login attempts", response.get_data(as_text=True))

    def test_rate_limit_ignores_untrusted_forwarded_for_header(self):
        self.register_user()

        for value in ["1.1.1.1", "2.2.2.2", "3.3.3.3", "4.4.4.4", "5.5.5.5"]:
            response = self.client.post(
                "/",
                data={
                    "email": "tester@example.com",
                    "password": "wrong-password",
                    "csrf_token": self.get_csrf_token("/"),
                },
                headers={"X-Forwarded-For": value},
                follow_redirects=False,
            )
            self.assertEqual(response.status_code, 200)

        response = self.client.post(
            "/",
            data={
                "email": "tester@example.com",
                "password": "wrong-password",
                "csrf_token": self.get_csrf_token("/"),
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
        self.assertEqual(response.headers.get("Permissions-Policy"), "camera=(), microphone=(), geolocation=()")
        self.assertIn("Content-Security-Policy", response.headers)
        self.assertIn("connect-src 'self'", response.headers["Content-Security-Policy"])
        self.assertNotIn("'unsafe-inline'", response.headers["Content-Security-Policy"])

    def test_demo_seed_script_requires_explicit_confirmation(self):
        with self.assertRaisesRegex(RuntimeError, "COGNICOOK_ALLOW_DEMO_SEED=1"):
            seed_recipes()

    def test_recipe_detail_requires_authentication(self):
        response = self.client.get("/recipe/1", follow_redirects=False)
        self.assertEqual(response.status_code, 302)

    def test_tampered_user_session_does_not_raise_server_error(self):
        with self.client.session_transaction() as session:
            session["_user_id"] = "not-an-integer"

        response = self.client.get("/dashboard", follow_redirects=False)
        self.assertEqual(response.status_code, 302)

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

    def test_root_redirects_authenticated_users_to_dashboard(self):
        self.register_user()
        self.login_user()

        response = self.client.get("/", follow_redirects=False)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers.get("Location"), "/dashboard")


if __name__ == "__main__":
    unittest.main()
