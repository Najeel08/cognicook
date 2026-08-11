from tests.base import (
    CogniCookTestCase,
    BASE_DIR,
    resolve_project_path,
    load_dataset_rows,
)


class TestValidation(CogniCookTestCase):
    def test_relative_configuration_paths_resolve_from_project_root(self):
        self.assertEqual(
            resolve_project_path("instance/test.db", "unused"),
            BASE_DIR / "instance" / "test.db",
        )
        absolute_path = BASE_DIR / "dataset" / "recipes.csv"
        self.assertEqual(resolve_project_path(absolute_path, "unused"), absolute_path)

    def test_dataset_loader_rejects_traversal_paths(self):
        with self.assertRaisesRegex(ValueError, "Dataset path is invalid"):
            load_dataset_rows("../dataset/recipes.csv")

    def test_query_schema_rejects_unknown_duplicate_and_xss_parameters(self):
        self.register_user()
        self.login_user()

        response = self.client.get("/recommendations?ingredients=onion,tomato,potato&unexpected=1")
        self.assertEqual(response.status_code, 400)

        response = self.client.get("/recommendations?ingredients=onion,tomato,potato&page=1&page=2")
        self.assertEqual(response.status_code, 400)

        response = self.client.get("/recommendations?ingredients=onion,tomato,potato%3Cscript%3E")
        self.assertEqual(response.status_code, 400)

    def test_query_schema_rejects_traversal_in_url_parameters(self):
        self.register_user()
        self.login_user()

        response = self.client.get("/recommendations?ingredients=onion,tomato,..%2Fsecret")
        self.assertEqual(response.status_code, 400)

