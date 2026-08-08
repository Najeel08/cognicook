from tests.base import (
    CogniCookTestCase,
    BASE_DIR,
    Recipe,
)


class TestDashboard(CogniCookTestCase):
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
        self.create_user()
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

    def test_dashboard_does_not_count_basic_staples_toward_minimum(self):
        self.register_user()
        self.login_user()
        token = self.get_csrf_token("/dashboard")

        response = self.client.post(
            "/dashboard",
            data={"ingredients": "onion, tomato, salt, water, sugar", "csrf_token": token},
            follow_redirects=True,
        )

        text = response.get_data(as_text=True)
        self.assertIn("besides salt, sugar, or water", text)
        self.assertIn("Available ingredients", text)

    def test_recipe_discovery_is_available_before_login_but_save_requires_login(self):
        response = self.client.get("/recommendations?ingredients=onion,tomato,potato,oil")
        text = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn("Simple Curry", text)
        self.assertIn("Log in to Save", text)
        self.assertNotIn(">Save</button>", text)

    def test_root_redirects_visitors_to_dashboard(self):
        response = self.client.get("/", follow_redirects=False)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers.get("Location"), "/dashboard")

    def test_primary_button_keeps_original_orange_gradient_with_white_text(self):
        stylesheet = (BASE_DIR / "static" / "css" / "cognicook.css").read_text(encoding="utf-8")

        self.assertIn(
            "--primary-gradient: linear-gradient(135deg, #ff8a24 0%, #f97316 50%, #dc5c12 100%);",
            stylesheet,
        )
        self.assertIn("--primary-text: #ffffff;", stylesheet)

