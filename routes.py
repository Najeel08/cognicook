import secrets
from urllib.parse import urlsplit

from flask import abort, current_app, flash, redirect, render_template, request, session, url_for
from flask_login import current_user, login_required, login_user, logout_user
from sqlalchemy.exc import IntegrityError
from werkzeug.security import check_password_hash, generate_password_hash

from extensions import db
from models.favorite import Favorite
from models.recipe import Recipe
from models.user import User
from services.recipe_service import (
    DIET_OPTIONS,
    DIFFICULTY_OPTIONS,
    SIMILAR_SORT_OPTIONS,
    entered_user_ingredient_set,
    get_filter_options,
    get_similar_recommendations,
    get_strict_recommendations,
)
from utils.ingredient_cleaner import clean_ingredients
from utils.pagination import paginate_query
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
MAX_SAVE_RECIPE_ID_LENGTH = 10
MIN_SEARCH_INGREDIENTS = 3
DUMMY_PASSWORD_HASH = generate_password_hash(secrets.token_urlsafe(32))
INVALID_INGREDIENT_INPUT_MESSAGE = (
    "Invalid input: ingredients list must be under 1000 characters and cannot contain '<' or '>'."
)
MIN_SEARCH_INGREDIENTS_MESSAGE = (
    "Enter at least 3 valid ingredients besides salt, sugar, or water to see recommendations."
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
        path_is_local = (
            parsed.path.startswith("/")
            and not parsed.path.startswith("//")
            and "\\" not in parsed.path
        )
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
    path_is_local = (
        parsed.path.startswith("/")
        and not parsed.path.startswith("//")
        and "\\" not in parsed.path
    )
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


def flash_errors(errors):
    for error in errors:
        flash(error, "danger")


def create_login_session(user, security_tools):
    session.clear()
    login_user(user)
    session.permanent = True
    security_tools["rotate_csrf_token"]()


def auto_save_recipe_after_login(form, saved_message=None):
    save_recipe_id = form.get("save_recipe", "").strip()
    next_url = get_safe_return_path(form.get("next", "").strip())
    if (
        not save_recipe_id
        or len(save_recipe_id) > MAX_SAVE_RECIPE_ID_LENGTH
        or not save_recipe_id.isdigit()
    ):
        return next_url or url_for("dashboard")
    try:
        recipe_id = int(save_recipe_id)
    except ValueError:
        return next_url or url_for("dashboard")
    recipe = db.session.get(Recipe, recipe_id)
    if recipe is None:
        return next_url or url_for("dashboard")
    exists = Favorite.query.filter_by(user_id=current_user.id, recipe_id=recipe_id).first()
    if exists:
        flash(f"{recipe.title} is already saved to your favorites.", "info")
    else:
        db.session.add(Favorite(user_id=current_user.id, recipe_id=recipe_id))
        try:
            db.session.commit()
            flash(saved_message or f"{recipe.title} was saved to favorites.", "success")
        except IntegrityError:
            db.session.rollback()
            flash("This recipe is already in your favorites.", "info")
    return next_url or url_for("dashboard")


def get_validated_ingredients(source):
    ingredients_input = (source.get("ingredients") or "").strip()
    if not is_safe_input(ingredients_input, max_length=MAX_INGREDIENT_INPUT_LENGTH) or "<" in ingredients_input or ">" in ingredients_input:
        return None
    return ingredients_input


def validate_search_request(
    source,
    empty_message="Enter at least one ingredient to see recommendations.",
    no_valid_message="Please enter at least one valid ingredient to get suggestions.",
):
    ingredients_input = get_validated_ingredients(source)
    if ingredients_input is None:
        flash(INVALID_INGREDIENT_INPUT_MESSAGE, "warning")
        return None

    if not ingredients_input:
        flash(empty_message, "warning")
        return None

    normalized_ingredients = clean_ingredients(ingredients_input)
    if not normalized_ingredients:
        flash(no_valid_message, "warning")
        return None

    if len(entered_user_ingredient_set(normalized_ingredients)) < MIN_SEARCH_INGREDIENTS:
        flash(MIN_SEARCH_INGREDIENTS_MESSAGE, "warning")
        return None

    return ingredients_input


def get_pagination_args():
    page = get_positive_int(request.args.get("page"), default=1, maximum=999)
    per_page = get_positive_int(
        request.args.get("per_page"),
        default=current_app.config["RESULTS_PER_PAGE"],
        maximum=current_app.config["MAX_PER_PAGE"],
    )
    return page, per_page


def register_routes(app):
    @app.route("/", methods=["GET"])
    def landing():
        return redirect(url_for("dashboard"))

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if current_user.is_authenticated:
            return redirect(url_for("dashboard"))

        if request.method == "POST":
            security_tools = current_app.extensions["security_tools"]
            username = " ".join((request.form.get("username") or "").strip().split())
            password = request.form.get("password") or ""
            rate_limit_key = username.casefold()

            if security_tools["is_auth_rate_limited"](rate_limit_key):
                flash("Too many login attempts. Please wait a minute and try again.", "danger")
                abort(429, description="Too many login attempts. Please wait a minute and try again.")

            if (
                not is_safe_input(username, max_length=30, allow_path_separators=False)
                or not is_valid_username(username)
            ):
                security_tools["record_auth_failure"](rate_limit_key)
                flash("Invalid username or password.", "danger")
                return render_template("login_v2.html", title="Login",
                    save_recipe=request.form.get("save_recipe", ""),
                    next_url=request.form.get("next", ""))

            if len(password) > MAX_PASSWORD_INPUT_LENGTH:
                security_tools["record_auth_failure"](rate_limit_key)
                flash("Invalid username or password.", "danger")
                return render_template("login_v2.html", title="Login",
                    save_recipe=request.form.get("save_recipe", ""),
                    next_url=request.form.get("next", ""))

            user = User.query.filter(db.func.lower(User.name) == username.casefold()).first()
            password_matches = (
                user.check_password(password)
                if user
                else check_password_hash(DUMMY_PASSWORD_HASH, password)
            )
            if user and password_matches:
                security_tools["clear_auth_failures"](rate_limit_key)
                create_login_session(user, security_tools)
                flash(f"Welcome, {user.username}", "success")
                redirect_url = auto_save_recipe_after_login(request.form)
                return redirect(redirect_url)

            security_tools["record_auth_failure"](rate_limit_key)
            flash("Invalid username or password.", "danger")

        return render_template("login_v2.html", title="Login",
            save_recipe=request.args.get("save_recipe", ""),
            next_url=request.args.get("next", ""))

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

            if User.query.filter(db.func.lower(User.name) == username.casefold()).first():
                errors.append("Username not available.")

            if User.query.filter(db.func.lower(User.email) == email).first():
                errors.append("Email address already in use. Please log in instead.")

            if errors:
                security_tools["record_auth_failure"](email)
                flash_errors(errors)
                return render_template("register_v2.html", title="Register",
                    save_recipe=request.form.get("save_recipe", ""),
                    next_url=request.form.get("next", ""))

            user = User(name=username, email=email)
            user.set_password(password)

            db.session.add(user)
            try:
                db.session.commit()
            except IntegrityError:
                db.session.rollback()
                security_tools["record_auth_failure"](email)
                if User.query.filter(db.func.lower(User.name) == username.casefold()).first():
                    flash("Username not available.", "danger")
                elif User.query.filter(db.func.lower(User.email) == email).first():
                    flash("Email address already in use. Please log in instead.", "danger")
                else:
                    flash("Registration could not be completed. Please try again.", "danger")
                return render_template("register_v2.html", title="Register",
                    save_recipe=request.form.get("save_recipe", ""),
                    next_url=request.form.get("next", ""))

            security_tools["clear_auth_failures"](email)
            create_login_session(user, security_tools)
            if request.form.get("save_recipe"):
                redirect_url = auto_save_recipe_after_login(
                    request.form,
                    saved_message="Account created successfully! Your recipe has been added to your favourites.",
                )
                return redirect(redirect_url)
            flash("Account created successfully!", "success")
            redirect_url = auto_save_recipe_after_login(request.form)
            return redirect(redirect_url)

        return render_template("register_v2.html", title="Register",
            save_recipe=request.args.get("save_recipe", ""),
            next_url=request.args.get("next", ""))

    @app.route("/dashboard", methods=["GET", "POST"])
    def dashboard():
        if request.method == "POST":
            ingredients_input = validate_search_request(
                request.form,
                empty_message="Enter at least one valid ingredient to see recommendations.",
                no_valid_message="Enter at least one valid ingredient to see recommendations.",
            )
            if ingredients_input is None:
                return redirect(url_for("dashboard"))

            return redirect(url_for("recommendations", ingredients=ingredients_input))

        return render_template("dashboard_home.html", title="Dashboard")

    @app.route("/recommendations", methods=["GET"])
    def recommendations():
        ingredients_input = validate_search_request(request.args)
        if ingredients_input is None:
            return redirect(url_for("dashboard"))

        page, per_page = get_pagination_args()
        diet = sanitize_choice(request.args.get("diet"), DIET_OPTIONS)
        difficulty = sanitize_choice(request.args.get("difficulty"), DIFFICULTY_OPTIONS)

        recommendation_data = get_strict_recommendations(
            ingredients_input, page=page, per_page=per_page,
            diet=diet, difficulty=difficulty,
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
            filters={"diet": diet, "difficulty": difficulty},
            filter_options=get_filter_options(),
        )

    @app.route("/similar", methods=["GET"])
    def similar_recipes_page():
        ingredients_input = validate_search_request(request.args)
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
        diet = sanitize_choice(request.args.get("diet"), DIET_OPTIONS)
        difficulty = sanitize_choice(request.args.get("difficulty"), DIFFICULTY_OPTIONS)

        favorite_recipes = (
            Recipe.query.join(Favorite, Favorite.recipe_id == Recipe.id)
            .filter(Favorite.user_id == current_user.id)
        )
        if diet:
            favorite_recipes = favorite_recipes.filter(Recipe.diet_type == diet)
        if difficulty:
            favorite_recipes = favorite_recipes.filter(Recipe.difficulty == difficulty)

        favorite_recipes = favorite_recipes.order_by(Recipe.title.asc())
        favorites_pagination = paginate_query(favorite_recipes, page, per_page)

        return render_template(
            "favorite_list.html",
            title="Favorites",
            favorites_pagination=favorites_pagination,
            per_page=per_page,
            filters={"diet": diet, "difficulty": difficulty},
            filter_options=get_filter_options(),
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
