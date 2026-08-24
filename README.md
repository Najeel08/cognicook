# Cogni Cook: Intelligent Recipe Recommendation System

Cogni Cook is a Flask-based web application that recommends recipes based on ingredients you already have. It provides exact ingredient matching, similarity-based recipe discovery, dietary and difficulty filters, user authentication, and saved favorites.

## Features

- **Ingredient-Based Search:** Find dishes you can prepare using available ingredients.
- **Exact & Similar Matches:** Surfaces recipes you can make immediately, along with close matches requiring only a few extra items.
- **Dietary & Difficulty Filters:** Filter recommendations by diet type (vegetarian / non-vegetarian) and cooking difficulty (easy, medium, hard).
- **User Accounts & Favorites:** Register, log in, and bookmark your favorite recipes.
- **Detailed Recipe View:** Step-by-step cooking instructions, ingredient lists, and measurements.

## Tech Stack

- **Backend:** Python, Flask, Flask-Login
- **Database & ORM:** SQLite, SQLAlchemy
- **Machine Learning & Data:** scikit-learn (TF-IDF Vectorization, Cosine Similarity), pandas
- **Frontend:** HTML5, CSS3, JavaScript
- **Testing:** Python `unittest`

## Project Structure

- `app.py` - Application entry point, configuration, middleware, and error handlers.
- `routes.py` - Web endpoints, authentication flows, and view logic.
- `config.py` - Application and security settings.
- `models/` - SQLAlchemy database models (`User`, `Recipe`, `Favorite`, `AuthAttempt`).
- `services/` - Recommendation engine and dataset loader.
- `utils/` - Input validation, ingredient normalization, and pagination utilities.
- `templates/` & `static/` - Jinja2 HTML templates, styling, and client-side scripts.
- `dataset/` - Raw and canonical recipe datasets (`recipes.csv`).
- `scripts/` - Dataset cleaning and database import utilities.
- `tests/` - Automated test suite covering security, authentication, and recommendations.

## Local Setup

### 1. Create and activate a virtual environment

- **Windows (PowerShell):**
  ```powershell
  python -m venv venv
  .\venv\Scripts\Activate.ps1
  ```
- **macOS / Linux:**
  ```bash
  python3 -m venv venv
  source venv/bin/activate
  ```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Run the application

```bash
python app.py
```

Open `http://127.0.0.1:5000` in your web browser.

> **Note:** For custom configuration, refer to `.env.example` for available environment variables.

## Running Tests

Execute the automated test suite with:

```bash
python -m unittest discover -s tests -p "test_*.py"
```

## Dataset Maintenance

- **Clean and preprocess raw dataset:**
  ```bash
  python scripts/clean_dataset.py
  ```

- **Import recipes into the local database:**
  ```bash
  python scripts/import_dataset.py
  ```

