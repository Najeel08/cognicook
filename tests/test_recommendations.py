from tests.base import (
    CogniCookTestCase,
    StaticPool,
    create_app,
    db,
    Recipe,
    get_ingredient_vocabulary,
    get_strict_recommendations,
    parse_ingredient_query,
)


class TestRecommendations(CogniCookTestCase):
    def test_recommendations_does_not_count_basic_staples_toward_minimum(self):
        self.register_user()
        self.login_user()

        response = self.client.get(
            "/recommendations?ingredients=onion,tomato,salt,water,sugar",
            follow_redirects=True,
        )

        text = response.get_data(as_text=True)
        self.assertIn("besides salt, sugar, or water", text)
        self.assertIn("Available ingredients", text)

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

    def test_recommendation_cache_is_reset_for_fresh_app_database(self):
        with self.app.app_context():
            db.session.add(
                Recipe(
                    title="Rare Pepper Demo",
                    ingredients="rarepepper,salt,oil",
                    instructions="Cook rare pepper.",
                    diet_type="veg",
                    difficulty="easy",
                    cooking_time=12,
                )
            )
            db.session.commit()
            self.assertIn("rarepepper", get_ingredient_vocabulary()[0])

        class EmptyConfig:
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
            TRUSTED_HOSTS = None

        isolated_app = create_app(EmptyConfig)
        try:
            with isolated_app.app_context():
                self.assertEqual(Recipe.query.count(), 0)
                self.assertNotIn("rarepepper", get_ingredient_vocabulary()[0])
        finally:
            with isolated_app.app_context():
                db.session.remove()
                db.engine.dispose()

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

    def test_spice_and_ingredient_variant_matching(self):
        with self.app.app_context():
            db.session.add_all(
                [
                    Recipe(
                        title="Cardamom Drink",
                        ingredients="milk,sugar,cardamom powder",
                        instructions="Mix milk, sugar, and cardamom powder.",
                        diet_type="veg",
                        difficulty="easy",
                        cooking_time=5,
                    ),
                    Recipe(
                        title="Turmeric Veg Curry",
                        ingredients="potato,onion,turmeric powder,oil,salt",
                        instructions="Cook potato and onion with turmeric powder and oil.",
                        diet_type="veg",
                        difficulty="easy",
                        cooking_time=15,
                    ),
                ]
            )
            db.session.commit()

            # Test whole cardamom matches cardamom powder
            res_cardamom = get_strict_recommendations("milk, sugar, cardamom", page=1, per_page=10)
            titles_cardamom = [r.title for r in res_cardamom["strict"].items]
            self.assertIn("Cardamom Drink", titles_cardamom)

            # Test turmeric matches turmeric powder
            res_turmeric = get_strict_recommendations("potato, onion, turmeric, oil", page=1, per_page=10)
            titles_turmeric = [r.title for r in res_turmeric["strict"].items]
            self.assertIn("Turmeric Veg Curry", titles_turmeric)


