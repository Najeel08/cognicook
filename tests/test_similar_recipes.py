from tests.base import (
    CogniCookTestCase,
    BASE_DIR,
    db,
    Favorite,
    Recipe,
    load_dataset_rows,
    replace_recipe_rows,
    get_similar_recommendations,
    parse_ingredient_query,
    sort_similar_matches,
)


class TestSimilarRecipes(CogniCookTestCase):
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

