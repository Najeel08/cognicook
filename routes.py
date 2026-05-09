from urllib.parse import urlsplit

from flask import abort, current_app, flash, redirect, render_template, request, session, url_for
from flask_login import current_user, login_required, login_user, logout_user
from sqlalchemy.exc import IntegrityError

from extensions import db
from models.favorite import Favorite
from models.recipe import Recipe
from models.user import User
from services.recipe_service import (
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
    sanitize_choice,
    sanitize_text,
    validate_password,
)


def current_similar_filters():
    return {
        "diet": sanitize_choice(request.args.get("diet"), {"veg", "non_veg"}),
        "difficulty": sanitize_choice(request.args.get("difficulty"), {"easy", "medium", "hard"}),
        "sort": sanitize_choice(request.args.get("sort"), SIMILAR_SORT_OPTIONS) or "relevance",
    }


def get_safe_redirect_target(default_endpoint, **values):
    referrer = request.referrer
    if referrer:
        parsed = urlsplit(referrer)
        path_is_local = parsed.path.startswith("/") and not parsed.path.startswith("//")
        if parsed.scheme in {"http", "https"} and parsed.netloc == request.host and path_is_local:
            target = parsed.path
            if parsed.query:
                target = f"{target}?{parsed.query}"
            return target

    return url_for(default_endpoint, **values)


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


def register_routes(app):
    @app.route("/", methods=["GET", "POST"])
    def login():
        if current_user.is_authenticated:
            return redirect(url_for("dashboard"))

        if request.method == "POST":
            security_tools = current_app.extensions["security_tools"]
            if security_tools["is_auth_rate_limited"]():
                flash("Too many login attempts. Please wait a minute and try again.", "danger")
                abort(429, description="Too many login attempts. Please wait a minute and try again.")

            email = (request.form.get("email") or "").strip().lower()
            password = request.form.get("password") or ""

            user = User.query.filter_by(email=email).first()
            if user and user.check_password(password):
                security_tools["clear_auth_failures"]()
                session.clear()
                login_user(user)
                session.permanent = True
                security_tools["rotate_csrf_token"]()
                flash("Dashboard ready.", "success")
                return redirect(url_for("dashboard"))

            security_tools["record_auth_failure"]()
            flash("Invalid email or password.", "danger")

        return render_template("login_v2.html", title="Login")

    @app.route("/register", methods=["GET", "POST"])
    def register():
        if current_user.is_authenticated:
            return redirect(url_for("dashboard"))

        if request.method == "POST":
            username = sanitize_text(request.form.get("username"), max_length=30)
            email = (request.form.get("email") or "").strip().lower()
            password = request.form.get("password") or ""
            confirm_password = request.form.get("confirm_password") or ""

            errors = []

            if not is_valid_username(username):
                errors.append("Username must be 3 to 30 characters and may contain letters, numbers, dots, hyphens, or underscores.")

            if not is_valid_email(email):
                errors.append("Please enter a valid email address.")

            errors.extend(validate_password(password))

            if password != confirm_password:
                errors.append("Password confirmation does not match.")

            if User.query.filter_by(email=email).first():
                errors.append("Email already registered. Please use a different email address.")

            if errors:
                flash_errors(errors)
                return redirect(url_for("register"))

            user = User(name=username, email=email)
            user.set_password(password)

            db.session.add(user)
            try:
                db.session.commit()
            except IntegrityError:
                db.session.rollback()
                flash("Email already registered. Please use a different email address.", "danger")
                return redirect(url_for("register"))

            flash("Registration successful. Account created successfully. Please login.", "success")
            return redirect(url_for("login"))

        return render_template("register_v2.html", title="Register")

    @app.route("/dashboard", methods=["GET", "POST"])
    @login_required
    def dashboard():
        if request.method == "POST":
            ingredients_input = (request.form.get("ingredients") or "").strip()

            if len(ingredients_input) > 1000:
                flash("Ingredient list is too long.", "warning")
                return redirect(url_for("dashboard"))

            cleaned_ingredients = clean_ingredients(ingredients_input)
            if len(cleaned_ingredients) < 3:
                flash("Enter at least 3 ingredients to see recommendations.", "warning")
                return redirect(url_for("dashboard"))

            return redirect(url_for("recommendations", ingredients=ingredients_input))

        return render_template("dashboard_home.html", title="Dashboard")

    @app.route("/recommendations", methods=["GET"])
    @login_required
    def recommendations():
        ingredients_input = (request.args.get("ingredients") or "").strip()
        if not ingredients_input:
            flash("Enter at least 3 ingredients to see recommendations.", "warning")
            return redirect(url_for("dashboard"))

        normalized_ingredients = clean_ingredients(ingredients_input)
        if len(normalized_ingredients) < 3:
            flash("Please enter at least 3 valid ingredients to get suggestions.", "warning")
            return redirect(url_for("dashboard"))

        page = get_positive_int(request.args.get("page"), default=1, maximum=999)
        per_page = get_positive_int(
            request.args.get("per_page"),
            default=current_app.config["RESULTS_PER_PAGE"],
            maximum=current_app.config["MAX_PER_PAGE"],
        )

        recommendation_data = get_strict_recommendations(ingredients_input, page=page, per_page=per_page)
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
    @login_required
    def similar_recipes_page():
        ingredients_input = (request.args.get("ingredients") or "").strip()
        if not ingredients_input:
            flash("Enter at least 3 ingredients to see recommendations.", "warning")
            return redirect(url_for("dashboard"))

        normalized_ingredients = clean_ingredients(ingredients_input)
        if len(normalized_ingredients) < 3:
            flash("Please enter at least 3 valid ingredients to get suggestions.", "warning")
            return redirect(url_for("dashboard"))

        filters = current_similar_filters()
        page = get_positive_int(request.args.get("page"), default=1, maximum=999)
        per_page = get_positive_int(
            request.args.get("per_page"),
            default=current_app.config["RESULTS_PER_PAGE"],
            maximum=current_app.config["MAX_PER_PAGE"],
        )

        recommendation_data = get_similar_recommendations(
            ingredients_input,
            filters,
            page=page,
            per_page=per_page,
            max_missing=3,
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
        page = get_positive_int(request.args.get("page"), default=1, maximum=999)
        per_page = get_positive_int(
            request.args.get("per_page"),
            default=current_app.config["RESULTS_PER_PAGE"],
            maximum=current_app.config["MAX_PER_PAGE"],
        )

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
    @login_required
    def recipe_detail(recipe_id):
        recipe = db.get_or_404(Recipe, recipe_id)
        is_favorite = Favorite.query.filter_by(user_id=current_user.id, recipe_id=recipe.id).first() is not None
        return render_template(
            "recipe_view.html",
            title=recipe.title,
            recipe=recipe,
            is_favorite=is_favorite,
            back_url=get_safe_redirect_target("dashboard"),
        )

    @app.route("/logout", methods=["POST"])
    @login_required
    def logout():
        logout_user()
        session.clear()
        flash("You have been logged out successfully.", "success")
        return redirect(url_for("login"))
