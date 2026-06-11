from sqlalchemy import event

from extensions import db
from utils.ingredient_cleaner import normalize_ingredient_text, clean_ingredients
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
    cleaned_ingredients = db.Column(db.Text, nullable=False, default="")
    instructions = db.Column(db.Text, nullable=False)
    diet_type = db.Column(db.String(50))
    difficulty = db.Column(db.String(50))
    cooking_time = db.Column(db.Integer)
    ingredient_measurements = db.Column(db.Text)

    def ingredient_list(self):
        return clean_ingredients(self.cleaned_ingredients or self.ingredients)

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


@event.listens_for(Recipe, "before_insert")
@event.listens_for(Recipe, "before_update")
def sync_cleaned_ingredients(_mapper, _connection, recipe):
    recipe.cleaned_ingredients = normalize_ingredient_text(recipe.ingredients)
