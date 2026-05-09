import os
import secrets
from datetime import timedelta
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
INSTANCE_PATH = Path(os.environ.get("COGNICOOK_DATA_DIR") or (BASE_DIR / "instance"))
DATABASE_PATH = Path(os.environ.get("COGNICOOK_DB_PATH") or (INSTANCE_PATH / "cognicook.db"))
LEGACY_DATABASE_PATH = BASE_DIR / "database" / "cognicook.db"
APP_ENV = os.environ.get("COGNICOOK_ENV", os.environ.get("FLASK_ENV", "development")).strip().lower()
DEFAULT_SECURE_COOKIE = "1" if APP_ENV == "production" else "0"
SECRET_KEY = os.environ.get("SECRET_KEY")
SECRET_KEY_FROM_ENV = bool(SECRET_KEY)
if not SECRET_KEY:
    INSTANCE_PATH.mkdir(parents=True, exist_ok=True)
    dev_secret_path = INSTANCE_PATH / ".secret_key"
    try:
        SECRET_KEY = dev_secret_path.read_text(encoding="utf-8").strip()
    except OSError:
        SECRET_KEY = ""

    if not SECRET_KEY:
        SECRET_KEY = secrets.token_urlsafe(48)
        try:
            dev_secret_path.write_text(SECRET_KEY, encoding="utf-8")
        except OSError:
            pass


class Config:
    SECRET_KEY = SECRET_KEY
    SECRET_KEY_FROM_ENV = SECRET_KEY_FROM_ENV
    REQUIRE_SECRET_KEY_FROM_ENV = APP_ENV == "production"
    DATABASE_FILE = DATABASE_PATH.as_posix()
    LEGACY_DATABASE_FILE = LEGACY_DATABASE_PATH.as_posix()
    SQLALCHEMY_DATABASE_URI = f"sqlite:///{DATABASE_PATH.as_posix()}"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = os.environ.get("SESSION_COOKIE_SECURE", DEFAULT_SECURE_COOKIE) == "1"
    REMEMBER_COOKIE_HTTPONLY = True
    REMEMBER_COOKIE_SAMESITE = "Lax"
    REMEMBER_COOKIE_SECURE = SESSION_COOKIE_SECURE
    PERMANENT_SESSION_LIFETIME = timedelta(hours=8)
    MAX_CONTENT_LENGTH = 1024 * 1024
    DATASET_PATH = str(BASE_DIR / "dataset" / "recipes.csv")
    AUTO_BOOTSTRAP_DATA = os.environ.get("AUTO_BOOTSTRAP_DATA", "1") == "1"
    RESULTS_PER_PAGE = 12
    MAX_PER_PAGE = 24
    AUTH_RATE_LIMIT_WINDOW_SECONDS = 60
    AUTH_RATE_LIMIT_MAX_ATTEMPTS = 5
    AUTH_RATE_LIMIT_TRUST_PROXY_HEADERS = os.environ.get("AUTH_RATE_LIMIT_TRUST_PROXY_HEADERS", "0") == "1"
    AUTH_RATE_LIMIT_TRUSTED_PROXIES = {
        value.strip()
        for value in os.environ.get("AUTH_RATE_LIMIT_TRUSTED_PROXIES", "").split(",")
        if value.strip()
    }
