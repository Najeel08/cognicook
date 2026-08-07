from tests.base import (
    CogniCookTestCase,
    inspect,
    StaticPool,
    create_app,
    db,
)


class TestSecurity(CogniCookTestCase):
    def test_security_headers_are_present(self):
        response = self.client.get("/")
        self.assertEqual(response.headers.get("X-Content-Type-Options"), "nosniff")
        self.assertEqual(response.headers.get("X-Frame-Options"), "DENY")
        self.assertEqual(response.headers.get("Referrer-Policy"), "strict-origin-when-cross-origin")
        self.assertEqual(response.headers.get("Cache-Control"), "no-store, no-cache, must-revalidate, max-age=0")
        self.assertEqual(response.headers.get("Pragma"), "no-cache")
        self.assertEqual(response.headers.get("Expires"), "0")
        self.assertEqual(response.headers.get("Cross-Origin-Opener-Policy"), "same-origin")
        self.assertEqual(response.headers.get("Cross-Origin-Resource-Policy"), "same-origin")
        self.assertEqual(response.headers.get("X-Permitted-Cross-Domain-Policies"), "none")
        self.assertEqual(response.headers.get("Permissions-Policy"), "camera=(), microphone=(), geolocation=()")
        self.assertIn("Content-Security-Policy", response.headers)
        self.assertIn("connect-src 'self'", response.headers["Content-Security-Policy"])
        self.assertIn("script-src 'self'", response.headers["Content-Security-Policy"])
        self.assertIn("style-src 'self'", response.headers["Content-Security-Policy"])
        self.assertIn("font-src 'self'", response.headers["Content-Security-Policy"])
        self.assertNotIn("cdn.jsdelivr.net", response.headers["Content-Security-Policy"])
        self.assertNotIn("'unsafe-inline'", response.headers["Content-Security-Policy"])

    def test_hsts_header_is_configurable_for_production_like_environments(self):
        original_enabled = self.app.config.get("SECURITY_HSTS_ENABLED")
        original_max_age = self.app.config.get("SECURITY_HSTS_MAX_AGE")
        self.app.config["SECURITY_HSTS_ENABLED"] = True
        self.app.config["SECURITY_HSTS_MAX_AGE"] = 123
        try:
            response = self.client.get("/")
            self.assertEqual(
                response.headers.get("Strict-Transport-Security"),
                "max-age=123; includeSubDomains",
            )
        finally:
            if original_enabled is None:
                self.app.config.pop("SECURITY_HSTS_ENABLED", None)
            else:
                self.app.config["SECURITY_HSTS_ENABLED"] = original_enabled
            if original_max_age is None:
                self.app.config.pop("SECURITY_HSTS_MAX_AGE", None)
            else:
                self.app.config["SECURITY_HSTS_MAX_AGE"] = original_max_age

    def test_trusted_hosts_reject_unexpected_host_headers(self):
        original_trusted_hosts = self.app.config.get("TRUSTED_HOSTS")
        self.app.config["TRUSTED_HOSTS"] = ["good.test"]
        try:
            response = self.client.get("/", headers={"Host": "evil.test"})
            self.assertEqual(response.status_code, 400)

            response = self.client.get("/", headers={"Host": "good.test"})
            self.assertEqual(response.status_code, 302)
            self.assertEqual(response.headers.get("Location"), "/dashboard")
        finally:
            self.app.config["TRUSTED_HOSTS"] = original_trusted_hosts

    def test_error_pages_return_visitors_to_public_dashboard(self):
        response = self.client.get("/missing-page")
        text = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 404)
        self.assertIn('href="/dashboard"', text)
        self.assertIn("Go to Dashboard", text)

    def test_method_not_allowed_uses_consistent_error_view(self):
        response = self.client.get("/logout")
        text = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 405)
        self.assertIn("Method Not Allowed", text)
        self.assertIn("This action is not available for the requested method.", text)

    def test_request_too_large_uses_consistent_error_view(self):
        original_limit = self.app.config.get("MAX_CONTENT_LENGTH")
        self.app.config["MAX_CONTENT_LENGTH"] = 64
        try:
            response = self.client.post(
                "/dashboard",
                data={"ingredients": "x" * 512, "csrf_token": "token"},
                follow_redirects=False,
            )
            text = response.get_data(as_text=True)

            self.assertEqual(response.status_code, 413)
            self.assertIn("Request Too Large", text)
            self.assertIn("The submitted data is too large.", text)
        finally:
            self.app.config["MAX_CONTENT_LENGTH"] = original_limit

    def test_static_assets_are_cacheable_but_keep_security_headers(self):
        response = self.client.get("/static/js/theme-init.js")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers.get("Cache-Control"), "public, max-age=31536000, immutable")
        self.assertEqual(response.headers.get("X-Content-Type-Options"), "nosniff")
        self.assertNotEqual(response.headers.get("Pragma"), "no-cache")
        response.close()

        response = self.client.get("/static/css/bootstrap.min.css")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers.get("Cache-Control"), "public, max-age=31536000, immutable")
        response.close()

        response = self.client.get("/static/js/bootstrap.bundle.min.js")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers.get("Cache-Control"), "public, max-age=31536000, immutable")
        response.close()

        response = self.client.get("/static/js/cognicook.js")
        script_text = response.get_data(as_text=True)
        self.assertNotIn("window.location.reload", script_text)
        self.assertNotIn("cognicook-history-reload", script_text)
        response.close()

    def test_search_history_is_not_stored_or_exposed(self):
        self.register_user()
        self.login_user()
        self.client.get("/recommendations?ingredients=onion,tomato,potato")

        response = self.client.get("/activity", follow_redirects=False)
        self.assertEqual(response.status_code, 404)

        dashboard_text = self.client.get("/dashboard").get_data(as_text=True)
        self.assertNotIn(">Activity</a>", dashboard_text)

        with self.app.app_context():
            self.assertFalse(inspect(db.engine).has_table("search_activity"))

    def test_production_configuration_fails_closed(self):
        class ProductionConfig:
            TESTING = True
            IS_PRODUCTION = True
            SECRET_KEY = "x" * 48
            SECRET_KEY_FROM_ENV = True
            REQUIRE_SECRET_KEY_FROM_ENV = True
            SESSION_COOKIE_SECURE = True
            TRUSTED_HOSTS = ["cognicook.example"]
            SQLALCHEMY_DATABASE_URI = "sqlite://"
            SQLALCHEMY_TRACK_MODIFICATIONS = False
            SQLALCHEMY_ENGINE_OPTIONS = {
                "connect_args": {"check_same_thread": False},
                "poolclass": StaticPool,
            }
            AUTO_BOOTSTRAP_DATA = False

        class WeakSecretConfig(ProductionConfig):
            SECRET_KEY = "short"

        class InsecureCookieConfig(ProductionConfig):
            SESSION_COOKIE_SECURE = False

        class MissingHostsConfig(ProductionConfig):
            TRUSTED_HOSTS = None

        class WildcardHostsConfig(ProductionConfig):
            TRUSTED_HOSTS = ["*"]

        with self.assertRaisesRegex(RuntimeError, "at least 32 characters"):
            create_app(WeakSecretConfig)
        with self.assertRaisesRegex(RuntimeError, "SESSION_COOKIE_SECURE"):
            create_app(InsecureCookieConfig)
        with self.assertRaisesRegex(RuntimeError, "explicit production hostnames"):
            create_app(MissingHostsConfig)
        with self.assertRaisesRegex(RuntimeError, "explicit production hostnames"):
            create_app(WildcardHostsConfig)

        production_app = create_app(ProductionConfig)
        try:
            response = production_app.test_client().get("/", headers={"Host": "cognicook.example"})
            self.assertEqual(response.status_code, 302)
            self.assertEqual(response.headers.get("Location"), "/dashboard")
        finally:
            with production_app.app_context():
                db.session.remove()
                db.engine.dispose()

    def test_static_assets_use_versioned_urls_with_immutable_cache_headers(self):
        response = self.client.get("/dashboard")
        body = response.get_data(as_text=True)
        self.assertRegex(body, r'/static/js/theme-init\.js\?v=[0-9a-f]{12}')
        self.assertRegex(body, r'/static/css/bootstrap\.min\.css\?v=[0-9a-f]{12}')
        self.assertRegex(body, r'/static/css/cognicook\.css\?v=[0-9a-f]{12}')
        self.assertRegex(body, r'/static/js/bootstrap\.bundle\.min\.js\?v=[0-9a-f]{12}')
        self.assertRegex(body, r'/static/js/cognicook\.js\?v=[0-9a-f]{12}')

