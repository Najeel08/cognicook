import re
import threading
from difflib import get_close_matches

from sqlalchemy import event
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from models.recipe import Recipe
from utils.ingredient_cleaner import clean_ingredients, normalize_search_text
from utils.pagination import paginate_list

BASIC_INGREDIENTS = {"salt", "water", "sugar"}
DIET_OPTIONS = ("veg", "non_veg")
DIFFICULTY_OPTIONS = ("easy", "medium", "hard")
SIMILAR_SORT_OPTIONS = ("relevance", "title_asc", "title_desc", "time_asc", "time_desc")
MIN_SIMILAR_MATCH_COUNT = 2
MIN_SIMILAR_MATCH_RATIO = 0.5
INGREDIENT_MATCH_ALIASES = {
    "salted cod": {"cod"},
    "seer fish": {"fish"},
    "anchovy": {"fish"},
    "black pepper": {"pepper"},
    "cardamom powder": {"cardamom"},
    "chocolate chips": {"chocolate"},
    "chocolate syrup": {"chocolate"},
    "cocoa powder": {"cocoa"},
    "coriander leaves": {"coriander"},
    "coriander powder": {"coriander"},
    "garlic powder": {"garlic"},
    "lemon juice": {"lemon"},
    "mint leaves": {"mint"},
    "turmeric powder": {"turmeric"},
    "vanilla essence": {"vanilla"},
}

GENERIC_HEAD_ALIASES = {
    "olives": {"olive", "olives"},
}

_similarity_cache = {
    "vocab_built": False,
    "index_built": False,
    "recipe_ids": (),
    "recipe_positions": {},
    "vectorizer": None,
    "matrix": None,
    "ingredient_vocabulary": frozenset(),
    "max_ingredient_words": 1,
}
_similarity_cache_lock = threading.RLock()

WORD_PATTERN = re.compile(r"[a-z]+")
TITLE_STOPWORDS = {"recipe", "dish"}
TITLE_MATCH_THRESHOLD = 0.75


def invalidate_recipe_similarity_cache(*_args, **_kwargs):
    with _similarity_cache_lock:
        _similarity_cache["vocab_built"] = False
        _similarity_cache["index_built"] = False
        _similarity_cache["recipe_ids"] = ()
        _similarity_cache["recipe_positions"] = {}
        _similarity_cache["vectorizer"] = None
        _similarity_cache["matrix"] = None
        _similarity_cache["ingredient_vocabulary"] = frozenset()
        _similarity_cache["max_ingredient_words"] = 1


@event.listens_for(Recipe, "after_insert")
@event.listens_for(Recipe, "after_update")
@event.listens_for(Recipe, "after_delete")
def _clear_recipe_similarity_cache(*_args, **_kwargs):
    invalidate_recipe_similarity_cache()


def get_filter_options():
    return {
        "diets": DIET_OPTIONS,
        "difficulties": DIFFICULTY_OPTIONS,
    }


def normalize_query_words(value):
    text = str(value or "").lower().replace("&", " and ")
    return WORD_PATTERN.findall(text)


def get_ingredient_vocabulary():
    with _similarity_cache_lock:
        if _similarity_cache["vocab_built"]:
            return _similarity_cache["ingredient_vocabulary"], _similarity_cache["max_ingredient_words"]

        recipes = Recipe.query.order_by(Recipe.id.asc()).all()
        vocabulary = {
            ingredient
            for recipe in recipes
            for ingredient in recipe.ingredient_list()
            if ingredient
        }
        vocabulary.update(
            alias
            for ingredient in tuple(vocabulary)
            for alias in ingredient_match_terms(ingredient)
        )
        max_words = max((len(ingredient.split()) for ingredient in vocabulary), default=1)

        _similarity_cache["ingredient_vocabulary"] = frozenset(vocabulary)
        _similarity_cache["max_ingredient_words"] = max_words
        _similarity_cache["vocab_built"] = True
        return _similarity_cache["ingredient_vocabulary"], _similarity_cache["max_ingredient_words"]


