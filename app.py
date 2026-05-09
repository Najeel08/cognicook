import os
import secrets
import shutil
import sqlite3
from pathlib import Path
from time import time
from urllib.parse import urlencode

from flask import Flask, abort, flash, redirect, render_template, request, session, url_for
from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError

from config import Config
from extensions import db, login_manager
from models.auth_attempt import AuthAttempt

SAFE_METHODS = {"GET", "HEAD", "OPTIONS", "TRACE"}


@event.listens_for(Engine, "connect")
def configure_sqlite_connection(dbapi_connection, connection_record):
    if isinstance(dbapi_connection, sqlite3.Connection):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=MEMORY")
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
        target.execute("PRAGMA journal_mode=MEMORY")
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
    legacy_database_file = app.config.get("LEGACY_DATABASE_FILE")
    if not database_file:
        return

    database_path = Path(database_file)
    database_path.parent.mkdir(parents=True, exist_ok=True)

    if not database_path.exists() and legacy_database_file:
        legacy_path = Path(legacy_database_file)
        if legacy_path.exists():
            shutil.copy2(legacy_path, database_path)

    if database_path.exists() and not sqlite_file_is_usable(database_path):
        recovered_path = choose_recovered_database_path(database_path)
        if not recovered_path.exists():
            try:
                recover_sqlite_file(database_path, recovered_path)
            except (RuntimeError, sqlite3.Error):
                recovered_path = choose_recovered_database_path(database_path)

        app.config["DATABASE_FILE"] = recovered_path.as_posix()
        app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{recovered_path.as_posix()}"


def create_app(config_object=Config):
    app = Flask(__name__)
    app.config.from_object(config_object)
    os.makedirs(app.instance_path, exist_ok=True)

    if app.config.get("REQUIRE_SECRET_KEY_FROM_ENV") and not app.config.get("SECRET_KEY_FROM_ENV"):
        raise RuntimeError("SECRET_KEY must be provided via the environment in production.")

    prepare_database_file(app)

    db.init_app(app)
    login_manager.init_app(app)
    login_manager.session_protection = "strong"

    @login_manager.unauthorized_handler
    def handle_unauthorized():
        flash("Please login to continue.", "warning")
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

    def query_string(**updates):
        args = request.args.to_dict(flat=True)
        for key, value in updates.items():
            if value in (None, "", False):
                args.pop(key, None)
            else:
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

    def prune_auth_attempts(key=None):
        cutoff = time() - app.config.get("AUTH_RATE_LIMIT_WINDOW_SECONDS", 60)
        query = db.session.query(AuthAttempt).filter(AuthAttempt.attempted_at < cutoff)
        if key is not None:
            query = query.filter(AuthAttempt.key == key)
        query.delete(synchronize_session=False)

    def is_auth_rate_limited():
        key = auth_rate_limit_key()
        max_attempts = app.config.get("AUTH_RATE_LIMIT_MAX_ATTEMPTS", 5)
        prune_auth_attempts(key)
        attempt_count = db.session.query(AuthAttempt).filter(AuthAttempt.key == key).count()
        db.session.commit()
        return attempt_count >= max_attempts

    def record_auth_failure():
        key = auth_rate_limit_key()
        prune_auth_attempts(key)
        db.session.add(AuthAttempt(key=key, attempted_at=time()))
        db.session.commit()

    def clear_auth_failures():
        key = auth_rate_limit_key()
        db.session.query(AuthAttempt).filter(AuthAttempt.key == key).delete(synchronize_session=False)
        db.session.commit()

    def reset_auth_rate_limits():
        db.session.query(AuthAttempt).delete(synchronize_session=False)
        db.session.commit()

    @app.before_request
    def protect_against_csrf():
        if request.method in SAFE_METHODS:
            return

        fetch_site = request.headers.get("Sec-Fetch-Site", "").lower()
        if fetch_site == "cross-site":
            abort(403)

        sent_token = request.form.get("csrf_token") or request.headers.get("X-CSRF-Token")
        expected_token = session.get("_csrf_token")
        if not sent_token or not expected_token or not secrets.compare_digest(sent_token, expected_token):
            abort(400)

    @app.after_request
    def set_security_headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
        response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
        response.headers["Cross-Origin-Resource-Policy"] = "same-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "style-src 'self' https://cdn.jsdelivr.net 'unsafe-inline'; "
            "script-src 'self' https://cdn.jsdelivr.net; "
            "img-src 'self' data:; "
            "font-src 'self' https://cdn.jsdelivr.net; "
            "connect-src 'self'; "
            "object-src 'none'; "
            "base-uri 'self'; "
            "frame-ancestors 'none'; "
            "form-action 'self'"
        )
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
        from models.user import User

        db.create_all()
        if app.config.get("AUTO_BOOTSTRAP_DATA", True):
            from services.data_loader import bootstrap_recipe_data

            bootstrap_recipe_data(app.config["DATASET_PATH"])

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
        return render_template(
            "error_view.html",
            title="Service Unavailable",
            status_code=500,
            message="The recipe service is temporarily unavailable. Please try again in a moment.",
        ), 500

    @app.errorhandler(500)
    def server_error(error):
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
