from extensions import db
from utils.ingredient_cleaner import normalize_ingredient_text, normalize_ingredient_tokens
from utils.ingredient_measurements import parse_ingredient_measurements
from utils.instructions import split_instruction_block


class Recipe(db.Model):
    __table_args__ = (
        db.Index("ix_recipe_title", "title"),
        db.Index("ix_recipe_diet_type", "diet_type"),
        db.Index("ix_recipe_difficulty", "difficulty"),
    )

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    ingredients = db.Column(db.Text, nullable=False)
    instructions = db.Column(db.Text, nullable=False)
    diet_type = db.Column(db.String(50))
    difficulty = db.Column(db.String(50))
    cooking_time = db.Column(db.Integer)
    ingredient_measurements = db.Column(db.Text)

    def ingredient_list(self):
        return normalize_ingredient_tokens(self.ingredients)

    @property
    def cleaned_ingredients(self):
        return normalize_ingredient_text(self.ingredients)

    def instruction_steps(self):
        return split_instruction_block(self.instructions)

    def ingredient_measurement_list(self):
        return parse_ingredient_measurements(
            self.ingredient_measurements,
            known_ingredients=self.ingredients,
        )

    @property
    def has_ingredient_measurements(self):
        return bool(self.ingredient_measurement_list())
