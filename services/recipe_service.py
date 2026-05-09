from sqlalchemy import event
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from models.recipe import Recipe
from utils.ingredient_cleaner import clean_ingredients, normalize_search_text
from utils.pagination import paginate_list

BASIC_INGREDIENTS = {"salt", "oil", "water", "sugar"}
DIET_OPTIONS = ("veg", "non_veg")
DIFFICULTY_OPTIONS = ("easy", "medium", "hard")
SIMILAR_SORT_OPTIONS = ("relevance", "title_asc", "title_desc", "time_asc", "time_desc")
MIN_SIMILAR_MATCH_COUNT = 2
MIN_SIMILAR_MATCH_RATIO = 0.5

_similarity_cache = {
    "recipe_ids": (),
    "recipe_positions": {},
    "vectorizer": None,
    "matrix": None,
}


def invalidate_recipe_similarity_cache(*_args, **_kwargs):
    _similarity_cache["recipe_ids"] = ()
    _similarity_cache["recipe_positions"] = {}
    _similarity_cache["vectorizer"] = None
    _similarity_cache["matrix"] = None


@event.listens_for(Recipe, "after_insert")
@event.listens_for(Recipe, "after_update")
@event.listens_for(Recipe, "after_delete")
def _clear_recipe_similarity_cache(*_args, **_kwargs):
    invalidate_recipe_similarity_cache()


def get_filter_options():
    return {
        "diets": DIET_OPTIONS,
        "difficulties": DIFFICULTY_OPTIONS,
        "sorts": SIMILAR_SORT_OPTIONS,
    }


def parse_ingredient_query(text):
    cleaned = clean_ingredients(text)
    return cleaned, ", ".join(cleaned)


def required_recipe_ingredients(recipe):
    return set(recipe.ingredient_list()) - BASIC_INGREDIENTS


def recipe_query_text(recipe):
    required_ingredients = sorted(required_recipe_ingredients(recipe))
    return normalize_search_text(" ".join(required_ingredients)).lower()


def build_similarity_index():
    recipes = Recipe.query.order_by(Recipe.id.asc()).all()
    recipe_ids = tuple(recipe.id for recipe in recipes)
    if _similarity_cache["recipe_ids"] == recipe_ids:
        return _similarity_cache

    if not recipes:
        invalidate_recipe_similarity_cache()
        return _similarity_cache

    recipe_texts = [recipe_query_text(recipe) for recipe in recipes]
    if not any(recipe_texts):
        invalidate_recipe_similarity_cache()
        _similarity_cache["recipe_ids"] = recipe_ids
        _similarity_cache["recipe_positions"] = {recipe.id: index for index, recipe in enumerate(recipes)}
        return _similarity_cache

    vectorizer = TfidfVectorizer(ngram_range=(1, 2))
    matrix = vectorizer.fit_transform(recipe_texts)

    _similarity_cache["recipe_ids"] = recipe_ids
    _similarity_cache["recipe_positions"] = {recipe.id: index for index, recipe in enumerate(recipes)}
    _similarity_cache["vectorizer"] = vectorizer
    _similarity_cache["matrix"] = matrix
    return _similarity_cache


def score_recipes_by_similarity(user_ingredients):
    similarity_index = build_similarity_index()
    vectorizer = similarity_index["vectorizer"]
    matrix = similarity_index["matrix"]
    if vectorizer is None or matrix is None:
        return {}

    query_ingredients = [ingredient for ingredient in user_ingredients if ingredient not in BASIC_INGREDIENTS] or user_ingredients
    query_text = normalize_search_text(" ".join(query_ingredients)).lower()
    query_vector = vectorizer.transform([query_text])
    all_scores = cosine_similarity(query_vector, matrix).flatten()
    return {
        recipe_id: all_scores[position]
        for recipe_id, position in similarity_index["recipe_positions"].items()
    }


def apply_similar_filters(filters):
    query = Recipe.query.order_by(Recipe.id.asc())

    if filters["diet"]:
        query = query.filter(Recipe.diet_type == filters["diet"])

    if filters["difficulty"]:
        query = query.filter(Recipe.difficulty == filters["difficulty"])

    return query


def sort_strict_matches(matches):
    matches.sort(key=lambda recipe: recipe.id)