def extract_known_ingredients(text, vocabulary, max_words):
    if not vocabulary:
        return []

    words = normalize_query_words(text)
    if not words:
        return []

    single_word_ingredients = {
        ingredient
        for ingredient in vocabulary
        if " " not in ingredient and ingredient not in BASIC_INGREDIENTS
    }
    ingredients = []
    index = 0
    while index < len(words):
        matched_tokens = None
        matched_length = 0

        for length in range(min(max_words, len(words) - index), 0, -1):
            phrase = " ".join(words[index:index + length])
            normalized_tokens = clean_ingredients(phrase)
            if normalized_tokens and all(token in vocabulary for token in normalized_tokens):
                matched_tokens = normalized_tokens
                matched_length = length
                break

        if matched_tokens:
            ingredients.extend(matched_tokens)
            index += matched_length
            continue

        word = words[index]
        if len(word) >= 5:
            close_matches = get_close_matches(word, single_word_ingredients, n=1, cutoff=0.84)
            if close_matches:
                ingredients.append(close_matches[0])

        index += 1

    return list(dict.fromkeys(ingredients))


def parse_ingredient_query(text):
    cleaned = clean_ingredients(text)
    vocabulary, max_words = get_ingredient_vocabulary()
    extracted = extract_known_ingredients(text, vocabulary, max_words)
    if extracted:
        cleaned = extracted
    return cleaned, ", ".join(cleaned)


def ingredient_match_terms(ingredient):
    normalized = normalize_search_text(ingredient).lower()
    if not normalized:
        return set()

    terms = {normalized}
    terms.update(INGREDIENT_MATCH_ALIASES.get(normalized, set()))

    words = normalized.split()
    if len(words) > 1:
        terms.update(GENERIC_HEAD_ALIASES.get(words[-1], set()))

    word_set = set(words)
    if "cod" in word_set:
        terms.add("cod")
    if normalized == "fish" or normalized.endswith(" fish"):
        terms.add("fish")

    return terms


def recipe_ingredient_matches_user(ingredient, user_ingredient_set):
    return bool(ingredient_match_terms(ingredient) & user_ingredient_set)


def matched_recipe_ingredients(recipe_ingredients, user_ingredient_set):
    return sorted(
        ingredient
        for ingredient in recipe_ingredients
        if recipe_ingredient_matches_user(ingredient, user_ingredient_set)
    )


def missing_recipe_ingredients(recipe_ingredients, user_ingredient_set):
    return sorted(
        ingredient
        for ingredient in recipe_ingredients
        if not recipe_ingredient_matches_user(ingredient, user_ingredient_set)
    )


def ingredient_feature_text(ingredients):
    terms = []
    for ingredient in ingredients:
        for normalized in sorted(ingredient_match_terms(ingredient)):
            if not normalized:
                continue
            if " " in normalized:
                terms.append(normalized.replace(" ", "_"))
            terms.extend(normalized.split())
    return " ".join(terms)


def required_recipe_ingredients(recipe):
    return set(recipe.ingredient_list()) - BASIC_INGREDIENTS


def entered_user_ingredient_set(user_ingredients):
    return set(user_ingredients) - BASIC_INGREDIENTS


def matching_user_ingredient_set(user_ingredients):
    return entered_user_ingredient_set(user_ingredients)


def recipe_query_text(recipe):
    required_ingredients = sorted(required_recipe_ingredients(recipe))
    return ingredient_feature_text(required_ingredients)


