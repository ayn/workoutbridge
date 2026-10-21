import tempfile
import threading
import unittest
from pathlib import Path

from fastapi import HTTPException
from fastapi.testclient import TestClient

from workoutbridge.profiles import authenticate_profile, load_profile
from workoutbridge.web import create_app


class WebExtensionTests(unittest.TestCase):
    def test_embedding_supplies_operation_lock_and_runs_only_whitelisted_actions(self):
        with tempfile.TemporaryDirectory() as directory:
            operation = threading.RLock()
            app = create_app(
                Path(directory), "https://bridge.example", "a" * 40, poll=False, operation=operation
            )
            self.assertIs(app.state.operation, operation)
            with self.assertRaises(ValueError):
                app.state.run_action("delete_everything", "unknown", {})
            with self.assertRaises(HTTPException):
                app.state.run_action("preview", "missing", {})

    def test_explicit_profile_roots_do_not_change_process_environment(self):
        with tempfile.TemporaryDirectory() as directory:
            first, second = Path(directory) / "first", Path(directory) / "second"
            authenticate_profile("personal", config_root=first, authenticator=lambda _: "123")
            authenticate_profile("personal", config_root=second, authenticator=lambda _: "456")
            self.assertEqual(load_profile("personal", config_root=first)["account_id"], "123")
            self.assertEqual(load_profile("personal", config_root=second)["account_id"], "456")

    def test_embedding_authentication_is_explicit_and_default_owner_login_still_works(self):
        with tempfile.TemporaryDirectory() as directory:
            app = create_app(
                Path(directory),
                "https://bridge.example",
                "a" * 40,
                poll=False,
                authenticate_request=lambda request: (
                    request.headers.get("x-synthetic") == "allowed"
                ),
            )
            client = TestClient(app, base_url="https://bridge.example")
            self.assertEqual(client.get("/api/v1/state").status_code, 401)
            self.assertEqual(
                client.get("/api/v1/state", headers={"x-synthetic": "allowed"}).status_code, 200
            )
            self.assertEqual(
                client.post(
                    "/api/v1/login",
                    json={"password": "a" * 40},
                    headers={"Origin": "https://bridge.example", "x-synthetic": "allowed"},
                ).status_code,
                404,
            )