def sort_similar_matches(matches, sort_key):
    if sort_key == "title_asc":
        matches.sort(key=lambda item: (item["recipe"].title.lower(), -item["relevance_score"], item["missing_count"]))
        return

    if sort_key == "title_desc":
        matches.sort(key=lambda item: (-item["relevance_score"], item["missing_count"]))
        matches.sort(key=lambda item: item["recipe"].title.lower(), reverse=True)
        return

    if sort_key == "time_asc":
        matches.sort(
            key=lambda item: (
                item["recipe"].cooking_time or 0,
                -item["relevance_score"],
                item["missing_count"],
                item["recipe"].title.lower(),
            )
        )
        return

    if sort_key == "time_desc":
        matches.sort(
            key=lambda item: (
                -(item["recipe"].cooking_time or 0),
                -item["relevance_score"],
                item["missing_count"],
                item["recipe"].title.lower(),
            )
        )
        return

    matches.sort(
        key=lambda item: (
            -item["relevance_score"],
            -item["match_count"],
            -item["match_ratio"],
            item["missing_count"],
            -item["score"],
            item["recipe"].title.lower(),
        )
    )


def relevance_percent(match_ratio, similarity_score, missing_count, max_missing):
    missing_penalty = (missing_count / max_missing) * 0.15 if max_missing else 0
    weighted_score = (match_ratio * 0.7) + (similarity_score * 0.3) - missing_penalty
    return round(max(0, min(1, weighted_score)) * 100)


def get_strict_recommendations(ingredients_text, page, per_page):
    user_ingredients, normalized_input = parse_ingredient_query(ingredients_text)
    user_ingredient_set = set(user_ingredients) - BASIC_INGREDIENTS
    matches = []
    seen_recipes = set()

    if user_ingredients:
        for recipe in Recipe.query.order_by(Recipe.id.asc()).all():
            recipe_key = (recipe.title.lower(), ",".join(recipe.ingredient_list()))
            if recipe_key in seen_recipes:
                continue

            if required_recipe_ingredients(recipe).issubset(user_ingredient_set):
                matches.append(recipe)
                seen_recipes.add(recipe_key)

    sort_strict_matches(matches)
    return {
        "ingredients": user_ingredients,
        "ingredients_text": normalized_input,
        "strict": paginate_list(matches, page, per_page),
    }


def get_similar_recommendations(ingredients_text, filters, page, per_page, max_missing=3):
    user_ingredients, normalized_input = parse_ingredient_query(ingredients_text)
    user_ingredient_set = set(user_ingredients) - BASIC_INGREDIENTS

    if not user_ingredients:
        return {
            "ingredients": [],
            "ingredients_text": normalized_input,
            "similar": paginate_list([], page, per_page),
        }

    recipes = apply_similar_filters(filters).all()
    similarity_scores = score_recipes_by_similarity(user_ingredients)
    candidates = []
    seen_recipes = set()

    for recipe in recipes:
        recipe_key = (recipe.title.lower(), ",".join(recipe.ingredient_list()))
        if recipe_key in seen_recipes:
            continue

        recipe_ingredients = required_recipe_ingredients(recipe)
        if recipe_ingredients.issubset(user_ingredient_set):
            continue

        missing = sorted(recipe_ingredients - user_ingredient_set)
        matched = sorted(recipe_ingredients & user_ingredient_set)

        if not matched:
            continue
        if not 1 <= len(missing) <= max_missing:
            continue

        required_count = len(recipe_ingredients)
        match_count = len(matched)
        match_ratio = match_count / required_count if required_count else 0.0
        missing_count = len(missing)
        similarity_score = similarity_scores.get(recipe.id, 0.0)
        is_strong_match = match_count >= MIN_SIMILAR_MATCH_COUNT or match_ratio >= MIN_SIMILAR_MATCH_RATIO
        is_fallback_match = match_count >= 1 and missing_count <= 2
        if not is_strong_match and not is_fallback_match:
            continue

        relevance_score = round(
            (match_count * 100)
            + (match_ratio * 100)
            + (similarity_score * 100)
            - (missing_count * 25),
            6,
        )

        candidates.append(
            {
                "recipe": recipe,
                "missing": missing,
                "matched": matched,
                "score": similarity_score,
                "match_count": match_count,
                "match_ratio": match_ratio,
                "missing_count": missing_count,
                "required_count": required_count,
                "relevance_score": relevance_score,
                "relevance_percent": relevance_percent(match_ratio, similarity_score, missing_count, max_missing),
                "is_fallback_match": not is_strong_match,
            }
        )
        seen_recipes.add(recipe_key)

    strong_matches = [item for item in candidates if not item["is_fallback_match"]]
    matches = strong_matches or candidates
    sort_similar_matches(matches, filters["sort"])
    return {
        "ingredients": user_ingredients,
        "ingredients_text": normalized_input,
        "similar": paginate_list(matches, page, per_page),
    }
