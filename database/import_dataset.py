import os
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(BASE_DIR)

os.environ.setdefault("COGNICOOK_SKIP_APP_BOOTSTRAP", "1")

from app import create_app
from services.data_loader import replace_recipe_data


def import_dataset():
    app = create_app()

    with app.app_context():
        imported = replace_recipe_data(app.config["DATASET_PATH"])
        print(f"Imported {imported} recipes from the canonical CSV dataset.")


if __name__ == "__main__":
    import_dataset()
