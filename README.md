# CogniCook

CogniCook is a Flask-based recipe recommendation system that finds recipes from ingredients a user already has. It supports exact ingredient matching, TF-IDF and cosine-similarity recommendations, dietary and difficulty filters, authentication, and favorites.

## Technology

- Python and Flask
- SQLAlchemy with SQLite
- scikit-learn TF-IDF and cosine similarity
- HTML, Bootstrap CSS, and JavaScript
- Python `unittest`

## Project Structure

- `app.py` - application factory, security middleware, error handlers, and startup
- `routes.py` - web routes and user workflows
- `models/` - SQLAlchemy models
- `services/` - recommendation and dataset services
- `utils/` - validation, ingredient normalization, instruction parsing, and pagination
- `templates/` and `static/` - frontend
- `dataset/recipes.csv` - canonical runtime dataset
- `dataset/raw_recipes.csv` - raw source dataset used by the cleaning script
- `scripts/` - dataset cleaning and import utilities
- `tests/` - automated tests and fixtures

## Local Setup

```powershell
py -3.13 -m venv venv
.\venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python app.py
```

Open `http://127.0.0.1:5000`.

The application works without a local `.env` file. For custom configuration, set the variables documented in `.env.example` in the shell, IDE launch configuration, or deployment platform.

## Tests

```powershell
python -m unittest discover -s tests -p test_*.py
```

## Dataset Maintenance

Regenerate the canonical dataset from the raw source:

```powershell
python scripts/clean_dataset.py
```

Import the canonical dataset while preserving matching favorites:

```powershell
python scripts/import_dataset.py
```

## Runtime Files

The following are intentionally excluded from version control:

- `.env` and other local environment files
- `instance/` databases, WAL files, and development secrets
- `venv/` and `.venv/`
- `__pycache__/` and test or coverage caches
- log files

Do not include these generated or machine-specific files in a submission archive or deployment artifact.

## Production Notes

Set `COGNICOOK_ENV=production`, provide a strong `SECRET_KEY`, configure explicit `COGNICOOK_TRUSTED_HOSTS`, use HTTPS, and run the application with a production WSGI server rather than Flask's development server.
