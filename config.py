import os
import secrets
from datetime import timedelta
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent


def resolve_project_path(value, default):
    path = Path(value).expanduser() if value else Path(default)
    return path if path.is_absolute() else BASE_DIR / path


INSTANCE_PATH = resolve_project_path(os.environ.get("COGNICOOK_DATA_DIR"), "instance")
DATABASE_PATH = resolve_project_path(
    os.environ.get("COGNICOOK_DB_PATH"),
    INSTANCE_PATH / "cognicook.db",
)
DATASET_PATH = resolve_project_path(
    os.environ.get("COGNICOOK_DATASET_PATH"),
    "dataset/recipes.csv",
)
APP_ENV = os.environ.get("COGNICOOK_ENV", os.environ.get("FLASK_ENV", "development")).strip().lower()
IS_PRODUCTION = APP_ENV == "production"
DEFAULT_SECURE_COOKIE = "1" if APP_ENV == "production" else "0"
DEFAULT_AUTO_BOOTSTRAP_DATA = "1"
TRUSTED_HOSTS = [
    value.strip()
    for value in os.environ.get("COGNICOOK_TRUSTED_HOSTS", "").split(",")
    if value.strip()
]
render_host = os.environ.get("RENDER_EXTERNAL_HOSTNAME", "").strip()
if render_host and render_host not in TRUSTED_HOSTS:
    TRUSTED_HOSTS.append(render_host)
SECRET_KEY = os.environ.get("SECRET_KEY")
SECRET_KEY_FROM_ENV = bool(SECRET_KEY)
if not SECRET_KEY and not IS_PRODUCTION:
    INSTANCE_PATH.mkdir(parents=True, exist_ok=True)
    dev_secret_path = INSTANCE_PATH / ".secret_key"
    try:
        SECRET_KEY = dev_secret_path.read_text(encoding="utf-8").strip()
    except OSError:
        SECRET_KEY = None

    if not SECRET_KEY:
        SECRET_KEY = secrets.token_urlsafe(48)
        try:
            dev_secret_path.touch(mode=0o600, exist_ok=True)
            dev_secret_path.write_text(SECRET_KEY, encoding="utf-8")
        except OSError:
            pass


class Config:
    IS_PRODUCTION = IS_PRODUCTION
    SECRET_KEY = SECRET_KEY
    SECRET_KEY_FROM_ENV = SECRET_KEY_FROM_ENV
    REQUIRE_SECRET_KEY_FROM_ENV = IS_PRODUCTION
    DATABASE_FILE = DATABASE_PATH.as_posix()
    SQLALCHEMY_DATABASE_URI = f"sqlite:///{DATABASE_PATH.as_posix()}"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = os.environ.get("SESSION_COOKIE_SECURE", DEFAULT_SECURE_COOKIE) == "1"
    REMEMBER_COOKIE_HTTPONLY = True
    REMEMBER_COOKIE_SAMESITE = "Lax"
    REMEMBER_COOKIE_SECURE = SESSION_COOKIE_SECURE
    SESSION_COOKIE_NAME = "__Host-cognicook_session" if SESSION_COOKIE_SECURE else "cognicook_session"
    PERMANENT_SESSION_LIFETIME = timedelta(hours=8)
    MAX_CONTENT_LENGTH = 1024 * 1024
    SECURITY_HSTS_ENABLED = os.environ.get("SECURITY_HSTS_ENABLED", DEFAULT_SECURE_COOKIE) == "1"
    try:
        SECURITY_HSTS_MAX_AGE = int(os.environ.get("SECURITY_HSTS_MAX_AGE", "31536000"))
    except (ValueError, TypeError):
        SECURITY_HSTS_MAX_AGE = 31536000
    TRUSTED_HOSTS = TRUSTED_HOSTS or None
    DATASET_PATH = DATASET_PATH.as_posix()
    AUTO_BOOTSTRAP_DATA = os.environ.get("AUTO_BOOTSTRAP_DATA", DEFAULT_AUTO_BOOTSTRAP_DATA) == "1"
    RESULTS_PER_PAGE = 12
    MAX_PER_PAGE = 24
    AUTH_RATE_LIMIT_WINDOW_SECONDS = 60
    AUTH_RATE_LIMIT_MAX_ATTEMPTS = 5
    AUTH_REGISTER_RATE_LIMIT_MAX_ATTEMPTS = 20
    AUTH_ACCOUNT_LOCKOUT_WINDOW_SECONDS = 15 * 60
    AUTH_ACCOUNT_LOCKOUT_MAX_ATTEMPTS = 5
    AUTH_REGISTER_ACCOUNT_LOCKOUT_MAX_ATTEMPTS = 10
    AUTH_RATE_LIMIT_TRUST_PROXY_HEADERS = os.environ.get("AUTH_RATE_LIMIT_TRUST_PROXY_HEADERS", "0") == "1"
    AUTH_RATE_LIMIT_TRUSTED_PROXIES = {
        value.strip()
        for value in os.environ.get("AUTH_RATE_LIMIT_TRUSTED_PROXIES", "").split(",")
        if value.strip()
    }
