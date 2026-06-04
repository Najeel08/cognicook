# CogniCook

CogniCook is a Flask-based intelligent recipe recommendation system. It recommends recipes from available ingredients, separates exact matches from similar recipes, supports dietary and difficulty filters, and lets registered users save favorite recipes.

## Core Features

- Ingredient preprocessing and normalization for consistent matching
- Exact recipe matching using only available ingredients plus kitchen basics
- Similar recipe recommendations using TF-IDF and cosine similarity
- Filters for diet type, difficulty, and result sorting
- User registration, login, logout, favorites, and activity summary
- SQLite persistence through SQLAlchemy models
- CSRF protection, input validation, rate limiting, and security headers

## Project Structure

- `app.py` - Flask app factory, security hooks, database setup, and error handlers
- `routes.py` - web routes and user workflows
- `models/` - SQLAlchemy models
- `services/` - dataset loading and recommendation logic
- `utils/` - validation, ingredient cleanup, pagination, instruction parsing, and measurement parsing
- `templates/` - Jinja templates
- `static/` - CSS and JavaScript assets
- `scripts/` - dataset cleaning/import helpers
- `tests/` - regression and integration tests
- `proposal_pages/` - proposal reference pages used as requirements

## Setup

```powershell
.\venv\Scripts\python.exe -m pip install -r requirements.txt
```

Run the app:

```powershell
.\venv\Scripts\python.exe app.py
```

Run tests:

```powershell
.\venv\Scripts\python.exe -m unittest discover -s tests -p test_*.py
```

## Dataset Maintenance

The live app builds its TF-IDF recommendation index from the recipe database at runtime, so there are no separate model training artifacts to generate or keep in sync.

Clean or import recipe data:

```powershell
.\venv\Scripts\python.exe scripts\clean_dataset.py
.\venv\Scripts\python.exe scripts\import_dataset.py
```

## Production Notes

- Set `SECRET_KEY` in the environment for production.
- Keep `COGNICOOK_ENV=production` for secure-cookie defaults.
- Do not commit `instance/`, SQLite databases, generated artifacts, virtual environments, or Python cache files.
