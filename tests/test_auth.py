from tests.base import (
    CogniCookTestCase,
    db,
    Favorite,
    Recipe,
    User,
)


class TestAuth(CogniCookTestCase):
    def test_register_requires_csrf(self):
        response = self.client.post(
            "/register",
            data={"username": "tester_user", "email": "tester@example.com", "password": "SecurePass8"},
        )
        self.assertEqual(response.status_code, 400)

    def test_register_validates_email_username_and_password_strength(self):
        response = self.register_user(email="invalid-email")
        self.assertIn("Please enter a valid email address.", response.get_data(as_text=True))

        response = self.register_user(email="user@domain.c")
        self.assertIn("Please enter a valid email address.", response.get_data(as_text=True))

        response = self.register_user(email=".user@example.com")
        self.assertIn("Please enter a valid email address.", response.get_data(as_text=True))

        response = self.register_user(email="amban@gmail.co")
        self.assertIn("Please enter a valid email address.", response.get_data(as_text=True))

        response = self.register_user(username="ab", email="another@example.com")
        self.assertIn("Username must be 3 to 30 characters", response.get_data(as_text=True))

        response = self.register_user(password="weakpass")
        text = response.get_data(as_text=True)
        self.assertIn("Password must include at least one uppercase letter.", text)
        self.assertIn("Password must include at least one number.", text)

        response = self.register_user(password="AAAA1111")
        self.assertIn("Password cannot contain simple repeated sequences", response.get_data(as_text=True))

        response = self.register_user(password="Abcd1234")
        self.assertIn("Password cannot contain obvious sequential patterns", response.get_data(as_text=True))

        response = self.register_user(password="Safe9876Pass")
        self.assertIn("Password cannot contain obvious sequential patterns", response.get_data(as_text=True))

        response = self.register_user(password="Password123")
        self.assertIn("Password is too common", response.get_data(as_text=True))

        response = self.register_user(email="person@example.co")
        self.assertIn("Account created successfully!", response.get_data(as_text=True))
        self.assertIn("Logout", response.get_data(as_text=True))

    def test_register_rejects_mismatched_confirmation_and_unavailable_identity(self):
        token = self.get_csrf_token("/register")
        response = self.client.post(
            "/register",
            data={
                "username": "tester_user",
                "email": "tester@example.com",
                "password": "SecurePass8",
                "confirm_password": "SecurePass9",
                "csrf_token": token,
            },
            follow_redirects=True,
        )
        self.assertIn("Password confirmation does not match.", response.get_data(as_text=True))
        self.assertNotIn("Logout", response.get_data(as_text=True))
        self.assertEqual(self.client.get("/favorites", follow_redirects=False).status_code, 302)

        self.create_user()

        response = self.register_user(username="second_user")
        self.assertIn(
            "Email address already in use. Please log in instead.",
            response.get_data(as_text=True),
        )

        response = self.register_user(username="TESTER_USER", email="second@example.com")
        self.assertIn("Username not available.", response.get_data(as_text=True))

    def test_register_rejects_overlong_username_without_truncating(self):
        response = self.register_user(username="a" * 31)
        self.assertIn("Username must be 3 to 30 characters", response.get_data(as_text=True))

        with self.app.app_context():
            self.assertIsNone(User.query.filter_by(email="tester@example.com").first())

    def test_registration_rate_limit_blocks_repeated_invalid_submissions(self):
        original_ip_limit = self.app.config.get("AUTH_REGISTER_RATE_LIMIT_MAX_ATTEMPTS")
        original_account_limit = self.app.config.get("AUTH_REGISTER_ACCOUNT_LOCKOUT_MAX_ATTEMPTS")
        self.app.config["AUTH_REGISTER_RATE_LIMIT_MAX_ATTEMPTS"] = 2
        self.app.config["AUTH_REGISTER_ACCOUNT_LOCKOUT_MAX_ATTEMPTS"] = 2
        try:
            for _ in range(2):
                response = self.register_user(email="invalid-email")
                self.assertEqual(response.status_code, 200)

            response = self.register_user(email="invalid-email")
            self.assertEqual(response.status_code, 429)
            self.assertIn("Too many registration attempts", response.get_data(as_text=True))
        finally:
            if original_ip_limit is None:
                self.app.config.pop("AUTH_REGISTER_RATE_LIMIT_MAX_ATTEMPTS", None)
            else:
                self.app.config["AUTH_REGISTER_RATE_LIMIT_MAX_ATTEMPTS"] = original_ip_limit
            if original_account_limit is None:
                self.app.config.pop("AUTH_REGISTER_ACCOUNT_LOCKOUT_MAX_ATTEMPTS", None)
            else:
                self.app.config["AUTH_REGISTER_ACCOUNT_LOCKOUT_MAX_ATTEMPTS"] = original_account_limit

    def test_register_and_login_flow_uses_expected_success_message(self):
        response = self.register_user(email="USER@Example.com")
        registration_text = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn("Account created successfully!", registration_text)
        self.assertIn("Search Recipes", registration_text)
        self.assertIn("Logout", registration_text)
        self.assertNotIn("Welcome Back", registration_text)

        self.logout_user()

        response = self.login_user(username="tester@example.com")
        self.assertIn("Invalid username or password.", response.get_data(as_text=True))

        response = self.login_user()
        text = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn("Welcome, tester_user", text)
        self.assertIn("Search Recipes", text)
        self.assertNotIn("Recipe Explorer", text)

        with self.app.app_context():
            user = User.query.filter_by(email="user@example.com").first()
            self.assertIsNotNone(user)
            self.assertEqual(user.username, "tester_user")

    def test_register_from_login_to_save_auto_logs_in_saves_and_returns(self):
        next_url = "/recommendations?ingredients=onion,tomato,potato,oil"
        token = self.get_csrf_token(f"/register?save_recipe=1&next={next_url}")

        response = self.client.post(
            "/register",
            data={
                "username": "save_user",
                "email": "save@example.com",
                "password": "SecurePass8",
                "confirm_password": "SecurePass8",
                "save_recipe": "1",
                "next": next_url,
                "csrf_token": token,
            },
            follow_redirects=True,
        )
        text = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn("Account created successfully! Your recipe has been added to your favorites.", text)
        self.assertIn("Exact Recipe Matches", text)
        self.assertIn(">Remove<", text)
        self.assertIn("Logout", text)
        with self.app.app_context():
            self.assertEqual(User.query.filter_by(email="save@example.com").count(), 1)
            self.assertEqual(db.session.query(Recipe).filter_by(id=1).count(), 1)
            user = User.query.filter_by(email="save@example.com").one()
            self.assertEqual(Favorite.query.filter_by(user_id=user.id, recipe_id=1).count(), 1)

    def test_register_with_unsafe_pending_next_uses_normal_dashboard_redirect(self):
        token = self.get_csrf_token("/register?save_recipe=1&next=https%3A%2F%2Fevil.example")

        response = self.client.post(
            "/register",
            data={
                "username": "safe_redirect_user",
                "email": "safe-redirect@example.com",
                "password": "SecurePass8",
                "confirm_password": "SecurePass8",
                "save_recipe": "1",
                "next": "https://evil.example",
                "csrf_token": token,
            },
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers.get("Location"), "/dashboard")

    def test_login_rotates_csrf_token_after_authentication(self):
        self.create_user()
        original_token = self.get_csrf_token("/login")

        response = self.client.post(
            "/login",
            data={"username": "tester_user", "password": "SecurePass8", "csrf_token": original_token},
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 302)
        with self.client.session_transaction() as session:
            self.assertNotEqual(session["_csrf_token"], original_token)

    def test_login_ignores_overlong_save_recipe_without_server_error(self):
        self.create_user()
        token = self.get_csrf_token("/login")

        response = self.client.post(
            "/login",
            data={
                "username": "tester_user",
                "password": "SecurePass8",
                "save_recipe": "9" * 5000,
                "csrf_token": token,
            },
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers.get("Location"), "/dashboard")

    def test_auth_switch_links_preserve_pending_save_intent(self):
        response = self.client.get("/login?save_recipe=1&next=%2Frecipe%2F1")
        text = response.get_data(as_text=True)
        self.assertIn('href="/register?', text)
        self.assertIn("save_recipe=1", text)
        self.assertIn("next=/recipe/1", text)

        response = self.client.get("/register?save_recipe=1&next=%2Frecipe%2F1")
        text = response.get_data(as_text=True)
        self.assertIn('href="/login?', text)
        self.assertIn("save_recipe=1", text)
        self.assertIn("next=/recipe/1", text)

    def test_auth_pages_use_contextual_greetings_without_security_hint(self):
        login_response = self.client.get("/login")
        login_text = login_response.get_data(as_text=True)
        self.assertIn("Welcome", login_text)
        self.assertIn('href="/register"', login_text)
        self.assertIn('class="brandmark" href="/dashboard"', login_text)
        self.assertIn('href="/dashboard" class="btn btn-neon-secondary"', login_text)
        self.assertIn('href="/login" class="btn btn-neon-secondary"', login_text)
        self.assertIn('name="username"', login_text)
        self.assertIn('data-password-toggle', login_text)
        self.assertIn('aria-label="Show password"', login_text)
        self.assertIn('aria-label="Primary navigation"', login_text)
        self.assertIn("/static/css/bootstrap.min.css?v=", login_text)
        self.assertIn("/static/js/bootstrap.bundle.min.js?v=", login_text)
        self.assertNotIn("cdn.jsdelivr.net", login_text)
        self.assertNotIn("welcome back", login_text.lower())
        self.assertNotIn("Repeated failed logins are rate limited automatically", login_text)

        register_response = self.client.get("/register")
        register_text = register_response.get_data(as_text=True)
        self.assertIn("Create your account", register_text)
        self.assertIn('action="/register"', register_text)
        self.assertEqual(register_text.count('data-password-toggle'), 2)

    def test_logout_requires_post(self):
        self.register_user()

        response = self.client.get("/logout")
        self.assertEqual(response.status_code, 405)

        token = self.get_csrf_token("/dashboard")
        response = self.client.post("/logout", data={"csrf_token": token}, follow_redirects=True)
        self.assertIn("Login", response.get_data(as_text=True))

        response = self.client.get("/dashboard", follow_redirects=False)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Welcome to Cogni Cook", response.data)

    def test_login_rate_limit_blocks_repeated_failures(self):
        self.create_user()

        for _ in range(5):
            response = self.client.post(
                "/login",
                data={
                    "username": "tester_user",
                    "password": "wrong-password",
                    "csrf_token": self.get_csrf_token("/login"),
                },
                follow_redirects=False,
            )
            self.assertEqual(response.status_code, 200)

        response = self.client.post(
            "/login",
            data={
                "username": "tester_user",
                "password": "wrong-password",
                "csrf_token": self.get_csrf_token("/login"),
            },
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 429)
        self.assertIn("Too many login attempts", response.get_data(as_text=True))

    def test_login_account_lockout_blocks_rotating_remote_addresses(self):
        self.create_user()

        for index in range(5):
            response = self.client.post(
                "/login",
                data={
                    "username": "tester_user",
                    "password": "wrong-password",
                    "csrf_token": self.get_csrf_token("/login"),
                },
                environ_overrides={"REMOTE_ADDR": f"10.0.0.{index + 1}"},
                follow_redirects=False,
            )
            self.assertEqual(response.status_code, 200)

        response = self.client.post(
            "/login",
            data={
                "username": "tester_user",
                "password": "SecurePass8",
                "csrf_token": self.get_csrf_token("/login"),
            },
            environ_overrides={"REMOTE_ADDR": "10.0.0.99"},
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 429)
        self.assertIn("Too many login attempts", response.get_data(as_text=True))

    def test_rate_limit_ignores_untrusted_forwarded_for_header(self):
        self.create_user()

        for value in ["1.1.1.1", "2.2.2.2", "3.3.3.3", "4.4.4.4", "5.5.5.5"]:
            response = self.client.post(
                "/login",
                data={
                    "username": "tester_user",
                    "password": "wrong-password",
                    "csrf_token": self.get_csrf_token("/login"),
                },
                headers={"X-Forwarded-For": value},
                follow_redirects=False,
            )
            self.assertEqual(response.status_code, 200)

        response = self.client.post(
            "/login",
            data={
                "username": "tester_user",
                "password": "wrong-password",
                "csrf_token": self.get_csrf_token("/login"),
            },
            headers={"X-Forwarded-For": "6.6.6.6"},
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 429)

    def test_email_uniqueness_is_case_insensitive(self):
        self.create_user(email="case@example.com")
        response = self.register_user(username="different_user", email="CASE@example.com")
        self.assertIn(b"Email address already in use.", response.data)

    def test_malformed_password_hash_is_rejected_without_server_error(self):
        with self.app.app_context():
            db.session.add(
                User(
                    name="legacy_user",
                    email="legacy@example.com",
                    password_hash="invalid-password-hash",
                )
            )
            db.session.commit()

        response = self.login_user(username="legacy_user", password="SecurePass8")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Invalid username or password.", response.data)

