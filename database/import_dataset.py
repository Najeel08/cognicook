import os
import sys
import argparse

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(BASE_DIR)

os.environ.setdefault("COGNICOOK_SKIP_APP_BOOTSTRAP", "1")
os.environ.setdefault("AUTO_BOOTSTRAP_DATA", "0")

from app import create_app
from services.data_loader import replace_recipe_data


def parse_args():
    parser = argparse.ArgumentParser(description="Import the canonical CogniCook CSV dataset into the database.")
    parser.add_argument("--dataset", help="CSV dataset path. Defaults to Config.DATASET_PATH.")
    parser.add_argument(
        "--no-preserve-favorites",
        action="store_true",
        help="Do not restore matching favorites after recipe replacement.",
    )
    return parser.parse_args()


def import_dataset(dataset_path=None, preserve_favorites=True):
    app = create_app()

    with app.app_context():
        path = dataset_path or app.config["DATASET_PATH"]
        imported = replace_recipe_data(path, preserve_favorites=preserve_favorites)
        print(f"Imported {imported} recipes from {path}.")


if __name__ == "__main__":
    args = parse_args()
    import_dataset(args.dataset, preserve_favorites=not args.no_preserve_favorites)
