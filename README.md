# Cogni Cook (Intelligent Recipe Recommendation System)

Cogni Cook (Intelligent Recipe Recommendation System) is a Flask recipe recommendation web app that finds recipes from ingredients a user already has. It supports exact ingredient matches, similarity-based recommendations, filters, user accounts, and saved favorites.

## Features

- Search recipes by available ingredients
- View exact matches and similar recipe suggestions
- Filter recipes by diet type and difficulty
- Register, log in, and manage saved favorites
- View recipe details with ingredients, measurements, and cooking instructions

## Tech Stack

- Python, Flask, Flask-Login
- SQLAlchemy with SQLite
- pandas, scikit-learn, TF-IDF, cosine similarity
- HTML, CSS, JavaScript
- Python `unittest`

## Project Structure

- `app.py` - application setup, security middleware, error handlers, and database initialization
- `routes.py` - page routes and user workflows
- `models/` - database models
- `services/` - recipe data loading and recommendation logic
- `utils/` - validation, ingredient normalization, instruction parsing, and pagination helpers
- `templates/` and `static/` - frontend templates, styles, and scripts
- `dataset/recipes.csv` - runtime recipe dataset
- `scripts/` - dataset cleaning and import scripts
- `tests/` - automated tests and fixtures

## Local Setup

```powershell
py -3.13 -m venv venv
.\venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python app.py
```

Open `http://127.0.0.1:5000` in the browser.

For custom configuration, set environment variables in the shell or process manager before starting the app. See `.env.example` for supported variable names.

## Tests

```powershell
python -m unittest discover -s tests -p test_*.py
```

## Dataset Maintenance

Regenerate `dataset/recipes.csv` from the raw dataset:

```powershell
python scripts/clean_dataset.py
```

Import the dataset into the local database:

```powershell
python scripts/import_dataset.py
```
