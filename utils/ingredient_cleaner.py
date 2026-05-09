import re

REMOVE_WORDS = [
    "finely chopped",
    "roughly chopped",
    "thinly sliced",
    "freshly grated",
    "chopped",
    "fresh",
    "boiled",
    "fried",
    "roasted",
    "grated",
    "crushed",
    "powdered",
    "sliced",
    "diced",
    "minced",
    "ground",
    "soaked",
    "peeled",
    "dried",
    "washed",
    "cleaned",
    "deveined",
    "boneless",
    "skinless",
    "cubed",
    "shredded",
    "mashed",
    "cooked",
    "uncooked",
    "warm",
    "hot",
    "cold",
    "small",
    "large",
    "medium",
    "ripe",
    "raw",
    "whole",
    "optional",
]

PLURAL_MAP = {
    "tomatoes": "tomato",
    "potatoes": "potato",
    "onions": "onion",
    "eggs": "egg",
    "chilies": "green chilli",
    "chillies": "green chilli",
    "green chilies": "green chilli",
    "green chillies": "green chilli",
    "lentils": "lentil",
    "beans": "beans",
    "carrots": "carrot",
    "peas": "peas",
    "cashews": "cashew nuts",
    "cashew": "cashew nuts",
    "peanuts": "peanuts",
    "shallots": "shallots",
    "cloves": "cloves",
    "leaves": "leaves",
    "curry leaf": "curry leaves",
    "coriander leaf": "coriander leaves",
    "drumsticks": "drumstick",
    "prawns": "prawns",
    "vegetables": "vegetables",
    "chickpeas": "chickpeas",
    "kidney beans": "kidney beans",
    "seeds": "seeds",
    "mustards": "mustard seeds",
    "coconuts": "coconut",
    "lemons": "lemon",
    "bananas": "banana",
    "apples": "apple",
}

INGREDIENT_ALIASES = {
    "chili": "green chilli",
    "chilli": "green chilli",
    "green chili": "green chilli",
    "green green chilli": "green chilli",
    "green chilies": "green chilli",
    "green chillies": "green chilli",
    "red chili": "dry red chilli",
    "red chilli": "dry red chilli",
    "chili powder": "chilli powder",
    "chilly powder": "chilli powder",
    "red chili powder": "red chilli powder",
    "red chilly powder": "red chilli powder",
    "cumin": "cumin seeds",
    "mustard": "mustard seeds",
    "curd": "yogurt",
    "yoghurt": "yogurt",
    "cilantro": "coriander leaves",
    "coriander leaf": "coriander leaves",
    "garlic paste": "garlic",
    "ginger paste": "ginger",
}

COMPOUND_INGREDIENTS = {
    "ginger garlic paste": ("ginger", "garlic"),
    "ginger garlic": ("ginger", "garlic"),
    "ginger-garlic paste": ("ginger", "garlic"),
    "ginger-garlic": ("ginger", "garlic"),
}

REMOVE_WORDS_PATTERN = re.compile(
    r"\b(?:%s)\b" % "|".join(re.escape(word) for word in sorted(REMOVE_WORDS, key=len, reverse=True))
)
PLURAL_PATTERN = re.compile(
    r"\b(?:%s)\b" % "|".join(re.escape(word) for word in sorted(PLURAL_MAP, key=len, reverse=True))
)
SPLIT_PATTERN = re.compile(r"\s*(?:,|;|\n|\r|\band\b|\bor\b)\s*", re.IGNORECASE)


def normalize_search_text(value):
    return " ".join(str(value or "").split()).strip()


def normalize_ingredient_tokens(value):
    if not value:
        return []

    text = str(value).lower()
    text = text.replace("&", " and ")
    text = re.sub(r"[-/]", " ", text)
    text = PLURAL_PATTERN.sub(lambda match: PLURAL_MAP[match.group(0)], text)
    text = REMOVE_WORDS_PATTERN.sub("", text)
    text = re.sub(r"[^a-zA-Z,;\n\r ]", "", text)

    ingredients = []
    for item in SPLIT_PATTERN.split(text):
        ingredient = normalize_search_text(item).lower()
        if not ingredient:
            continue

        if ingredient in COMPOUND_INGREDIENTS:
            ingredients.extend(COMPOUND_INGREDIENTS[ingredient])
            continue

        ingredients.append(INGREDIENT_ALIASES.get(ingredient, ingredient))

    return list(dict.fromkeys(ingredients))


def normalize_ingredient_text(value):
    return ",".join(normalize_ingredient_tokens(value))


def clean_ingredients(user_input):
    return normalize_ingredient_tokens(user_input)
