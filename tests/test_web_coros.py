import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from workoutbridge.calendar import Event
from workoutbridge.profiles import load_profile
from workoutbridge.web import create_app


class CorosWebTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.env = patch.dict(os.environ, {"WORKOUTBRIDGE_CONFIG_DIR": str(self.root / "config")})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.client = TestClient(
            create_app(self.root / "web", "https://bridge.example", "a" * 40, poll=False),
            base_url="https://bridge.example",
        )
        self.headers = {"Origin": "https://bridge.example"}

    def login(self):
        self.client.post("/api/v1/login", json={"password": "a" * 40}, headers=self.headers)

    def test_coros_login_requires_owner_then_saves_verified_profile(self):
        path = "/api/v1/coros/login"
        self.assertEqual(self.client.post(path, json={}, headers=self.headers).status_code, 401)
        self.login()
        with patch(
            "workoutbridge.coros_auth.begin_login",
            return_value={"login_url": "https://mcpus.coros.com/cli/login/test", "expires_in": 600},
        ):
            self.assertEqual(self.client.post(path, json={}).status_code, 403)
            result = self.client.post(
                path, json={"profile": "coros-test", "region": "us"}, headers=self.headers
            )
            self.assertEqual(result.status_code, 200)
            job = result.json()
        with patch("workoutbridge.coros_auth.finish_login", return_value=None):
            pending = self.client.post(
                path + "/finish", json={"id": job["id"]}, headers=self.headers
            )
            self.assertEqual(pending.json()["status"], "pending")
        with patch("workoutbridge.coros_auth.finish_login", return_value="coros:us:synthetic"):
            complete = self.client.post(
                path + "/finish", json={"id": job["id"]}, headers=self.headers
            )
            self.assertEqual(complete.json()["status"], "complete")
        self.assertEqual(load_profile("coros-test")["destination"], "coros")
        state = self.client.get("/api/v1/state").json()
        self.assertEqual(state["connections"][0]["provider"], "COROS")
        self.assertNotIn("session_dir", self.client.get("/api/v1/state").text)

    def test_coros_sync_review_and_publish_use_coros_adapter(self):
        self.login()
        profile = {
            "destination": "coros",
            "account_id": "coros:us:synthetic",
            "session_dir": str(self.root / "session"),
            "state_db": str(self.root / "coros.sqlite"),
        }
        with (
            patch("workoutbridge.web.load_profile", return_value=profile),
            patch("workoutbridge.web.read_calendar", return_value=b"synthetic"),
            patch(
                "workoutbridge.web.import_calendar",
                return_value=[Event("test", "one", "", "2026-10-22", "Run", "run 15 min")],
            ),
        ):
            source = self.client.post(
                "/api/v1/sources",
                json={
                    "name": "Test",
                    "format": "generic",
                    "timezone": "UTC",
                    "url": "https://calendar.google.com/calendar/ical/example/public/basic.ics",
                },
                headers=self.headers,
            ).json()["id"]
            rule = self.client.post(
                "/api/v1/syncs",
                json={"source": source, "profile": "coros-test"},
                headers=self.headers,
            ).json()["id"]
            plan = self.client.post(f"/api/v1/syncs/{rule}/preview", headers=self.headers).json()
            self.assertEqual(plan["items"][0]["payload"]["sportType"], 1)
            with (
                patch("workoutbridge.coros_client.CorosClient") as client,
                patch("workoutbridge.coros_publishing.CorosEventPublisher") as publisher,
                patch("workoutbridge.web.GarminProvider.connect") as garmin,
            ):
                publisher.return_value.publish.return_value = "123"
                result = self.client.post(
                    f"/api/v1/syncs/{rule}/publish",
                    json={"hash": plan["hash"], "selected": [0]},
                    headers=self.headers,
                )
                self.assertEqual(result.status_code, 200)
                self.assertEqual(publisher.return_value.publish.call_count, 1)
                self.assertEqual(garmin.call_count, 0)
                client.return_value.close.assert_called_once()
