import json
import re
from dataclasses import dataclass

from utils.ingredient_cleaner import clean_ingredients, normalize_search_text


@dataclass(frozen=True)
class IngredientMeasurement:
    ingredient: str
    measurement: str = ""
    quantity: str = ""
    unit: str = ""
    note: str = ""

    @property
    def display_measurement(self):
        parts = [part for part in (self.quantity, self.unit) if part]
        if parts:
            return " ".join(parts)
        return self.measurement or self.note

    def to_storage_dict(self):
        return {
            "ingredient": self.ingredient,
            "measurement": self.measurement,
            "quantity": self.quantity,
            "unit": self.unit,
            "note": self.note,
        }


def _clean_text(value):
    return " ".join(str(value or "").strip().split())


def _clean_ingredient(value):
    normalized_tokens = clean_ingredients(value)
    if normalized_tokens:
        return normalized_tokens[0]
    return normalize_search_text(value).lower()


def _measurement_from_mapping(mapping):
    ingredient = _clean_ingredient(
        mapping.get("ingredient")
        or mapping.get("name")
        or mapping.get("item")
        or mapping.get("ingredient_name")
    )
    measurement = _clean_text(
        mapping.get("measurement")
        or mapping.get("measure")
        or mapping.get("amount")
        or mapping.get("display")
    )
    quantity = _clean_text(mapping.get("quantity") or mapping.get("qty"))
    unit = _clean_text(mapping.get("unit"))
    note = _clean_text(mapping.get("note") or mapping.get("notes"))

    if not ingredient or not (measurement or quantity or unit or note):
        return None

    return IngredientMeasurement(
        ingredient=ingredient,
        measurement=measurement,
        quantity=quantity,
        unit=unit,
        note=note,
    )


def _measurement_from_pair(ingredient, measurement):
    ingredient = _clean_ingredient(ingredient)
    measurement = _clean_text(measurement)
    if not ingredient or not measurement:
        return None
    return IngredientMeasurement(ingredient=ingredient, measurement=measurement)


def _measurements_from_dict(value):
    records = []
    for ingredient, measurement in value.items():
        if isinstance(measurement, dict):
            record = _measurement_from_mapping({"ingredient": ingredient, **measurement})
        else:
            record = _measurement_from_pair(ingredient, measurement)
        if record:
            records.append(record)
    return records


def _measurements_from_sequence(value):
    records = []
    for item in value:
        record = None
        if isinstance(item, dict):
            record = _measurement_from_mapping(item)
        elif isinstance(item, (list, tuple)) and len(item) >= 2:
            record = _measurement_from_pair(item[0], item[1])
        if record:
            records.append(record)
    return records


def _measurements_from_text(value):
    text = _clean_text(value)
    if not text:
        return []

    if text[0] in "[{":
        try:
            return parse_ingredient_measurements(json.loads(text))
        except (TypeError, ValueError, json.JSONDecodeError):
            pass

    records = []
    for chunk in re.split(r"\s*(?:;|\||\n)\s*", text):
        if not chunk:
            continue
        if ":" in chunk:
            ingredient, measurement = chunk.split(":", 1)
        elif " - " in chunk:
            ingredient, measurement = chunk.split(" - ", 1)
        else:
            continue
        record = _measurement_from_pair(ingredient, measurement)
        if record:
            records.append(record)
    return records


def parse_ingredient_measurements(value, known_ingredients=None):
    """Parse future dataset measurement formats into a stable internal shape."""
    if value in (None, ""):
        return []

    if isinstance(value, dict):
        records = _measurements_from_dict(value)
    elif isinstance(value, (list, tuple)):
        records = _measurements_from_sequence(value)
    else:
        records = _measurements_from_text(value)

    if known_ingredients:
        known = {_clean_ingredient(ingredient) for ingredient in re.split(r"[,;\n|]+", str(known_ingredients))}
        records = [record for record in records if not known or record.ingredient in known]

    deduped = {}
    for record in records:
        deduped.setdefault(record.ingredient, record)
    return list(deduped.values())


def serialize_ingredient_measurements(value, known_ingredients=None):
    records = parse_ingredient_measurements(value, known_ingredients=known_ingredients)
    if not records:
        return ""
    return json.dumps([record.to_storage_dict() for record in records], separators=(",", ":"))
