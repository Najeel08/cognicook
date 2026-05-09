"""
Legacy import script kept for compatibility with earlier project iterations.
Use database/import_dataset.py for the final canonical CSV workflow.
"""

import os
import sys

import pandas as pd

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(BASE_DIR)

from app import create_app
from services.data_loader import normalize_row, replace_recipe_rows

EXCEL_PATH = os.path.join(BASE_DIR, "dataset", "Indian_Food_Recipe_Dataset.xlsx")


def import_excel():
    app = create_app()

    with app.app_context():
        dataframe = pd.read_excel(EXCEL_PATH)
        rows = []

        for record in dataframe.to_dict(orient="records"):
            normalized = normalize_row(record)
            if normalized is not None:
                rows.append(normalized)

        imported = replace_recipe_rows(rows, preserve_favorites=True)
        print(f"Recipes imported successfully from Excel dataset: {imported}")


if __name__ == "__main__":
    import_excel()
