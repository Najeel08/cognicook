import secrets
from urllib.parse import urlsplit
from time import time

from flask import abort, current_app, flash, redirect, render_template, request, session, url_for
from flask_login import current_user, login_required, login_user, logout_user
from sqlalchemy.exc import IntegrityError
from werkzeug.security import check_password_hash, generate_password_hash

from extensions import db
from models.favorite import Favorite
from models.recipe import Recipe
from models.search_activity import SearchActivity
from models.user import User
from services.recipe_service import (
    DIET_OPTIONS,
    DIFFICULTY_OPTIONS,
    SIMILAR_SORT_OPTIONS,
    get_filter_options,
    get_similar_recommendations,
    get_strict_recommendations,
)
from utils.ingredient_cleaner import clean_ingredients
from utils.pagination import paginate_list
from utils.validators import (
    get_positive_int,
    is_valid_email,
    is_valid_username,
    is_safe_input,
    sanitize_choice,
    validate_password,
)

MAX_INGREDIENT_INPUT_LENGTH = 1000
MAX_PASSWORD_INPUT_LENGTH = 256
DUMMY_PASSWORD_HASH = generate_password_hash(secrets.token_urlsafe(32))
INVALID_INGREDIENT_INPUT_MESSAGE = (
    "Invalid input: ingredients list must be under 1000 characters and cannot contain '<' or '>'."
)


def current_similar_filters():
    return {
        "diet": sanitize_choice(request.args.get("diet"), DIET_OPTIONS),
        "difficulty": sanitize_choice(request.args.get("difficulty"), DIFFICULTY_OPTIONS),
        "sort": sanitize_choice(request.args.get("sort"), SIMILAR_SORT_OPTIONS) or "relevance",
    }


def get_safe_redirect_target(default_endpoint, **values):
    referrer = request.referrer
    if referrer:
        parsed = urlsplit(referrer)
        path_is_local = parsed.path.startswith("/") and not parsed.path.startswith("//")
        path_is_safe = is_safe_input(parsed.path, max_length=2048)
        query_is_safe = is_safe_input(parsed.query, max_length=1200) and "<" not in parsed.query and ">" not in parsed.query
        if (
            parsed.scheme in {"http", "https"}
            and parsed.netloc == request.host
            and path_is_local
            and path_is_safe
            and query_is_safe
        ):
            target = parsed.path
            if parsed.query:
                target = f"{target}?{parsed.query}"
            return target

    return url_for(default_endpoint, **values)


def get_safe_return_path(value):
    if not value:
        return ""

    parsed = urlsplit(value)
    path_is_local = parsed.path.startswith("/") and not parsed.path.startswith("//")
    path_is_safe = is_safe_input(parsed.path, max_length=2048)
    query_is_safe = is_safe_input(parsed.query, max_length=1200) and "<" not in parsed.query and ">" not in parsed.query
    if parsed.scheme or parsed.netloc or not path_is_local or not path_is_safe or not query_is_safe:
        return ""

    target = parsed.path
    if parsed.query:
        target = f"{target}?{parsed.query}"
    return target


def get_favorite_recipe_ids(recipe_ids):
    if not recipe_ids or not current_user.is_authenticated:
        return set()

    return {
        recipe_id
        for (recipe_id,) in db.session.query(Favorite.recipe_id)
        .filter(Favorite.user_id == current_user.id, Favorite.recipe_id.in_(recipe_ids))
        .all()
    }


def record_search_activity(ingredients_input, normalized_ingredients, result_count, page):
    if not current_user.is_authenticated or page != 1:
        return

    db.session.add(
        SearchActivity(
            user_id=current_user.id,
            ingredients=ingredients_input,
            normalized_ingredients=", ".join(normalized_ingredients),
            result_count=result_count,
            created_at=time(),
        )
    )
    db.session.commit()


def flash_errors(errors):
    for error in errors:
        flash(error, "danger")


def get_validated_ingredients(source):
    ingredients_input = (source.get("ingredients") or "").strip()
    if not is_safe_input(ingredients_input, max_length=MAX_INGREDIENT_INPUT_LENGTH) or "<" in ingredients_input or ">" in ingredients_input:
        return None
    return ingredients_input


def validate_search_request(source):
    ingredients_input = get_validated_ingredients(source)
    if ingredients_input is None:
        flash(INVALID_INGREDIENT_INPUT_MESSAGE, "warning")
        return None, []

    if not ingredients_input:
        flash("Enter at least one ingredient to see recommendations.", "warning")
        return None, []

    normalized_ingredients = clean_ingredients(ingredients_input)
    if not normalized_ingredients:
        flash("Please enter at least one valid ingredient to get suggestions.", "warning")
        return None, []

    return ingredients_input, normalized_ingredients


