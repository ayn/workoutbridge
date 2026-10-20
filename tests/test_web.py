import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from workoutbridge.web import create_app


class WebTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.app = create_app(self.root, "https://bridge.example", "a" * 40, poll=False)
        self.client = TestClient(self.app, base_url="https://bridge.example")
        self.headers = {"Origin": "https://bridge.example"}

    def login(self):
        r = self.client.post("/api/login", json={"password": "a" * 40}, headers=self.headers)
        self.assertEqual(r.status_code, 200)
        self.assertIn("HttpOnly", r.headers["set-cookie"])
        self.assertIn("Secure", r.headers["set-cookie"])

    def test_auth_and_csrf(self):
        self.assertEqual(self.client.get("/api/state").status_code, 401)
        self.assertEqual(
            self.client.post("/api/login", json={"password": "a" * 40}).status_code, 403
        )
        self.login()
        self.assertEqual(self.client.get("/api/state").status_code, 200)
        self.assertEqual(
            self.client.post("/api/logout", headers={"Origin": "https://evil.example"}).status_code,
            403,
        )
        self.client.post("/api/logout", headers=self.headers)
        self.assertEqual(self.client.get("/api/state").status_code, 401)

    def test_sources_private_and_restricted(self):
        self.login()
        for url in (
            "/etc/passwd",
            "http://localhost/test",
            "https://127.0.0.1/x",
            "https://log.finalsurge.com.evil.example/x",
            "https://log.finalsurge.com:444/x",
        ):
            r = self.client.post(
                "/api/sources",
                json={"name": "Training", "url": url, "format": "finalsurge", "timezone": "UTC"},
                headers=self.headers,
            )
            self.assertEqual(r.status_code, 422)
        url = "https://log.finalsurge.com/delivery/ical/SYNTHETICPRIVATE"
        r = self.client.post(
            "/api/sources",
            json={"name": "Training", "url": url, "format": "finalsurge", "timezone": "UTC"},
            headers=self.headers,
        )
        self.assertEqual(r.status_code, 200)
        state = self.client.get("/api/state")
        self.assertNotIn("SYNTHETICPRIVATE", state.text)
        self.assertEqual(len(state.json()["sources"]), 1)
        self.assertEqual((self.root / "web.sqlite").stat().st_mode & 0o777, 0o600)

    def test_preview_and_publish_require_exact_server_plan(self):
        self.login()
        source = self.client.post(
            "/api/sources",
            json={
                "name": "Training",
                "url": "https://log.finalsurge.com/delivery/ical/EXAMPLE",
                "format": "finalsurge",
                "timezone": "UTC",
            },
            headers=self.headers,
        ).json()["id"]
        profile = {
            "account_id": "123",
            "session_dir": str(self.root / "session"),
            "state_db": str(self.root / "pub.sqlite"),
        }
        with patch("workoutbridge.web.load_profile", return_value=profile):
            rule = self.client.post(
                "/api/syncs", json={"source": source, "profile": "personal"}, headers=self.headers
            ).json()["id"]
            from workoutbridge.calendar import Event

            event = Event(source, "synthetic", "", "2030-01-01", "Run: 4 strides", "")
            with (
                patch("workoutbridge.web.read_calendar", return_value=b"synthetic calendar"),
                patch("workoutbridge.web.import_calendar", return_value=[event]),
                patch("workoutbridge.web.GarminProvider.connect") as connect,
            ):
                r = self.client.post(f"/api/syncs/{rule}/preview", headers=self.headers)
                self.assertEqual(r.status_code, 200)
                connect.assert_not_called()
            plan = r.json()
            self.assertEqual(plan["items"][0]["draft"]["steps"][0]["count"], 4)
            with (
                patch("workoutbridge.web.GarminProvider.connect") as connect,
                patch("workoutbridge.web.Publisher") as publisher,
            ):
                bad = self.client.post(
                    f"/api/syncs/{rule}/publish",
                    json={"hash": "wrong", "selected": [0]},
                    headers=self.headers,
                )
                self.assertEqual(bad.status_code, 409)
                connect.assert_not_called()
                publisher.return_value.publish.return_value = "55"
                good = self.client.post(
                    f"/api/syncs/{rule}/publish",
                    json={"hash": plan["hash"], "selected": [0]},
                    headers=self.headers,
                )
                self.assertEqual(good.status_code, 200)
                publisher.return_value.publish.assert_called_once()
            self.assertTrue(list((self.root / "archive").rglob("*.ics")))

    def test_fetch_failure_is_redacted(self):
        self.login()
        source = self.client.post(
            "/api/sources",
            json={
                "name": "Training",
                "url": "https://log.finalsurge.com/delivery/ical/PRIVATE",
                "format": "finalsurge",
                "timezone": "UTC",
            },
            headers=self.headers,
        ).json()["id"]
        with patch("workoutbridge.web.load_profile", return_value={"account_id": "123"}):
            rule = self.client.post(
                "/api/syncs", json={"source": source, "profile": "test"}, headers=self.headers
            ).json()["id"]
            with (
                patch("workoutbridge.web.read_calendar", side_effect=ValueError("PRIVATE")),
                patch("workoutbridge.web.GarminProvider.connect") as connect,
            ):
                self.app.state.poll_once()
                connect.assert_not_called()
            state = self.client.get("/api/state")
            self.assertNotIn("PRIVATE", state.text)
            self.assertIn("failed", state.json()["syncs"][0]["error"])
            self.assertEqual(
                self.client.post(
                    f"/api/syncs/{rule}/pause", json={"paused": True}, headers=self.headers
                ).status_code,
                200,
            )
            with patch("workoutbridge.web.read_calendar") as fetch:
                self.app.state.poll_once()
                fetch.assert_not_called()

    def test_bad_host_and_login_throttle(self):
        self.assertEqual(
            self.client.get("/health", headers={"host": "evil.example"}).status_code, 400
        )
        for _ in range(10):
            self.client.post("/api/login", json={"password": "incorrect"}, headers=self.headers)
        self.assertEqual(
            self.client.post(
                "/api/login", json={"password": "a" * 40}, headers=self.headers
            ).status_code,
            429,
        )

    def test_login_body_is_bounded(self):
        self.assertEqual(
            self.client.post(
                "/api/login", json={"password": "a" * 17000}, headers=self.headers
            ).status_code,
            413,
        )
