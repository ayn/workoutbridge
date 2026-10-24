import tempfile
import time
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
        fetch = patch("workoutbridge.web.read_calendar", side_effect=ValueError("Offline fixture"))
        fetch.start()
        self.addCleanup(fetch.stop)

    def login(self):
        r = self.client.post("/api/v1/login", json={"password": "a" * 40}, headers=self.headers)
        self.assertEqual(r.status_code, 200)
        self.assertIn("HttpOnly", r.headers["set-cookie"])
        self.assertIn("Secure", r.headers["set-cookie"])

    def test_api_routes_are_versioned_and_health_is_not(self):
        paths = {route.path for route in self.app.routes}
        self.assertIn("/api/v1/login", paths)
        self.assertIn("/api/v1/syncs/{key}/publish", paths)
        self.assertTrue(all(p.startswith("/api/v1/") for p in paths if p.startswith("/api/")))
        self.assertEqual(self.client.get("/health").json(), {"status": "ok"})
        for path in ("/api/login", "/api/state", "/api/v2/state"):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 404)
                self.assertEqual(response.headers["content-type"], "application/json")
        response = self.client.post("/api/syncs/example/publish", json={}, headers=self.headers)
        self.assertEqual(response.status_code, 404)

    def automatic_rule(self):
        self.login()
        profile = {
            "account_id": "123",
            "session_dir": str(self.root / "session"),
            "state_db": str(self.root / "pub.sqlite"),
        }
        patcher = patch("workoutbridge.web.load_profile", return_value=profile)
        patcher.start()
        self.addCleanup(patcher.stop)
        source = self.client.post(
            "/api/v1/sources",
            json={
                "name": "Training",
                "url": "https://log.finalsurge.com/delivery/ical/EXAMPLE",
                "format": "finalsurge",
                "timezone": "UTC",
            },
            headers=self.headers,
        ).json()["id"]
        rule = self.client.post(
            "/api/v1/syncs", json={"source": source, "profile": "test"}, headers=self.headers
        ).json()["id"]
        return rule, source, profile

    def test_coaching_policy_is_validated_persisted_and_scoped_to_source(self):
        from workoutbridge.calendar import Event

        rule, source, _ = self.automatic_rule()
        endpoint = f"/api/v1/sources/{source}/coaching-policy"
        for value in ("unknown", True, None):
            self.assertEqual(
                self.client.post(
                    endpoint, json={"policy": value}, headers=self.headers
                ).status_code,
                422,
            )
        events = [Event(source, "run", "", "2030-01-01", "Run: 3x1200", "")]
        with (
            patch("workoutbridge.web.read_calendar", return_value=b"synthetic"),
            patch("workoutbridge.web.import_calendar", return_value=events),
        ):
            self.app.state.poll_once(rule)
            self.assertIn("error", self.client.get("/api/v1/state").json()["plans"][0]["items"][0])

            response = self.client.post(endpoint, json={"policy": "cj"}, headers=self.headers)
            self.assertEqual(response.status_code, 200)
            self.app.state.poll_once(rule)
            state = self.client.get("/api/v1/state").json()
            self.assertEqual(state["sources"][0]["coaching_policy"], "cj")
            self.assertNotIn("error", state["plans"][0]["items"][0])
            self.client.post(endpoint, json={"policy": "strict"}, headers=self.headers)
            self.app.state.poll_once(rule)
            self.assertIn("error", self.client.get("/api/v1/state").json()["plans"][0]["items"][0])

    def test_source_distance_units_are_saved_validated_and_used_for_preview(self):
        from workoutbridge.calendar import Event

        rule, source, _ = self.automatic_rule()
        endpoint = f"/api/v1/sources/{source}/distance-unit"
        self.assertEqual(
            self.client.post(endpoint, json={"unit": "meters"}, headers=self.headers).status_code,
            422,
        )
        self.assertEqual(
            self.client.post(endpoint, json={"unit": "km"}, headers=self.headers).status_code, 200
        )
        events = [Event(source, "run", "", "2030-01-01", "Run: 12 easy", "")]
        with (
            patch("workoutbridge.web.read_calendar", return_value=b"synthetic"),
            patch("workoutbridge.web.import_calendar", return_value=events),
        ):
            self.app.state.poll_once(rule)
            state = self.client.get("/api/v1/state").json()
            self.assertEqual(state["sources"][0]["distance_unit"], "km")
            self.assertNotIn("error", state["plans"][0]["items"][0])
            self.assertEqual(state["plans"][0]["items"][0]["draft"]["steps"][0]["duration"], 12000)

    def test_owner_session_survives_restart_without_storing_bearer_token(self):
        self.login()
        token = self.client.cookies.get("wb_session")
        restarted = TestClient(
            create_app(self.root, "https://bridge.example", "a" * 40, poll=False),
            base_url="https://bridge.example",
        )
        response = restarted.get("/api/v1/state", headers={"Cookie": f"wb_session={token}"})
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(token.encode(), (self.root / "web.sqlite").read_bytes())
        self.assertEqual((self.root / "web.sqlite").stat().st_mode & 0o777, 0o600)

    def test_owner_session_rolls_for_30_days_and_expires_after_inactivity(self):
        now = time.time()
        with patch("workoutbridge.web.time.time", return_value=now):
            self.login()
        token = self.client.cookies.get("wb_session")
        headers = {"Cookie": f"wb_session={token}"}
        with patch("workoutbridge.web.time.time", return_value=now + 29 * 86400):
            response = self.client.get("/api/v1/state", headers=headers)
            self.assertEqual(response.status_code, 200)
            self.assertIn("Max-Age=2592000", response.headers["set-cookie"])
            self.assertIn("HttpOnly", response.headers["set-cookie"])
            self.assertIn("Secure", response.headers["set-cookie"])
            self.assertIn("SameSite=strict", response.headers["set-cookie"])
        with patch("workoutbridge.web.time.time", return_value=now + 31 * 86400):
            self.assertEqual(self.client.get("/api/v1/state", headers=headers).status_code, 200)
        with patch("workoutbridge.web.time.time", return_value=now + 62 * 86400):
            self.assertEqual(self.client.get("/api/v1/state", headers=headers).status_code, 401)

    def test_owner_logout_revokes_persistent_session_and_password_change_invalidates(self):
        self.login()
        token = self.client.cookies.get("wb_session")
        headers = {"Cookie": f"wb_session={token}"}
        changed = TestClient(
            create_app(self.root, "https://bridge.example", "b" * 40, poll=False),
            base_url="https://bridge.example",
        )
        self.assertEqual(changed.get("/api/v1/state", headers=headers).status_code, 401)
        self.client.post("/api/v1/logout", headers=self.headers)
        restarted = TestClient(
            create_app(self.root, "https://bridge.example", "a" * 40, poll=False),
            base_url="https://bridge.example",
        )
        self.assertEqual(restarted.get("/api/v1/state", headers=headers).status_code, 401)

    def test_rejected_requests_do_not_extend_owner_session(self):
        now = time.time()
        with patch("workoutbridge.web.time.time", return_value=now):
            self.login()
        token = self.client.cookies.get("wb_session")
        headers = {"Cookie": f"wb_session={token}", "Origin": "https://evil.example"}
        with patch("workoutbridge.web.time.time", return_value=now + 29 * 86400):
            response = self.client.post("/api/v1/logout", headers=headers)
            self.assertEqual(response.status_code, 403)
            self.assertNotIn("set-cookie", response.headers)
        with patch("workoutbridge.web.time.time", return_value=now + 31 * 86400):
            self.assertEqual(self.client.get("/api/v1/state", headers=headers).status_code, 401)

    def test_hourly_publish_is_opt_in_account_bound_and_idempotent(self):
        from test_publishing import FakeGarmin

        from workoutbridge.calendar import Event

        rule, source, profile = self.automatic_rule()
        other = self.client.post(
            "/api/v1/syncs", json={"source": source, "profile": "other"}, headers=self.headers
        ).json()["id"]
        provider = FakeGarmin()
        provider.account_id = "123"
        events = [
            Event(source, "run", "", "2030-01-01", "Run: 20 min", ""),
            Event(source, "unclear", "", "2030-01-02", "Run: mysterious exercise", ""),
        ]
        with (
            patch("workoutbridge.web.read_calendar", return_value=b"synthetic"),
            patch("workoutbridge.web.import_calendar", return_value=events),
            patch("workoutbridge.web.GarminProvider.connect", return_value=provider) as connect,
        ):
            self.app.state.poll_once()
            connect.assert_not_called()
            endpoint = f"/api/v1/syncs/{rule}/automatic"
            self.assertEqual(
                self.client.post(
                    endpoint, json={"enabled": True, "account": "999"}, headers=self.headers
                ).status_code,
                409,
            )
            self.assertEqual(
                self.client.post(
                    endpoint, json={"enabled": True, "account": "123"}, headers=self.headers
                ).status_code,
                200,
            )
            self.assertEqual((provider.uploads, provider.schedules), (1, 1))
            checks = self.client.get("/api/v1/state").json()["history"]
            self.assertEqual(sum(h["sync"] == other for h in checks), 1)
            self.app.state.poll_once()
            self.app.state.poll_once()
            self.assertEqual((provider.uploads, provider.schedules), (1, 1))
            profile["account_id"] = "999"
            connect.reset_mock()
            self.app.state.poll_once()
            connect.assert_not_called()
            rules = self.client.get("/api/v1/state").json()["syncs"]
            self.assertTrue(next(s for s in rules if s["id"] == rule)["auto_blocked"])

    def test_automatic_failure_latches_across_restart_and_requires_acknowledgment(self):
        from workoutbridge.calendar import Event

        rule, source, _ = self.automatic_rule()
        endpoint = f"/api/v1/syncs/{rule}/automatic"
        self.assertEqual(
            self.client.post(
                endpoint, json={"enabled": True, "account": "123"}, headers=self.headers
            ).status_code,
            200,
        )
        with (
            patch("workoutbridge.web.read_calendar", return_value=b"synthetic"),
            patch(
                "workoutbridge.web.import_calendar",
                return_value=[Event(source, "run", "", "2030-01-01", "Run: 20 min", "")],
            ),
            patch(
                "workoutbridge.web.GarminProvider.connect", side_effect=RuntimeError("PRIVATE")
            ) as connect,
        ):
            self.app.state.poll_once()
            restarted = create_app(self.root, "https://bridge.example", "a" * 40, poll=False)
            restarted.state.poll_once()
            connect.assert_called_once()
        state = self.client.get("/api/v1/state")
        self.assertNotIn("PRIVATE", state.text)
        self.assertTrue(state.json()["syncs"][0]["auto_blocked"])
        self.assertEqual(
            self.client.post(
                endpoint, json={"enabled": True, "account": "123"}, headers=self.headers
            ).status_code,
            409,
        )
        self.assertEqual(
            self.client.post(
                endpoint,
                json={"enabled": True, "account": "123", "acknowledge_review": True},
                headers=self.headers,
            ).status_code,
            200,
        )

    def test_automatic_empty_failed_fetch_and_paused_do_not_connect(self):
        rule, _, _ = self.automatic_rule()
        self.assertEqual(
            self.client.post(
                f"/api/v1/syncs/{rule}/automatic",
                json={"enabled": True, "account": "123"},
                headers=self.headers,
            ).status_code,
            200,
        )
        with patch("workoutbridge.web.GarminProvider.connect") as connect:
            with patch("workoutbridge.web.read_calendar", side_effect=ValueError("PRIVATE")):
                self.app.state.poll_once()
            history = self.client.get("/api/v1/state").json()["history"]
            self.assertEqual(history[-1]["status"], "Feed check failed")
            self.assertNotIn("PRIVATE", str(history))
            with (
                patch("workoutbridge.web.read_calendar", return_value=b"synthetic"),
                patch("workoutbridge.web.import_calendar", return_value=[]),
            ):
                self.app.state.poll_once()
                self.client.post(f"/api/v1/syncs/{rule}/preview", json={}, headers=self.headers)
            history = self.client.get("/api/v1/state").json()["history"]
            self.assertEqual(len(history), 4)
            for entry in history[2:]:
                self.assertEqual(entry["status"], "Checked successfully")
                self.assertEqual(entry["upcoming_count"], 0)
                self.assertEqual(entry["results"], [])
                self.assertEqual(entry["sync"], rule)
                self.assertTrue(entry["at"])
            self.client.post(
                f"/api/v1/syncs/{rule}/pause", json={"paused": True}, headers=self.headers
            )
            with patch("workoutbridge.web.read_calendar") as fetch:
                self.client.post(
                    f"/api/v1/syncs/{rule}/automatic",
                    json={"enabled": True, "account": "123"},
                    headers=self.headers,
                )
                self.app.state.poll_once()
                fetch.assert_not_called()
            self.assertEqual(self.client.get("/api/v1/state").json()["history"], history)
            connect.assert_not_called()

    def test_manual_failure_also_stops_enabled_automatic_publishing(self):
        from workoutbridge.calendar import Event

        rule, source, _ = self.automatic_rule()
        self.client.post(
            f"/api/v1/syncs/{rule}/automatic",
            json={"enabled": True, "account": "123"},
            headers=self.headers,
        )
        with (
            patch("workoutbridge.web.read_calendar", return_value=b"synthetic"),
            patch(
                "workoutbridge.web.import_calendar",
                return_value=[Event(source, "run", "", "2030-01-01", "Run: 20 min", "")],
            ),
        ):
            plan = self.client.post(f"/api/v1/syncs/{rule}/preview", headers=self.headers).json()
        with patch("workoutbridge.web.GarminProvider.connect", side_effect=RuntimeError("PRIVATE")):
            self.assertEqual(
                self.client.post(
                    f"/api/v1/syncs/{rule}/publish",
                    json={"hash": plan["hash"], "selected": [0]},
                    headers=self.headers,
                ).status_code,
                409,
            )
        self.assertTrue(self.client.get("/api/v1/state").json()["syncs"][0]["auto_blocked"])

    def test_auth_and_csrf(self):
        self.assertEqual(self.client.get("/api/v1/state").status_code, 401)
        self.assertEqual(
            self.client.post("/api/v1/login", json={"password": "a" * 40}).status_code, 403
        )
        self.login()
        self.assertEqual(self.client.get("/api/v1/state").status_code, 200)
        self.assertEqual(
            self.client.post(
                "/api/v1/logout", headers={"Origin": "https://evil.example"}
            ).status_code,
            403,
        )
        self.client.post("/api/v1/logout", headers=self.headers)
        self.assertEqual(self.client.get("/api/v1/state").status_code, 401)

    def test_garmin_login_api_requires_owner_origin_and_https(self):
        path = "/api/v1/garmin/login"
        self.assertEqual(self.client.post(path, json={}, headers=self.headers).status_code, 401)
        self.login()
        with patch(
            "workoutbridge.web_auth.GarminLogin.start",
            return_value={"id": "job", "status": "signing_in"},
        ) as start:
            body = {
                "profile": "personal",
                "email": "example@example.invalid",
                "password": "PRIVATE",
            }
            self.assertEqual(self.client.post(path, json=body).status_code, 403)
            response = self.client.post(path, json=body, headers=self.headers)
            self.assertEqual(response.status_code, 200)
            self.assertNotIn("PRIVATE", response.text)
            start.assert_called_once_with("personal", "example@example.invalid", "PRIVATE")
        self.assertEqual(self.client.get(path).status_code, 200)
        self.assertEqual(
            self.client.post(
                path + "/mfa", json={"id": "wrong", "code": "123456"}, headers=self.headers
            ).status_code,
            409,
        )
        http = TestClient(
            create_app(self.root / "http", "http://bridge.example", "a" * 40, poll=False),
            base_url="http://bridge.example",
        )
        http.post(
            "/api/v1/login",
            json={"password": "a" * 40},
            headers={"Origin": "http://bridge.example"},
        )
        self.assertEqual(
            http.post(path, json=body, headers={"Origin": "http://bridge.example"}).status_code, 403
        )

    def test_google_share_link_and_ics_are_one_source(self):
        self.login()
        body = {
            "name": "Synthetic calendar",
            "url": "https://calendar.google.com/calendar/embed?src=synthetic%40example.invalid",
            "format": "generic",
            "timezone": "UTC",
        }
        response = self.client.post("/api/v1/sources", json=body, headers=self.headers)
        self.assertEqual(response.status_code, 200)
        body["url"] = (
            "https://calendar.google.com/calendar/ical/synthetic%40example.invalid/public/basic.ics"
        )
        response = self.client.post("/api/v1/sources", json=body, headers=self.headers)
        self.assertEqual(response.status_code, 409)

    def test_icloud_published_link_aliases_are_one_private_source(self):
        self.login()
        url = "webcal://p123-caldav.icloud.com/published/2/SYNTHETIC_PRIVATE_TOKEN"
        body = {"name": "Synthetic training", "url": url, "format": "generic", "timezone": "UTC"}
        with patch("workoutbridge.feed.build_opener") as network:
            response = self.client.post("/api/v1/sources", json=body, headers=self.headers)
            self.assertEqual(response.status_code, 200)
            body["url"] = url.replace("webcal:", "https:")
            self.assertEqual(
                self.client.post("/api/v1/sources", json=body, headers=self.headers).status_code,
                409,
            )
            network.assert_not_called()
        state = self.client.get("/api/v1/state")
        self.assertNotIn("SYNTHETIC_PRIVATE_TOKEN", state.text)
        self.assertEqual(len(state.json()["sources"]), 1)

    def test_teamup_subscription_is_supported_without_exposing_its_token(self):
        self.login()
        body = {
            "name": "Calendar",
            "url": "https://ics.teamup.com/feed/SYNTHETIC_123/456.ics",
            "format": "generic",
            "timezone": "UTC",
        }
        response = self.client.post("/api/v1/sources", json=body, headers=self.headers)
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("SYNTHETIC_123", self.client.get("/api/v1/state").text)
        for url in (
            "https://ics.teamup.com.evil.invalid/feed/SYNTHETIC/456.ics",
            "https://teamup.com/feed/SYNTHETIC/456.ics",
        ):
            body["url"] = url
            self.assertEqual(
                self.client.post("/api/v1/sources", json=body, headers=self.headers).status_code,
                422,
            )

    def test_sources_private_and_restricted(self):
        self.login()
        for url in (
            "/etc/passwd",
            "http://localhost/test",
            "https://127.0.0.1/x",
            "https://log.finalsurge.com.evil.example/x",
            "https://log.finalsurge.com:444/x",
            "https://p123-caldav.icloud.com.evil.invalid/published/2/SYNTHETIC",
            "https://evil-p123-caldav.icloud.com/published/2/SYNTHETIC",
            "https://p123-caldav.icloud.com/private/calendar/",
            "webcal://127.0.0.1/published/2/SYNTHETIC",
        ):
            r = self.client.post(
                "/api/v1/sources",
                json={"name": "Training", "url": url, "format": "finalsurge", "timezone": "UTC"},
                headers=self.headers,
            )
            self.assertEqual(r.status_code, 422)
        url = "https://log.finalsurge.com/delivery/ical/SYNTHETICPRIVATE"
        r = self.client.post(
            "/api/v1/sources",
            json={"name": "Training", "url": url, "format": "finalsurge", "timezone": "UTC"},
            headers=self.headers,
        )
        self.assertEqual(r.status_code, 200)
        state = self.client.get("/api/v1/state")
        self.assertNotIn("SYNTHETICPRIVATE", state.text)
        self.assertEqual(len(state.json()["sources"]), 1)
        self.assertEqual((self.root / "web.sqlite").stat().st_mode & 0o777, 0o600)

    def test_preview_and_publish_require_exact_server_plan(self):
        self.login()
        source = self.client.post(
            "/api/v1/sources",
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
                "/api/v1/syncs",
                json={"source": source, "profile": "personal"},
                headers=self.headers,
            ).json()["id"]
            from workoutbridge.calendar import Event

            event = Event(source, "synthetic", "", "2030-01-01", "Run: 4 strides", "")
            with (
                patch("workoutbridge.web.read_calendar", return_value=b"synthetic calendar"),
                patch("workoutbridge.web.import_calendar", return_value=[event]),
                patch("workoutbridge.web.GarminProvider.connect") as connect,
            ):
                r = self.client.post(f"/api/v1/syncs/{rule}/preview", headers=self.headers)
                self.assertEqual(r.status_code, 200)
                connect.assert_not_called()
            plan = r.json()
            self.assertEqual(plan["items"][0]["draft"]["steps"][0]["count"], 4)
            with (
                patch("workoutbridge.web.GarminProvider.connect") as connect,
                patch("workoutbridge.web.Publisher") as publisher,
            ):
                bad = self.client.post(
                    f"/api/v1/syncs/{rule}/publish",
                    json={"hash": "wrong", "selected": [0]},
                    headers=self.headers,
                )
                self.assertEqual(bad.status_code, 409)
                connect.assert_not_called()
                publisher.return_value.publish.return_value = "55"
                good = self.client.post(
                    f"/api/v1/syncs/{rule}/publish",
                    json={"hash": plan["hash"], "selected": [0]},
                    headers=self.headers,
                )
                self.assertEqual(good.status_code, 200)
                publisher.return_value.publish.assert_called_once()
            self.assertTrue(list((self.root / "archive").rglob("*.ics")))

    def test_fetch_failure_is_redacted(self):
        self.login()
        source = self.client.post(
            "/api/v1/sources",
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
                "/api/v1/syncs", json={"source": source, "profile": "test"}, headers=self.headers
            ).json()["id"]
            with (
                patch("workoutbridge.web.read_calendar", side_effect=ValueError("PRIVATE")),
                patch("workoutbridge.web.GarminProvider.connect") as connect,
            ):
                self.app.state.poll_once()
                connect.assert_not_called()
            state = self.client.get("/api/v1/state")
            self.assertNotIn("PRIVATE", state.text)
            self.assertIn("failed", state.json()["syncs"][0]["error"])
            self.assertEqual(
                self.client.post(
                    f"/api/v1/syncs/{rule}/pause", json={"paused": True}, headers=self.headers
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
            self.client.post("/api/v1/login", json={"password": "incorrect"}, headers=self.headers)
        self.assertEqual(
            self.client.post(
                "/api/v1/login", json={"password": "a" * 40}, headers=self.headers
            ).status_code,
            429,
        )

    def test_login_body_is_bounded(self):
        self.assertEqual(
            self.client.post(
                "/api/v1/login", json={"password": "a" * 17000}, headers=self.headers
            ).status_code,
            413,
        )

    def test_progression_review_is_exact_account_scoped_durable_and_never_publishes(self):
        from dataclasses import replace

        from workoutbridge.calendar import Event

        rule, source, profile = self.automatic_rule()
        other = self.client.post(
            "/api/v1/syncs", json={"source": source, "profile": "other"}, headers=self.headers
        ).json()["id"]
        event = Event(
            source,
            "synthetic-progression",
            "",
            "2030-04-03",
            "Run: progression",
            "Workout: Run\n\nWarm up 1 miles\n4 mile progression from ~7:40 -> 7:00\nCool down 1 miles",
        )
        with (
            patch("workoutbridge.web.read_calendar", return_value=b"synthetic"),
            patch("workoutbridge.web.import_calendar", return_value=[event]) as imported,
            patch("workoutbridge.web.GarminProvider.connect") as connect,
        ):
            plan = self.client.post(
                f"/api/v1/syncs/{rule}/preview", json={}, headers=self.headers
            ).json()
            item = plan["items"][0]
            self.assertIn("error", item)
            self.assertEqual(len(item["suggestion"]["draft"]["steps"]), 4)
            endpoint = f"/api/v1/syncs/{rule}/review-progression"
            body = {"hash": plan["hash"], "index": 0, "choice": "pace_range_lap"}
            self.assertEqual(
                self.client.post(
                    endpoint, json={**body, "hash": "stale"}, headers=self.headers
                ).status_code,
                409,
            )
            self.assertEqual(
                self.client.post(
                    endpoint, json={**body, "index": True}, headers=self.headers
                ).status_code,
                422,
            )
            self.assertEqual(
                self.client.post(
                    endpoint, json={**body, "choice": "guess"}, headers=self.headers
                ).status_code,
                422,
            )
            response = self.client.post(endpoint, json=body, headers=self.headers)
            self.assertEqual(response.status_code, 200, response.text)
            plan = self.client.post(
                f"/api/v1/syncs/{rule}/preview", json={}, headers=self.headers
            ).json()
            self.assertNotIn("error", plan["items"][0])
            self.assertEqual(len(plan["items"][0]["draft"]["steps"]), 4)
            restarted = create_app(self.root, "https://bridge.example", "a" * 40, poll=False)
            self.addCleanup(restarted.state.close)
            restarted_client = TestClient(restarted, base_url="https://bridge.example")
            restarted_client.cookies.update(self.client.cookies)
            saved = restarted_client.post(
                f"/api/v1/syncs/{rule}/preview", json={}, headers=self.headers
            ).json()
            self.assertNotIn("error", saved["items"][0])
            other_plan = self.client.post(
                f"/api/v1/syncs/{other}/preview", json={}, headers=self.headers
            ).json()
            self.assertIn("error", other_plan["items"][0])
            # Change account even within the same rule: previous approval cannot follow it.
            profile["account_id"] = "456"
            changed = self.client.post(
                f"/api/v1/syncs/{rule}/preview", json={}, headers=self.headers
            ).json()
            self.assertIn("error", changed["items"][0])
            profile["account_id"] = "123"
            # Changed notes and a moved date both invalidate the exact-event review.
            for changed_event in [
                replace(event, description=event.description.replace("4 mile", "5 mile")),
                replace(event, date="2030-04-04"),
            ]:
                imported.return_value = [changed_event]
                changed = self.client.post(
                    f"/api/v1/syncs/{rule}/preview", json={}, headers=self.headers
                ).json()
                self.assertIn("error", changed["items"][0])
            connect.assert_not_called()
            from test_publishing import FakeGarmin

            provider = FakeGarmin()
            provider.account_id = "123"
            connect.return_value = provider
            imported.return_value = [event]
            plan = self.client.post(
                f"/api/v1/syncs/{rule}/preview", json={}, headers=self.headers
            ).json()
            for _ in range(2):
                result = self.client.post(
                    f"/api/v1/syncs/{rule}/publish",
                    json={"hash": plan["hash"], "selected": [0]},
                    headers=self.headers,
                )
                self.assertEqual(result.status_code, 200, result.text)
            self.assertEqual((provider.uploads, provider.schedules), (1, 1))