def get_pagination_args():
    page = get_positive_int(request.args.get("page"), default=1, maximum=999)
    per_page = get_positive_int(
        request.args.get("per_page"),
        default=current_app.config["RESULTS_PER_PAGE"],
        maximum=current_app.config["MAX_PER_PAGE"],
    )
    return page, per_page


def register_routes(app):
    @app.route("/", methods=["GET", "POST"])
    def login():
        if current_user.is_authenticated:
            return redirect(url_for("dashboard"))

        if request.method == "POST":
            security_tools = current_app.extensions["security_tools"]
            email = (request.form.get("email") or "").strip().lower()
            password = request.form.get("password") or ""

            if security_tools["is_auth_rate_limited"](email):
                flash("Too many login attempts. Please wait a minute and try again.", "danger")
                abort(429, description="Too many login attempts. Please wait a minute and try again.")

            if (
                not is_safe_input(email, max_length=254, allow_path_separators=False)
                or not is_valid_email(email)
                or len(password) > MAX_PASSWORD_INPUT_LENGTH
            ):
                security_tools["record_auth_failure"](email)
                flash("Invalid email or password.", "danger")
                return render_template("login_v2.html", title="Login")

            user = User.query.filter_by(email=email).first()
            password_matches = (
                user.check_password(password)
                if user
                else check_password_hash(DUMMY_PASSWORD_HASH, password)
            )
            if user and password_matches:
                security_tools["clear_auth_failures"](email)
                session.clear()
                login_user(user)
                session.permanent = True
                security_tools["rotate_csrf_token"]()
                flash("Dashboard ready.", "success")
                return redirect(url_for("dashboard"))

            security_tools["record_auth_failure"](email)
            flash("Invalid email or password.", "danger")

        return render_template("login_v2.html", title="Login")

    @app.route("/register", methods=["GET", "POST"])
    def register():
        if current_user.is_authenticated:
            return redirect(url_for("dashboard"))

        if request.method == "POST":
            security_tools = current_app.extensions["security_tools"]
            username = " ".join((request.form.get("username") or "").strip().split())
            email = (request.form.get("email") or "").strip().lower()
            password = request.form.get("password") or ""
            confirm_password = request.form.get("confirm_password") or ""

            if security_tools["is_auth_rate_limited"](email):
                flash("Too many registration attempts. Please wait a minute and try again.", "danger")
                abort(429, description="Too many registration attempts. Please wait a minute and try again.")

            errors = []

            if (
                not is_safe_input(username, max_length=30, allow_path_separators=False)
                or not is_valid_username(username)
            ):
                errors.append("Username must be 3 to 30 characters and may contain letters, numbers, dots, hyphens, or underscores.")

            if not is_valid_email(email):
                errors.append("Please enter a valid email address.")
            elif not is_safe_input(email, max_length=254, allow_path_separators=False):
                errors.append("Please enter a valid email address.")

            errors.extend(validate_password(password))

            if len(password) > MAX_PASSWORD_INPUT_LENGTH:
                errors.append("Password is too long.")

            if password != confirm_password:
                errors.append("Password confirmation does not match.")

            if User.query.filter_by(email=email).first():
                errors.append(
                    "Registration could not be completed. Use a different email address or sign in if you already have an account."
                )

            if errors:
                security_tools["record_auth_failure"](email)
                flash_errors(errors)
                return redirect(url_for("register"))

            user = User(name=username, email=email)
            user.set_password(password)

            db.session.add(user)
            try:
                db.session.commit()
            except IntegrityError:
                db.session.rollback()
                security_tools["record_auth_failure"](email)
                flash(
                    "Registration could not be completed. Use a different email address or sign in if you already have an account.",
                    "danger",
                )
                return redirect(url_for("register"))

            security_tools["clear_auth_failures"](email)
            flash("Registration successful. Account created successfully. Please log in.", "success")
            return redirect(url_for("login"))

        return render_template("register_v2.html", title="Register")

    @app.route("/dashboard", methods=["GET", "POST"])
    def dashboard():
        if request.method == "POST":
            ingredients_input = get_validated_ingredients(request.form)
            if ingredients_input is None:
                flash(INVALID_INGREDIENT_INPUT_MESSAGE, "warning")
                return redirect(url_for("dashboard"))

            cleaned_ingredients = clean_ingredients(ingredients_input)
            if not cleaned_ingredients:
                flash("Enter at least one valid ingredient to see recommendations.", "warning")
                return redirect(url_for("dashboard"))

            return redirect(url_for("recommendations", ingredients=ingredients_input))

        return render_template("dashboard_home.html", title="Dashboard")

    @app.route("/recommendations", methods=["GET"])
    def recommendations():
        ingredients_input, normalized_ingredients = validate_search_request(request.args)
        if ingredients_input is None:
            return redirect(url_for("dashboard"))

        page, per_page = get_pagination_args()

        recommendation_data = get_strict_recommendations(ingredients_input, page=page, per_page=per_page)
        record_search_activity(
            ingredients_input,
            recommendation_data["ingredients"],
            recommendation_data["strict"].total,
            page,
        )
        recipe_ids = {recipe.id for recipe in recommendation_data["strict"].items}
        favorite_recipe_ids = get_favorite_recipe_ids(recipe_ids)

        return render_template(
            "recommendations.html",
            title="Recommendations",
            strict_pagination=recommendation_data["strict"],
            ingredients=recommendation_data["ingredients"],
            ingredients_text=recommendation_data["ingredients_text"],
            favorite_recipe_ids=favorite_recipe_ids,
            per_page=per_page,
        )

    @app.route("/similar", methods=["GET"])
    def similar_recipes_page():
        ingredients_input, normalized_ingredients = validate_search_request(request.args)
        if ingredients_input is None:
            return redirect(url_for("dashboard"))

        filters = current_similar_filters()
        page, per_page = get_pagination_args()

        recommendation_data = get_similar_recommendations(
            ingredients_input,
            filters,
            page=page,
            per_page=per_page,
            max_missing=5,
        )

        recipe_ids = {item["recipe"].id for item in recommendation_data["similar"].items}
        favorite_recipe_ids = get_favorite_recipe_ids(recipe_ids)

        return render_template(
            "similar_recipes.html",
            title="Similar Recipes",
            filters=filters,
            filter_options=get_filter_options(),
            similar_pagination=recommendation_data["similar"],
            ingredients=recommendation_data["ingredients"],
            ingredients_text=recommendation_data["ingredients_text"],
            favorite_recipe_ids=favorite_recipe_ids,
            per_page=per_page,
        )

    @app.route("/favorites", methods=["GET"])
    @login_required
    def favorites():
        page, per_page = get_pagination_args()

        favorite_recipes = (
            Recipe.query.join(Favorite, Favorite.recipe_id == Recipe.id)
            .filter(Favorite.user_id == current_user.id)
            .order_by(Recipe.title.asc())
            .all()
        )
        favorites_pagination = paginate_list(favorite_recipes, page, per_page)

        return render_template(
            "favorite_list.html",
            title="Favorites",
            favorites_pagination=favorites_pagination,
            per_page=per_page,
        )

    @app.route("/activity", methods=["GET"])
    @login_required
    def activity_summary():
        page, per_page = get_pagination_args()

        favorite_count = Favorite.query.filter_by(user_id=current_user.id).count()
        activities = (
            SearchActivity.query.filter_by(user_id=current_user.id)
            .order_by(SearchActivity.created_at.desc())
            .all()
        )
        activity_pagination = paginate_list(activities, page, per_page)

        return render_template(
            "activity_summary.html",
            title="Activity Summary",
            activity_pagination=activity_pagination,
            search_count=len(activities),
            favorite_count=favorite_count,
            per_page=per_page,
        )

    @app.route("/favorite/<int:recipe_id>", methods=["POST"])
    @login_required
    def favorite(recipe_id):
        recipe = db.session.get(Recipe, recipe_id)
        if recipe is None:
            abort(404)

        exists = Favorite.query.filter_by(user_id=current_user.id, recipe_id=recipe_id).first()
        if exists:
            db.session.delete(exists)
            db.session.commit()
            flash(f"{recipe.title} was removed from favorites.", "success")
        else:
            db.session.add(Favorite(user_id=current_user.id, recipe_id=recipe_id))
            try:
                db.session.commit()
                flash(f"{recipe.title} was saved to favorites.", "success")
            except IntegrityError:
                db.session.rollback()
                flash("This recipe is already in your favorites.", "info")

        return redirect(get_safe_redirect_target("favorites"))

    @app.route("/favorite/<int:recipe_id>/remove", methods=["POST"])
    @login_required
    def remove_favorite(recipe_id):
        favorite_item = Favorite.query.filter_by(user_id=current_user.id, recipe_id=recipe_id).first()
        if favorite_item is None:
            flash("Favorite recipe not found.", "warning")
            return redirect(url_for("favorites"))

        db.session.delete(favorite_item)
        db.session.commit()
        flash("Recipe removed from favorites.", "success")
        return redirect(get_safe_redirect_target("favorites"))

    @app.route("/recipe/<int:recipe_id>")
    def recipe_detail(recipe_id):
        recipe = db.get_or_404(Recipe, recipe_id)
        is_favorite = (
            current_user.is_authenticated
            and Favorite.query.filter_by(user_id=current_user.id, recipe_id=recipe.id).first() is not None
        )
        return render_template(
            "recipe_view.html",
            title=recipe.title,
            recipe=recipe,
            is_favorite=is_favorite,
            back_url=get_safe_return_path(request.args.get("next")) or get_safe_redirect_target("dashboard"),
        )

    @app.route("/logout", methods=["POST"])
    @login_required
    def logout():
        logout_user()
        session.clear()
        flash("You have been logged out successfully.", "success")
        return redirect(url_for("login"))