def title_relevance_score(recipe, query_text):
    query_words = [word for word in normalize_query_words(query_text) if word not in TITLE_STOPWORDS]
    title_words = normalize_query_words(recipe.title)
    if not query_words or not title_words:
        return 0.0

    unique_query_words = set(query_words)
    unique_title_words = set(title_words)
    token_ratio = len(unique_query_words & unique_title_words) / len(unique_query_words)
    normalized_query = " ".join(query_words)
    normalized_title = " ".join(title_words)
    phrase_bonus = 1.0 if normalized_query and normalized_query in normalized_title else 0.0
    exact_bonus = 1.0 if normalized_query == normalized_title else 0.0
    return min(1.0, (token_ratio * 0.65) + (phrase_bonus * 0.25) + (exact_bonus * 0.10))


def best_title_relevance_score(recipe, *query_texts):
    return max((title_relevance_score(recipe, query_text) for query_text in query_texts if query_text), default=0.0)


def build_similarity_index():
    with _similarity_cache_lock:
        if _similarity_cache["index_built"]:
            return _similarity_cache.copy()

        recipes = Recipe.query.order_by(Recipe.id.asc()).all()
        if not recipes:
            _similarity_cache["index_built"] = True
            return _similarity_cache.copy()

        recipe_texts = [recipe_query_text(recipe) for recipe in recipes]
        if not any(recipe_texts):
            _similarity_cache["index_built"] = True
            _similarity_cache["recipe_ids"] = tuple(recipe.id for recipe in recipes)
            _similarity_cache["recipe_positions"] = {recipe.id: index for index, recipe in enumerate(recipes)}
            return _similarity_cache.copy()

        vectorizer = TfidfVectorizer()
        matrix = vectorizer.fit_transform(recipe_texts)

        _similarity_cache["recipe_ids"] = tuple(recipe.id for recipe in recipes)
        _similarity_cache["recipe_positions"] = {recipe.id: index for index, recipe in enumerate(recipes)}
        _similarity_cache["vectorizer"] = vectorizer
        _similarity_cache["matrix"] = matrix
        _similarity_cache["index_built"] = True
        return _similarity_cache.copy()


def score_recipes_by_similarity(user_ingredients):
    similarity_index = build_similarity_index()
    vectorizer = similarity_index["vectorizer"]
    matrix = similarity_index["matrix"]
    if vectorizer is None or matrix is None:
        return {}

    query_ingredients = [ingredient for ingredient in user_ingredients if ingredient not in BASIC_INGREDIENTS] or user_ingredients
    query_text = ingredient_feature_text(query_ingredients)
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


def sort_strict_matches(matches, user_ingredients, ingredients_text, normalized_input):
    user_ingredient_set = matching_user_ingredient_set(user_ingredients)
    entered_ingredient_set = entered_user_ingredient_set(user_ingredients)
    similarity_scores = score_recipes_by_similarity(user_ingredients)

    def sort_key(recipe):
        recipe_ingredients = required_recipe_ingredients(recipe)
        matched_count = len(matched_recipe_ingredients(recipe_ingredients, user_ingredient_set))
        query_coverage = min(1.0, matched_count / len(entered_ingredient_set)) if entered_ingredient_set else 0.0
        return (
            -matched_count,
            -query_coverage,
            -similarity_scores.get(recipe.id, 0.0),
            -best_title_relevance_score(recipe, ingredients_text, normalized_input),
            recipe.cooking_time or 0,
            recipe.title.lower(),
        )

    matches.sort(key=sort_key)


def sort_similar_matches(matches, sort_key):
    if sort_key == "title_asc":
        matches.sort(key=lambda item: (item["recipe"].title.lower(), -item["relevance_score"], item["missing_count"]))
        return

    if sort_key == "title_desc":
        matches.sort(
            key=lambda item: (
                -item["relevance_score"],
                item["missing_count"],
                item["recipe"].title.lower(),
            )
        )
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
            item["missing_count"],
            -item.get("relevance_value", item["relevance_score"]),
            -item["match_count"],
            -item["match_ratio"],
            -item["score"],
            item["recipe"].title.lower(),
        )
    )


