import os
import secrets
import sqlite3
from hmac import new as hmac_new
from pathlib import Path
from time import time
from urllib.parse import urlencode

from flask import Flask, abort, flash, redirect, render_template, request, session, url_for
from sqlalchemy import event, inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError
from werkzeug.exceptions import SecurityError

from config import Config
from extensions import db, login_manager
from models.auth_attempt import AuthAttempt
from utils.ingredient_cleaner import normalize_ingredient_text
from utils.validators import is_safe_input

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
ALLOWED_QUERY_PARAMS_BY_ENDPOINT = {
    "landing": set(),
    "login": set(),
    "register": set(),
    "dashboard": set(),
    "recommendations": {"ingredients", "page", "per_page"},
    "similar_recipes_page": {"ingredients", "diet", "difficulty", "sort", "page", "per_page"},
    "favorites": {"page", "per_page"},
    "activity_summary": {"page", "per_page"},
    "favorite": set(),
    "remove_favorite": set(),
    "recipe_detail": {"next"},
    "logout": set(),
}
QUERY_PARAM_MAX_LENGTHS = {
    "ingredients": 1000,
    "page": 6,
    "per_page": 3,
    "diet": 20,
    "difficulty": 20,
    "sort": 30,
    "next": 1200,
}


@event.listens_for(Engine, "connect")
def configure_sqlite_connection(dbapi_connection, connection_record):
    if isinstance(dbapi_connection, sqlite3.Connection):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.close()


def sqlite_file_is_usable(path):
    if not path.exists():
        return True
    if path.stat().st_size == 0:
        return False

    try:
        with sqlite3.connect(path.as_posix(), timeout=5) as connection:
            connection.execute("SELECT name FROM sqlite_master LIMIT 1").fetchone()
            return connection.execute("PRAGMA integrity_check").fetchone() == ("ok",)
    except sqlite3.Error:
        return False


def recover_sqlite_file(source_path, recovered_path):
    source_uri = f"{source_path.resolve().as_uri()}?mode=ro&immutable=1"
    with sqlite3.connect(source_uri, uri=True) as source:
        if source.execute("PRAGMA integrity_check").fetchone() != ("ok",):
            raise RuntimeError(f"Unable to recover corrupt SQLite database: {source_path}")
        dump_sql = "\n".join(source.iterdump())

    with sqlite3.connect(recovered_path.as_posix(), isolation_level=None) as target:
        target.execute("PRAGMA journal_mode=WAL")
        target.execute("PRAGMA synchronous=NORMAL")
        target.executescript(dump_sql)


def choose_recovered_database_path(database_path):
    for index in range(1, 100):
        suffix = ".recovered" if index == 1 else f".recovered{index}"
        candidate = database_path.with_name(f"{database_path.stem}{suffix}{database_path.suffix}")
        journal = candidate.with_name(f"{candidate.name}-journal")

        if candidate.exists() and sqlite_file_is_usable(candidate):
            return candidate

        if not candidate.exists() and not journal.exists():
            return candidate

    raise RuntimeError(f"Unable to choose a recovered SQLite database path for {database_path}")


def prepare_database_file(app):
    database_file = app.config.get("DATABASE_FILE")
    if not database_file:
        return

    database_path = Path(database_file)
    database_path.parent.mkdir(parents=True, exist_ok=True)

    if database_path.exists() and not sqlite_file_is_usable(database_path):
        recovered_path = choose_recovered_database_path(database_path)
        if not recovered_path.exists():
            try:
                recover_sqlite_file(database_path, recovered_path)
            except (RuntimeError, sqlite3.Error) as e:
                app.logger.error(
                    "Database recovery failed for %s: %s. Using empty database.",
                    database_path, e
                )
                recovered_path = choose_recovered_database_path(database_path)

        app.config["DATABASE_FILE"] = recovered_path.as_posix()
        app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{recovered_path.as_posix()}"


def ensure_recipe_schema():
    inspector = inspect(db.engine)
    if not inspector.has_table("recipe"):
        return

    column_names = {column["name"] for column in inspector.get_columns("recipe")}
    with db.engine.begin() as connection:
        # Keep existing SQLite databases compatible until the project adopts migrations.
        if "cleaned_ingredients" not in column_names:
            connection.execute(
                text("ALTER TABLE recipe ADD COLUMN cleaned_ingredients TEXT NOT NULL DEFAULT ''")
            )

        if "ingredient_measurements" not in column_names:
            connection.execute(text("ALTER TABLE recipe ADD COLUMN ingredient_measurements TEXT"))

        rows = connection.execute(
            text(
                "SELECT id, ingredients FROM recipe "
                "WHERE cleaned_ingredients IS NULL OR cleaned_ingredients = ''"
            )
        ).mappings()
        for row in rows:
            connection.execute(
                text("UPDATE recipe SET cleaned_ingredients = :cleaned_ingredients WHERE id = :recipe_id"),
                {
                    "cleaned_ingredients": normalize_ingredient_text(row["ingredients"]),
                    "recipe_id": row["id"],
                },
            )


