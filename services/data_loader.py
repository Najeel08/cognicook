import csv
from pathlib import Path

from extensions import db
from models.favorite import Favorite
from models.recipe import Recipe
from services.recipe_service import invalidate_recipe_similarity_cache
from utils.ingredient_cleaner import normalize_ingredient_text, normalize_search_text
from utils.ingredient_measurements import serialize_ingredient_measurements
from utils.validators import contains_path_traversal

REQUIRED_COLUMNS = {
    "title",
    "ingredients",
    "instructions",
    "diet_type",
    "difficulty",
    "cooking_time",
}


def validate_dataset_path(dataset_path):
    raw_path = str(dataset_path or "")
    if not raw_path or contains_path_traversal(raw_path):
        raise ValueError("Dataset path is invalid")

    path = Path(raw_path)
    if path.suffix.lower() != ".csv":
        raise ValueError("Dataset path must point to a CSV file")

    return path


def normalize_category(value):
    return normalize_search_text(value).lower()


def parse_int(value, default=0):
    try:
        parsed = int(str(value).strip())
    except (TypeError, ValueError):
        return default
    return max(parsed, default)


def normalize_instructions(value):
    raw = str(value or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    lines = [" ".join(line.split()).strip() for line in raw.split("\n") if line.strip()]
    if not lines:
        return ""

    normalized_lines = []
    for line in lines:
        normalized = line.rstrip(". ")
        if normalized and normalized[-1] not in "!?":
            normalized = f"{normalized}."
        normalized_lines.append(normalized)

    return " ".join(normalized_lines)


def normalize_row(row):
    title = normalize_search_text(row.get("title", ""))
    ingredients = normalize_ingredient_text(row.get("ingredients", ""))
    instructions = normalize_instructions(row.get("instructions", ""))
    measurement_source = (
        row.get("ingredient_measurements")
        or row.get("measurements")
        or row.get("ingredient_measurement")
        or ""
    )

    if not title or not ingredients or not instructions:
        return None

    return {
        "title": title,
        "ingredients": ingredients,
        "instructions": instructions,
        # Accept known measurement column names while keeping the current CSV schema optional.
        "ingredient_measurements": serialize_ingredient_measurements(
            measurement_source,
            known_ingredients=ingredients,
        ),
        "diet_type": normalize_category(row.get("diet_type", "")),
        "difficulty": normalize_category(row.get("difficulty", "")),
        "cooking_time": parse_int(row.get("cooking_time", 0)),
    }


def recipe_identity(row):
    return row["title"].lower(), row["ingredients"]


def recipe_fingerprint_from_row(row):
    return (
        row["title"].lower(),
        row["ingredients"],
        row["instructions"],
        row.get("ingredient_measurements") or "",
        row["diet_type"],
        row["difficulty"],
        row["cooking_time"],
    )


def recipe_fingerprint_from_model(recipe):
    return (
        recipe.title.lower(),
        recipe.ingredients,
        recipe.instructions,
        recipe.ingredient_measurements or "",
        recipe.diet_type or "",
        recipe.difficulty or "",
        recipe.cooking_time or 0,
    )


def load_dataset_rows(dataset_path):
    path = validate_dataset_path(dataset_path)
    if not path.exists():
        raise FileNotFoundError(f"Dataset not found: {path}")

    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames or not REQUIRED_COLUMNS.issubset(set(reader.fieldnames)):
            raise ValueError("Dataset is missing one or more required columns")

        normalized_rows = []
        seen_keys = set()

        for row in reader:
            normalized = normalize_row(row)
            if normalized is None:
                continue

            unique_key = recipe_identity(normalized)
            if unique_key in seen_keys:
                continue

            seen_keys.add(unique_key)
            normalized_rows.append(normalized)

    return normalized_rows


def replace_recipe_rows(rows, preserve_favorites=True):
    if not rows:
        raise ValueError("Dataset did not produce any valid recipe rows")

    favorite_links = []
    if preserve_favorites:
        existing_recipes = {
            recipe.id: recipe_identity({"title": recipe.title, "ingredients": recipe.ingredients})
            for recipe in db.session.query(Recipe.id, Recipe.title, Recipe.ingredients).all()
        }
        favorite_links = [
            (favorite.user_id, existing_recipes.get(favorite.recipe_id))
            for favorite in db.session.query(Favorite.user_id, Favorite.recipe_id).all()
        ]

    recipes = [Recipe(**row) for row in rows]

    try:
        Favorite.query.delete()
        Recipe.query.delete()
        db.session.flush()
        db.session.add_all(recipes)
        db.session.flush()

        if preserve_favorites:
            replacement_ids = {
                recipe_identity({"title": recipe.title, "ingredients": recipe.ingredients}): recipe.id
                for recipe in recipes
            }
            restored_favorites = [
                Favorite(user_id=user_id, recipe_id=replacement_ids[identity])
                for user_id, identity in favorite_links
                if identity in replacement_ids
            ]
            if restored_favorites:
                db.session.add_all(restored_favorites)
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise

    invalidate_recipe_similarity_cache()
    return len(recipes)


def replace_recipe_data(dataset_path, preserve_favorites=True):
    rows = load_dataset_rows(dataset_path)
    return replace_recipe_rows(rows, preserve_favorites=preserve_favorites)


def bootstrap_recipe_data(dataset_path):
    rows = load_dataset_rows(dataset_path)
    existing_rows = Recipe.query.order_by(Recipe.id.asc()).all()
    if not existing_rows:
        return replace_recipe_rows(rows, preserve_favorites=True)

    existing_fingerprints = {recipe_fingerprint_from_model(recipe) for recipe in existing_rows}
    dataset_fingerprints = {recipe_fingerprint_from_row(row) for row in rows}
    if len(existing_rows) == len(rows) and existing_fingerprints == dataset_fingerprints:
        return 0

    return replace_recipe_rows(rows, preserve_favorites=True)
