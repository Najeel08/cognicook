from tests.base import (
    CogniCookTestCase,
    IntegrityError,
    db,
    Favorite,
    Recipe,
    replace_recipe_rows,
)


class TestFavorites(CogniCookTestCase):
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

    def test_favorite_actions_are_scoped_to_current_user(self):
        owner_id = self.create_user(username="owner_user", email="owner@example.com")
        self.login_user(username="owner_user")

        token = self.get_csrf_token("/recommendations?ingredients=onion,tomato,potato")
        self.client.post("/favorite/1", data={"csrf_token": token}, follow_redirects=True)
        self.logout_user()

        other_id = self.create_user(username="other_user", email="other@example.com")
        self.login_user(username="other_user")

        response = self.client.get("/favorites")
        self.assertNotIn("Simple Curry", response.get_data(as_text=True))

        token = self.get_csrf_token("/favorites")
        response = self.client.post("/favorite/1/remove", data={"csrf_token": token}, follow_redirects=True)
        self.assertIn("Favorite recipe not found.", response.get_data(as_text=True))

        with self.app.app_context():
            self.assertEqual(Favorite.query.filter_by(user_id=owner_id, recipe_id=1).count(), 1)
            self.assertEqual(Favorite.query.filter_by(user_id=other_id, recipe_id=1).count(), 0)

        token = self.get_csrf_token("/recommendations?ingredients=onion,tomato,potato")
        self.client.post("/favorite/1", data={"csrf_token": token}, follow_redirects=True)

        with self.app.app_context():
            self.assertEqual(Favorite.query.filter_by(user_id=owner_id, recipe_id=1).count(), 1)
            self.assertEqual(Favorite.query.filter_by(user_id=other_id, recipe_id=1).count(), 1)

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