def create_app(config_object=Config):
    app = Flask(__name__)
    app.config.from_object(config_object)
    os.makedirs(app.instance_path, exist_ok=True)

    if app.config.get("REQUIRE_SECRET_KEY_FROM_ENV") and not app.config.get("SECRET_KEY_FROM_ENV"):
        raise RuntimeError("SECRET_KEY must be provided via the environment in production.")
    if app.config.get("IS_PRODUCTION"):
        if len(str(app.config.get("SECRET_KEY") or "")) < 32:
            raise RuntimeError("SECRET_KEY must be at least 32 characters in production.")
        if not app.config.get("SESSION_COOKIE_SECURE"):
            raise RuntimeError("SESSION_COOKIE_SECURE must be enabled in production.")
        trusted_hosts = app.config.get("TRUSTED_HOSTS") or []
        if not trusted_hosts or "*" in trusted_hosts:
            raise RuntimeError("COGNICOOK_TRUSTED_HOSTS must contain explicit production hostnames.")

    prepare_database_file(app)

    db.init_app(app)
    login_manager.init_app(app)
    login_manager.session_protection = "strong"

    @login_manager.unauthorized_handler
    def handle_unauthorized():
        flash("Please log in to continue.", "warning")
        return redirect(url_for("login"))

    def generate_csrf_token():
        token = session.get("_csrf_token")
        if not token:
            token = secrets.token_urlsafe(32)
            session["_csrf_token"] = token
        return token

    def rotate_csrf_token():
        session["_csrf_token"] = secrets.token_urlsafe(32)
        return session["_csrf_token"]

    def allowed_query_params_for_current_endpoint():
        return ALLOWED_QUERY_PARAMS_BY_ENDPOINT.get(request.endpoint)

    def query_param_is_safe(key, value):
        max_length = QUERY_PARAM_MAX_LENGTHS.get(key, 120)
        return "<" not in str(value) and ">" not in str(value) and is_safe_input(value, max_length=max_length)

    def query_string(**updates):
        allowed_params = allowed_query_params_for_current_endpoint()
        args = {}
        for key, value in request.args.items():
            if allowed_params is not None and key not in allowed_params:
                continue
            if query_param_is_safe(key, value):
                args[key] = value

        for key, value in updates.items():
            if allowed_params is not None and key not in allowed_params:
                continue
            if value in (None, "", False):
                args.pop(key, None)
            elif query_param_is_safe(key, value):
                args[key] = value
        return urlencode(args)

    def query_string_for(key, value):
        return query_string(**{key: value})

    def auth_rate_limit_ip():
        client_ip = request.remote_addr or "unknown"
        if not app.config.get("AUTH_RATE_LIMIT_TRUST_PROXY_HEADERS"):
            return client_ip

        trusted_proxies = app.config.get("AUTH_RATE_LIMIT_TRUSTED_PROXIES", set())
        if client_ip not in trusted_proxies:
            return client_ip

        forwarded_for = request.headers.get("X-Forwarded-For", "")
        forwarded_ip = forwarded_for.split(",")[0].strip()
        return forwarded_ip or client_ip

    def auth_rate_limit_key():
        return f"{request.endpoint}:{auth_rate_limit_ip()}"

    def log_security_event(event, **details):
        app.logger.warning(
            "security_event=%s remote_addr=%s endpoint=%s method=%s path=%s details=%s",
            event,
            request.remote_addr,
            request.endpoint,
            request.method,
            request.path,
            details,
        )

    def auth_account_lockout_key(email):
        normalized_email = (email or "").strip().lower()
        if not normalized_email:
            return None
        secret_key = str(app.config["SECRET_KEY"]).encode("utf-8")
        digest = hmac_new(secret_key, normalized_email.encode("utf-8"), "sha256").hexdigest()
        return f"{request.endpoint}:account:{digest}"

    def prune_auth_attempts(key=None, window_seconds=None):
        cutoff = time() - (window_seconds or app.config.get("AUTH_RATE_LIMIT_WINDOW_SECONDS", 60))
        query = db.session.query(AuthAttempt).filter(AuthAttempt.attempted_at < cutoff)
        if key is not None:
            query = query.filter(AuthAttempt.key == key)
        query.delete(synchronize_session=False)

    def auth_attempt_count(key, window_seconds):
        prune_auth_attempts(key, window_seconds)
        attempt_count = db.session.query(AuthAttempt).filter(AuthAttempt.key == key).count()
        db.session.commit()
        return attempt_count

    def is_auth_rate_limited(email=None):
        key = auth_rate_limit_key()
        max_attempts = app.config.get(
            "AUTH_REGISTER_RATE_LIMIT_MAX_ATTEMPTS"
            if request.endpoint == "register"
            else "AUTH_RATE_LIMIT_MAX_ATTEMPTS",
            20 if request.endpoint == "register" else 5,
        )
        attempt_count = auth_attempt_count(key, app.config.get("AUTH_RATE_LIMIT_WINDOW_SECONDS", 60))
        if attempt_count >= max_attempts:
            return True

        account_key = auth_account_lockout_key(email)
        if not account_key:
            return False

        account_attempt_count = auth_attempt_count(
            account_key,
            app.config.get("AUTH_ACCOUNT_LOCKOUT_WINDOW_SECONDS", 15 * 60),
        )
        max_account_attempts = app.config.get(
            "AUTH_REGISTER_ACCOUNT_LOCKOUT_MAX_ATTEMPTS"
            if request.endpoint == "register"
            else "AUTH_ACCOUNT_LOCKOUT_MAX_ATTEMPTS",
            10 if request.endpoint == "register" else 5,
        )
        return account_attempt_count >= max_account_attempts

    def record_attempt(key):
        db.session.add(AuthAttempt(key=key, attempted_at=time()))

    def record_auth_failure(email=None):
        prune_auth_attempts(
            window_seconds=max(
                app.config.get("AUTH_RATE_LIMIT_WINDOW_SECONDS", 60),
                app.config.get("AUTH_ACCOUNT_LOCKOUT_WINDOW_SECONDS", 15 * 60),
            )
        )
        key = auth_rate_limit_key()
        prune_auth_attempts(key, app.config.get("AUTH_RATE_LIMIT_WINDOW_SECONDS", 60))
        record_attempt(key)

        account_key = auth_account_lockout_key(email)
        if account_key:
            prune_auth_attempts(account_key, app.config.get("AUTH_ACCOUNT_LOCKOUT_WINDOW_SECONDS", 15 * 60))
            record_attempt(account_key)

        db.session.commit()

    def clear_auth_failures(email=None):
        keys = {auth_rate_limit_key()}
        account_key = auth_account_lockout_key(email)
        if account_key:
            keys.add(account_key)
        db.session.query(AuthAttempt).filter(AuthAttempt.key.in_(keys)).delete(synchronize_session=False)
        db.session.commit()

    def reset_auth_rate_limits():
        db.session.query(AuthAttempt).delete(synchronize_session=False)
        db.session.commit()

    def validate_url_surface():
        if not is_safe_input(request.path, max_length=2048):
            log_security_event("invalid_path")
            abort(400)

        allowed_params = allowed_query_params_for_current_endpoint()
        if allowed_params is None:
            return

        for key, values in request.args.lists():
            if (
                key not in allowed_params
                or len(values) != 1
                or not is_safe_input(key, max_length=64, allow_path_separators=False)
            ):
                log_security_event("invalid_query_parameter", parameter=key)
                abort(400)

            value = values[0]
            if "<" in value or ">" in value or not query_param_is_safe(key, value):
                log_security_event("invalid_query_value", parameter=key)
                abort(400)

    @app.before_request
    def validate_url_and_query_parameters():
        validate_url_surface()

    @app.before_request
    def protect_against_csrf():
        if request.method in SAFE_METHODS:
            return

        fetch_site = request.headers.get("Sec-Fetch-Site", "").lower()
        if fetch_site == "cross-site":
            log_security_event("cross_site_post_blocked")
            abort(403)

        sent_token = request.form.get("csrf_token") or request.headers.get("X-CSRF-Token")
        expected_token = session.get("_csrf_token")
        if not sent_token or not expected_token or not secrets.compare_digest(sent_token, expected_token):
            log_security_event("csrf_validation_failed")
            abort(400)

    @app.after_request
    def set_security_headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        if request.endpoint == "static":
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
            response.headers.pop("Pragma", None)
            response.headers.pop("Expires", None)
        else:
            response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
        response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
        response.headers["Cross-Origin-Resource-Policy"] = "same-origin"
        response.headers["X-Permitted-Cross-Domain-Policies"] = "none"
        response.headers.pop("Server", None)
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        if app.config.get("SECURITY_HSTS_ENABLED"):
            response.headers["Strict-Transport-Security"] = (
                f"max-age={app.config.get('SECURITY_HSTS_MAX_AGE', 31536000)}; includeSubDomains"
            )
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "style-src 'self' https://cdn.jsdelivr.net; "
            "script-src 'self' https://cdn.jsdelivr.net; "
            "img-src 'self' data:; "
            "font-src 'self' https://cdn.jsdelivr.net; "
            "connect-src 'self'; "
            "object-src 'none'; "
            "base-uri 'self'; "
            "frame-ancestors 'none'; "
            "form-action 'self'"
        )
        if app.config.get("SESSION_COOKIE_SECURE"):
            response.headers["Content-Security-Policy"] += "; upgrade-insecure-requests"
        return response

    app.jinja_env.globals["csrf_token"] = generate_csrf_token
    app.jinja_env.globals["query_string"] = query_string
    app.jinja_env.globals["query_string_for"] = query_string_for
    app.extensions["security_tools"] = {
        "rotate_csrf_token": rotate_csrf_token,
        "is_auth_rate_limited": is_auth_rate_limited,
        "record_auth_failure": record_auth_failure,
        "clear_auth_failures": clear_auth_failures,
        "reset_auth_rate_limits": reset_auth_rate_limits,
    }

    with app.app_context():
        from models.favorite import Favorite
        from models.recipe import Recipe
        from models.search_activity import SearchActivity
        from models.user import User

        db.create_all()
        ensure_recipe_schema()
        if app.config.get("AUTO_BOOTSTRAP_DATA", True):
            from services.data_loader import bootstrap_recipe_data

            bootstrap_recipe_data(app.config["DATASET_PATH"])

    @app.errorhandler(SecurityError)
    def security_error(error):
        return (
            "<!doctype html><title>Bad Request</title>"
            "<h1>Bad Request</h1>"
            "<p>The request could not be processed.</p>"
        ), 400

    @app.errorhandler(400)
    def bad_request(error):
        return render_template(
            "error_view.html",
            title="Bad Request",
            status_code=400,
            message="The request could not be processed. Please review your input and try again.",
        ), 400

    @app.errorhandler(403)
    def forbidden(error):
        return render_template(
            "error_view.html",
            title="Access Denied",
            status_code=403,
            message="You do not have permission to access this page.",
        ), 403

    @app.errorhandler(404)
    def page_not_found(error):
        return render_template(
            "error_view.html",
            title="Page Not Found",
            status_code=404,
            message="The page you requested is unavailable or may have moved.",
        ), 404

    @app.errorhandler(405)
    def method_not_allowed(error):
        return render_template(
            "error_view.html",
            title="Method Not Allowed",
            status_code=405,
            message="This action is not available for the requested method.",
        ), 405

    @app.errorhandler(413)
    def request_entity_too_large(error):
        return render_template(
            "error_view.html",
            title="Request Too Large",
            status_code=413,
            message="The submitted data is too large. Please shorten your input and try again.",
        ), 413

    @app.errorhandler(429)
    def too_many_requests(error):
        return render_template(
            "error_view.html",
            title="Too Many Requests",
            status_code=429,
            message=getattr(error, "description", None)
            or "Too many requests were submitted. Please wait a moment and try again.",
        ), 429

    @app.errorhandler(SQLAlchemyError)
    def database_error(error):
        db.session.rollback()
        app.logger.error(
            "database_error endpoint=%s method=%s path=%s error_type=%s",
            request.endpoint,
            request.method,
            request.path,
            type(error).__name__,
        )
        return render_template(
            "error_view.html",
            title="Service Unavailable",
            status_code=500,
            message="The recipe service is temporarily unavailable. Please try again in a moment.",
        ), 500

    @app.errorhandler(500)
    def server_error(error):
        app.logger.error(
            "server_error endpoint=%s method=%s path=%s error_type=%s",
            request.endpoint,
            request.method,
            request.path,
            type(error).__name__,
        )
        return render_template(
            "error_view.html",
            title="Server Error",
            status_code=500,
            message="Something unexpected happened. Please try again shortly.",
        ), 500

    from routes import register_routes

    register_routes(app)

    return app


app = None if os.environ.get("COGNICOOK_SKIP_APP_BOOTSTRAP") == "1" else create_app()

if __name__ == "__main__":
    if app is None:
        app = create_app()
    app.run()
