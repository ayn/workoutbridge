import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from workoutbridge.profiles import authenticate_profile, load_profile
from workoutbridge.web import create_app


class TenantProfileTests(unittest.TestCase):
    def test_profiles_with_same_name_are_isolated_without_environment_mutation(self):
        with tempfile.TemporaryDirectory() as directory:
            a, b = Path(directory) / "a", Path(directory) / "b"
            authenticate_profile("personal", config_root=a, authenticator=lambda _: "123")
            authenticate_profile("personal", config_root=b, authenticator=lambda _: "456")
            self.assertEqual(load_profile("personal", config_root=a)["account_id"], "123")
            self.assertEqual(load_profile("personal", config_root=b)["account_id"], "456")
            app = create_app(
                a / "web", "https://bridge.example", "a" * 40, poll=False, config_root=a
            )
            client = TestClient(app, base_url="https://bridge.example")
            client.post(
                "/api/v1/login",
                json={"password": "a" * 40},
                headers={"Origin": "https://bridge.example"},
            )
            self.assertEqual(
                client.get("/api/v1/state").json()["connections"],
                [{"id": "personal", "provider": "Garmin Connect", "account": "123"}],
            )
