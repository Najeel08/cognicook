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
    favorites = db.relationship("Favorite", back_populates="recipe", cascade="all, delete-orphan")

    def ingredient_list(self):
        cache_key = (self.cleaned_ingredients or "", self.ingredients or "")
        if getattr(self, "_ingredient_list_cache_key", None) == cache_key:
            return list(self._ingredient_list_cache)

        if self.cleaned_ingredients:
            ingredients = [
                ingredient.strip().lower()
                for ingredient in self.cleaned_ingredients.split(",")
                if ingredient.strip()
            ]
            parsed = list(dict.fromkeys(ingredients))
        else:
            parsed = clean_ingredients(self.ingredients)

        self._ingredient_list_cache_key = cache_key
        self._ingredient_list_cache = tuple(parsed)
        return list(parsed)

    def instruction_steps(self):
        cache_key = self.instructions or ""
        if getattr(self, "_instruction_steps_cache_key", None) == cache_key:
            return list(self._instruction_steps_cache)

        parsed = split_instruction_block(self.instructions)
        self._instruction_steps_cache_key = cache_key
        self._instruction_steps_cache = tuple(parsed)
        return list(parsed)

    def ingredient_measurement_list(self):
        cache_key = (self.ingredient_measurements or "", self.ingredients or "")
        if getattr(self, "_ingredient_measurement_list_cache_key", None) == cache_key:
            return list(self._ingredient_measurement_list_cache)

        parsed = parse_ingredient_measurements(
            self.ingredient_measurements,
            known_ingredients=self.ingredients,
        )
        self._ingredient_measurement_list_cache_key = cache_key
        self._ingredient_measurement_list_cache = tuple(parsed)
        return list(parsed)

    @property
    def has_ingredient_measurements(self):
        return bool(self.ingredient_measurement_list())


@event.listens_for(Recipe, "before_insert")
@event.listens_for(Recipe, "before_update")
def sync_cleaned_ingredients(_mapper, _connection, recipe):
    recipe.cleaned_ingredients = normalize_ingredient_text(recipe.ingredients)
    for attribute in (
        "_ingredient_list_cache_key",
        "_ingredient_list_cache",
        "_instruction_steps_cache_key",
        "_instruction_steps_cache",
        "_ingredient_measurement_list_cache_key",
        "_ingredient_measurement_list_cache",
    ):
        recipe.__dict__.pop(attribute, None)
