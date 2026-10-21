import io
import json
import logging
import tempfile
import unittest
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import httpx

from workoutbridge.coros_auth import begin_login, finish_login


class CorosAuthTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.session = Path(self.directory.name) / "coros"
        self.authorized = False
        self.bad_state = False
        self.exchanges = 0
        self.http = httpx.Client(transport=httpx.MockTransport(self.respond))
        self.addCleanup(self.http.close)

    def respond(self, request):
        path = request.url.path
        if path == "/connect/register":
            registration = json.loads(request.content)
            self.assertEqual(registration["token_endpoint_auth_method"], "none")
            return httpx.Response(201, json={"client_id": "synthetic-client"})
        if path == "/api/v1/cli/login-sessions":
            return httpx.Response(
                201,
                json={
                    "sessionId": "synthetic",
                    "pollToken": "synthetic-poll",
                    "loginUrl": "https://mcpus.coros.com/cli/login/synthetic",
                },
            )
        if path.endswith("/claim"):
            self.assertEqual(request.headers["x-poll-token"], "synthetic-poll")
            return httpx.Response(
                200,
                json={"status": "authorized", "loginTicket": "synthetic-ticket"}
                if self.authorized
                else {"status": "pending"},
            )
        if path == "/oauth2/authorize":
            query = parse_qs(request.url.query.decode())
            self.assertEqual(query["code_challenge_method"], ["S256"])
            state = "wrong" if self.bad_state else query["state"][0]
            return httpx.Response(
                302,
                headers={
                    "location": "http://127.0.0.1:43123/callback?code=synthetic-code&state=" + state
                },
            )
        if path == "/oauth2/token":
            self.exchanges += 1
            form = parse_qs(request.content.decode())
            self.assertTrue(form["code_verifier"][0])
            return httpx.Response(
                200,
                json={
                    "access_token": "synthetic",
                    "refresh_token": "synthetic-refresh",
                    "expires_in": 3600,
                },
            )
        if path == "/userinfo":
            return httpx.Response(200, json={"sub": "synthetic-subject"})
        raise AssertionError(path)

    def test_browser_flow_pending_then_verified_session(self):
        result = begin_login(self.session, "us", http=self.http)
        self.assertEqual(urlparse(result["login_url"]).hostname, "mcpus.coros.com")
        self.assertIsNone(finish_login(self.session, http=self.http))
        self.authorized = True
        self.assertEqual(finish_login(self.session, http=self.http), "coros:us:synthetic-subject")
        self.assertFalse((self.session / "pending.json").exists())
        self.assertEqual((self.session / "token.json").stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.exchanges, 1)

    def test_state_mismatch_blocks_exchange(self):
        begin_login(self.session, "us", http=self.http)
        self.authorized = self.bad_state = True
        with self.assertRaises(ValueError):
            finish_login(self.session, http=self.http)
        self.assertEqual(self.exchanges, 0)

    def test_oauth_ticket_and_token_are_not_logged(self):
        output = io.StringIO()
        handler = logging.StreamHandler(output)
        logger = logging.getLogger("httpx")
        previous = logger.level
        logger.addHandler(handler)
        logger.setLevel(logging.DEBUG)
        try:
            begin_login(self.session, "us", http=self.http)
            self.authorized = True
            finish_login(self.session, http=self.http)
        finally:
            logger.removeHandler(handler)
            logger.setLevel(previous)
        self.assertNotIn("synthetic-ticket", output.getvalue())

    def test_existing_session_not_overwritten(self):
        begin_login(self.session, "us", http=self.http)
        with self.assertRaises(ValueError):
            begin_login(self.session, "us", http=self.http)

    def test_session_directory_reserved_before_network_requests(self):
        original = self.respond

        def reserved(request):
            self.assertTrue(self.session.is_dir())
            self.assertEqual(self.session.stat().st_mode & 0o777, 0o700)
            return original(request)

        begin_login(self.session, "us", http=httpx.Client(transport=httpx.MockTransport(reserved)))

    def test_reject_foreign_login_url(self):
        def foreign(request):
            if request.url.path == "/connect/register":
                return httpx.Response(201, json={"client_id": "synthetic"})
            return httpx.Response(
                201,
                json={
                    "sessionId": "test",
                    "pollToken": "test",
                    "loginUrl": "https://attacker.example/login",
                },
            )

        with self.assertRaises(ValueError):
            begin_login(
                self.session, "us", http=httpx.Client(transport=httpx.MockTransport(foreign))
            )
