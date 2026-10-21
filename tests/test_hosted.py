import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient

from workoutbridge.hosted import create_hosted_app


class HostedTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.sent = []
        self.app = create_hosted_app(
            Path(self.tmp.name),
            "https://bridge.example",
            send_email=lambda email, link: self.sent.append((email, link)),
            poll=False,
            admin_email="new@example.invalid",
        )
        self.store = self.app.state.accounts
        self.addCleanup(self.app.state.scheduler.close)
        self.headers = {"Origin": "https://bridge.example"}
        self.client = TestClient(self.app, base_url="https://bridge.example")

    def test_account_exposes_persistent_schedule_and_self_hosting_has_no_plan_limits(self):
        user, client = self.signed("schedule@example.invalid")
        self.app.state.scheduler.tick()
        account = client.get("/api/v1/account").json()
        self.assertEqual(account["schedule"]["interval"], 10800)
        self.assertEqual(account["schedule"]["status"], "waiting")
        self.assertEqual(
            client.post(
                "/api/v1/account/frequency", json={"seconds": 900}, headers=self.headers
            ).status_code,
            403,
        )
        self.assertEqual(
            client.post(
                "/api/v1/account/frequency", json={"seconds": 21600}, headers=self.headers
            ).status_code,
            200,
        )
        self.assertEqual(
            client.post("/api/v1/account/resume", json={}, headers=self.headers).status_code, 422
        )

    def signed(self, email):
        user = self.store.create_user(email)
        self.store.verify_email(user)
        self.store.add_credential(user, email, b"synthetic", 0)
        client = TestClient(self.app, base_url="https://bridge.example")
        client.cookies.set("prescribed_session", self.store.new_session(user))
        return user, client

    def test_email_verification_is_not_login_and_passkey_checks_origin_rp_and_uv(self):
        response = self.client.post(
            "/api/v1/auth/signup", json={"email": "new@example.invalid"}, headers=self.headers
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(self.sent), 1)
        token = self.sent[0][1].split("#verify=")[1]
        response = self.client.post(
            "/api/v1/auth/verify", json={"token": token}, headers=self.headers
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.client.get("/api/v1/state").status_code, 401)
        options = self.client.post("/api/v1/auth/register/options", json={}, headers=self.headers)
        self.assertEqual(options.status_code, 200)
        with patch(
            "workoutbridge.hosted.verify_registration_response",
            return_value=SimpleNamespace(
                credential_id=b"credential", credential_public_key=b"public", sign_count=0
            ),
        ) as verify:
            response = self.client.post(
                "/api/v1/auth/register/finish", json={"credential": {}}, headers=self.headers
            )
            self.assertEqual(response.status_code, 200)
            self.assertTrue(verify.call_args.kwargs["require_user_verification"])
            self.assertEqual(verify.call_args.kwargs["expected_origin"], "https://bridge.example")
            self.assertEqual(verify.call_args.kwargs["expected_rp_id"], "bridge.example")
        self.assertEqual(self.client.get("/api/v1/state").status_code, 200)
        self.assertTrue(self.client.get("/api/v1/account").json()["admin"])
        self.assertEqual(
            self.client.post(
                "/api/v1/auth/register/finish", json={"credential": {}}, headers=self.headers
            ).status_code,
            400,
        )

    def test_tenant_cannot_read_sources_or_modify_another_users_sync(self):
        a, ca = self.signed("a@example.invalid")
        b, cb = self.signed("b@example.invalid")
        source = ca.post(
            "/api/v1/sources",
            json={
                "name": "Private A",
                "format": "generic",
                "url": "https://calendar.google.com/calendar/ical/SYNTHETIC/basic.ics",
                "timezone": "UTC",
            },
            headers=self.headers,
        ).json()["id"]
        self.assertEqual(len(ca.get("/api/v1/state").json()["sources"]), 1)
        self.assertEqual(cb.get("/api/v1/state").json()["sources"], [])
        response = cb.post(
            f"/api/v1/syncs/{source}/pause", json={"paused": True}, headers=self.headers
        )
        self.assertEqual(response.status_code, 404)
        self.assertNotEqual(a, b)
        self.assertEqual(
            cb.post("/api/v1/login", json={"password": "a" * 40}, headers=self.headers).status_code,
            404,
        )

    def test_admin_view_and_gifts_reject_non_admin_and_are_audited(self):
        a, ca = self.signed("admin@example.invalid")
        b, cb = self.signed("member@example.invalid")
        self.assertEqual(cb.get("/api/v1/admin").status_code, 403)
        self.store.set_admin(a, True)
        response = ca.post(
            "/api/v1/admin/gifts",
            json={"user": b, "days": 30, "reason": "Early tester"},
            headers=self.headers,
        )
        self.assertEqual(response.status_code, 200)
        report = ca.get("/api/v1/admin").json()
        self.assertEqual(len(report["users"]), 2)
        self.assertEqual(len(report["grants"]), 1)
        self.assertEqual(len(report["audit"]), 2)
        self.assertEqual(report["audit"][0]["action"], "admin_view")
        self.assertNotIn("public_key", str(report))
        self.assertEqual(cb.get("/api/v1/account").json()["entitlements"]["plan"], "supporter")

    def test_csrf_host_body_limits_and_email_failure_are_safe(self):
        self.assertEqual(
            self.client.get("/health", headers={"host": "evil.example"}).status_code, 400
        )
        self.assertEqual(
            self.client.post(
                "/api/v1/auth/signup", json={"email": "bad@example.invalid"}
            ).status_code,
            403,
        )
        self.assertEqual(
            self.client.post(
                "/api/v1/auth/signup", json={"email": "x" * 20000}, headers=self.headers
            ).status_code,
            413,
        )
        app = create_hosted_app(
            Path(self.tmp.name) / "failure",
            "https://bridge.example",
            send_email=lambda *_: (_ for _ in ()).throw(ValueError("SECRET")),
            poll=False,
        )
        client = TestClient(app, base_url="https://bridge.example")
        response = client.post(
            "/api/v1/auth/signup", json={"email": "failure@example.invalid"}, headers=self.headers
        )
        self.assertEqual(response.status_code, 503)
        self.assertNotIn("SECRET", response.text)
