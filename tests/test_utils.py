from tests.base import (
    CogniCookTestCase,
    Recipe,
    clean_ingredients,
    parse_ingredient_measurements,
    split_instruction_block,
    paginate_list,
)


class TestUtils(CogniCookTestCase):
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

    def test_ingredient_measurement_parser_accepts_future_dataset_shapes(self):
        records = parse_ingredient_measurements(
            '[{"ingredient":"Onion","quantity":"1","unit":"cup"},{"ingredient":"Tomato","measurement":"2 medium"}]',
            known_ingredients="onion,tomato,salt",
        )

        self.assertEqual(records[0].ingredient, "onion")
        self.assertEqual(records[0].display_measurement, "1 cup")
        self.assertEqual(records[1].ingredient, "tomato")
        self.assertEqual(records[1].display_measurement, "2 medium")

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

    def test_instruction_parser_keeps_to_remove_phrase_together(self):
        self.assertEqual(
            split_instruction_block("Soak in 4 cup water for 15 minutes to remove excess starch and drain completely."),
            [
                "Soak in 4 cup water for 15 minutes to remove excess starch.",
                "Drain completely.",
            ],
        )

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

