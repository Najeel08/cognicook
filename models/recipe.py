from extensions import db
from utils.ingredient_cleaner import normalize_ingredient_text, normalize_ingredient_tokens
from utils.instructions import split_instruction_block


class Recipe(db.Model):
    __table_args__ = (
        db.Index("ix_recipe_title", "title"),
        db.Index("ix_recipe_diet_type", "diet_type"),
        db.Index("ix_recipe_difficulty", "difficulty"),
        db.Index("ix_recipe_cuisine", "cuisine"),
        db.Index("ix_recipe_state", "state"),
    )

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    ingredients = db.Column(db.Text, nullable=False)
    instructions = db.Column(db.Text, nullable=False)
    cuisine = db.Column(db.String(100))
    state = db.Column(db.String(100))
    diet_type = db.Column(db.String(50))
    difficulty = db.Column(db.String(50))
    cooking_time = db.Column(db.Integer)
    servings = db.Column(db.Integer)

    def ingredient_list(self):
        return normalize_ingredient_tokens(self.ingredients)

    @property
    def cleaned_ingredients(self):
        return normalize_ingredient_text(self.ingredients)

    def instruction_steps(self):
        return split_instruction_block(self.instructions)
