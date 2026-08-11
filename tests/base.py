import os
import unittest

os.environ["COGNICOOK_SKIP_APP_BOOTSTRAP"] = "1"

from pathlib import Path
import re

from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.pool import StaticPool

from app import create_app
from config import BASE_DIR, resolve_project_path
from extensions import db
from models.favorite import Favorite
from models.recipe import Recipe
from models.user import User
from services.data_loader import bootstrap_recipe_data, load_dataset_rows, normalize_instructions, normalize_row, replace_recipe_rows
from services.recipe_service import (
    get_ingredient_vocabulary,
    get_similar_recommendations,
    get_strict_recommendations,
    parse_ingredient_query,
    sort_similar_matches,
)
from utils.ingredient_cleaner import clean_ingredients
from utils.ingredient_measurements import parse_ingredient_measurements
from utils.instructions import split_instruction_block
from utils.pagination import paginate_list


class CogniCookTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        class TestConfig:
            TESTING = True
            SECRET_KEY = "test-secret-key"
            SQLALCHEMY_DATABASE_URI = "sqlite://"
            SQLALCHEMY_TRACK_MODIFICATIONS = False
            SQLALCHEMY_ENGINE_OPTIONS = {
                "connect_args": {"check_same_thread": False},
                "poolclass": StaticPool,
            }
            SESSION_COOKIE_HTTPONLY = True
            SESSION_COOKIE_SAMESITE = "Lax"
            SESSION_COOKIE_SECURE = False
            REMEMBER_COOKIE_HTTPONLY = True
            REMEMBER_COOKIE_SAMESITE = "Lax"
            REMEMBER_COOKIE_SECURE = False
            MAX_CONTENT_LENGTH = 1024 * 1024
            RESULTS_PER_PAGE = 2
            MAX_PER_PAGE = 10
            AUTH_ACCOUNT_LOCKOUT_WINDOW_SECONDS = 15 * 60
            AUTH_ACCOUNT_LOCKOUT_MAX_ATTEMPTS = 5
            AUTO_BOOTSTRAP_DATA = False
            TRUSTED_HOSTS = None

        cls.app = create_app(TestConfig)

    @classmethod
    def tearDownClass(cls):
        with cls.app.app_context():
            db.session.remove()
            db.engine.dispose()

    def setUp(self):
        self.client = self.app.test_client()
        with self.app.app_context():
            self.app.extensions["security_tools"]["reset_auth_rate_limits"]()
            db.drop_all()
            db.create_all()
            db.session.add_all(
                [
                    Recipe(
                        title="Simple Curry",
                        ingredients="onion,tomato,potato,salt,oil",
                        instructions="Cook everything together.",
                        diet_type="veg",
                        difficulty="easy",
                        cooking_time=20,
                    ),
                    Recipe(
                        title="Paneer Masala",
                        ingredients="onion,tomato,paneer,salt,oil",
                        instructions="Cook paneer in masala.",
                        diet_type="veg",
                        difficulty="medium",
                        cooking_time=25,
                    ),
                    Recipe(
                        title="Tomato Rice",
                        ingredients="rice,tomato,onion,salt,oil",
                        instructions="Cook rice and mix with tomato masala.",
                        diet_type="veg",
                        difficulty="easy",
                        cooking_time=18,
                    ),
                    Recipe(
                        title="Dal Fry",
                        ingredients="onion,tomato,lentil,cumin,salt,oil",
                        instructions="Cook lentils and temper with spices.",
                        diet_type="veg",
                        difficulty="medium",
                        cooking_time=30,
                    ),
                    Recipe(
                        title="Vegetable Korma",
                        ingredients="onion,tomato,potato,paneer,cream,cashew,salt,oil",
                        instructions="Cook vegetables in rich gravy.",
                        diet_type="veg",
                        difficulty="hard",
                        cooking_time=40,
                    ),
                    Recipe(
                        title="Masala Omelette",
                        ingredients="egg,onion,tomato,green chilli,salt,oil",
                        instructions="Whisk eggs and cook with vegetables.",
                        diet_type="non_veg",
                        difficulty="easy",
                        cooking_time=10,
                    ),
                ]
            )
            db.session.commit()

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()

    def get_csrf_token(self, path="/login"):
        self.client.get(path)
        with self.client.session_transaction() as session:
            return session["_csrf_token"]

    def register_user(self, username="tester_user", email="tester@example.com", password="SecurePass8"):
        token = self.get_csrf_token("/register")
        return self.client.post(
            "/register",
            data={
                "username": username,
                "email": email,
                "password": password,
                "confirm_password": password,
                "csrf_token": token,
            },
            follow_redirects=True,
        )

    def create_user(self, username="tester_user", email="tester@example.com", password="SecurePass8"):
        with self.app.app_context():
            user = User(name=username, email=email)
            user.set_password(password)
            db.session.add(user)
            db.session.commit()
            return user.id

    def logout_user(self):
        token = self.get_csrf_token("/dashboard")
        return self.client.post("/logout", data={"csrf_token": token}, follow_redirects=True)

    def login_user(self, username="tester_user", password="SecurePass8"):
        token = self.get_csrf_token("/login")
        return self.client.post(
            "/login",
            data={"username": username, "password": password, "csrf_token": token},
            follow_redirects=True,
        )
