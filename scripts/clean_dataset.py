import argparse
import csv
import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.append(str(BASE_DIR))

os.environ.setdefault("COGNICOOK_SKIP_APP_BOOTSTRAP", "1")

from services.data_loader import load_dataset_rows

DEFAULT_INPUT = BASE_DIR / "dataset" / "raw_recipes.csv"
DEFAULT_OUTPUT = BASE_DIR / "dataset" / "recipes.csv"
OUTPUT_COLUMNS = [
    "title",
    "ingredients",
    "cleaned_ingredients",
    "ingredient_measurements",
    "instructions",
    "diet_type",
    "difficulty",
    "cooking_time",
]


def clean_dataset(input_path=DEFAULT_INPUT, output_path=DEFAULT_OUTPUT):
    input_path = Path(input_path)
    output_path = Path(output_path)

    if input_path.resolve() == output_path.resolve():
        raise ValueError("Input and output paths must not refer to the same file")

    rows = load_dataset_rows(input_path)
    if not rows:
        raise ValueError(f"No valid rows found in {input_path}")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=OUTPUT_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)

    return len(rows), output_path


def parse_args():
    parser = argparse.ArgumentParser(description="Clean the Cogni Cook (Intelligent Recipe Recommendation System) recipe CSV into the canonical dataset file.")
    parser.add_argument("--input", default=str(DEFAULT_INPUT), help="Raw CSV path to clean.")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help="Clean canonical CSV path to write.")
    return parser.parse_args()


def main():
    args = parse_args()
    imported, output_path = clean_dataset(args.input, args.output)
    print(f"Cleaned {imported} recipes into {output_path}")


if __name__ == "__main__":
    main()