def relevance_value(match_ratio, query_coverage, similarity_score, missing_count, max_missing, title_score=0.0):
    completeness_score = 1 - (missing_count / max_missing) if max_missing else 0
    weighted_score = (
        (completeness_score * 0.85)
        + (match_ratio * 0.10)
        + (query_coverage * 0.03)
        + (similarity_score * 0.01)
        + (title_score * 0.01)
    )
    return max(0, min(1, weighted_score)) * 100


def get_strict_recommendations(ingredients_text, page, per_page, diet="", difficulty=""):
    user_ingredients, normalized_input = parse_ingredient_query(ingredients_text)
    user_ingredient_set = matching_user_ingredient_set(user_ingredients)
    matches = []
    seen_recipes = set()

    if user_ingredients:
        query = Recipe.query.order_by(Recipe.id.asc())
        if diet:
            query = query.filter(Recipe.diet_type == diet)
        if difficulty:
            query = query.filter(Recipe.difficulty == difficulty)

        for recipe in query.all():
            recipe_key = (recipe.title.lower(), ",".join(recipe.ingredient_list()))
            if recipe_key in seen_recipes:
                continue

            recipe_required = required_recipe_ingredients(recipe)
            if not recipe_required:
                continue
            if recipe_required and not missing_recipe_ingredients(recipe_required, user_ingredient_set):
                matches.append(recipe)
                seen_recipes.add(recipe_key)

    sort_strict_matches(matches, user_ingredients, ingredients_text, normalized_input)
    return {
        "ingredients": user_ingredients,
        "ingredients_text": normalized_input,
        "strict": paginate_list(matches, page, per_page),
    }


def get_similar_recommendations(ingredients_text, filters, page, per_page, max_missing=5):
    user_ingredients, normalized_input = parse_ingredient_query(ingredients_text)
    user_ingredient_set = matching_user_ingredient_set(user_ingredients)
    entered_ingredient_set = entered_user_ingredient_set(user_ingredients)

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
        title_score = best_title_relevance_score(recipe, ingredients_text, normalized_input)
        is_title_match = title_score >= TITLE_MATCH_THRESHOLD

        missing = missing_recipe_ingredients(recipe_ingredients, user_ingredient_set)
        if not missing:
            continue

        matched = matched_recipe_ingredients(recipe_ingredients, user_ingredient_set)

        if not matched and not is_title_match:
            continue

        required_count = len(recipe_ingredients)
        match_count = len(matched)
        match_ratio = match_count / required_count if required_count else 0.0
        missing_count = len(missing)
        similarity_score = similarity_scores.get(recipe.id, 0.0)
        query_coverage = min(1.0, match_count / len(entered_ingredient_set)) if entered_ingredient_set else 0.0
        is_primary_ingredient_match = bool(entered_ingredient_set) and len(entered_ingredient_set) <= 2 and query_coverage >= 1.0
        is_complete_query_match = bool(entered_ingredient_set) and len(entered_ingredient_set) <= 4 and query_coverage >= 1.0

        if not 1 <= missing_count <= max_missing:
            continue

        is_strong_match = (
            is_title_match
            or is_primary_ingredient_match
            or is_complete_query_match
            or match_count >= MIN_SIMILAR_MATCH_COUNT
            or match_ratio >= MIN_SIMILAR_MATCH_RATIO
        )
        is_fallback_match = match_count >= 1 and missing_count <= 2
        if not is_strong_match and not is_fallback_match:
            continue

        relevance_display_value = relevance_value(
            match_ratio,
            query_coverage,
            similarity_score,
            missing_count,
            max_missing,
            title_score,
        )
        relevance_score = round(relevance_display_value, 6)

        candidates.append(
            {
                "recipe": recipe,
                "missing": missing,
                "matched": matched,
                "score": similarity_score,
                "title_score": title_score,
                "match_count": match_count,
                "match_ratio": match_ratio,
                "missing_count": missing_count,
                "required_count": required_count,
                "relevance_score": relevance_score,
                "relevance_value": round(relevance_display_value, 6),
                "relevance_percent": round(relevance_display_value),
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
