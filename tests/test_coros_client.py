import json
import tempfile
import unittest
from pathlib import Path

import httpx

from workoutbridge.coros_client import CorosClient


class CorosClientTests(unittest.TestCase):
    def test_validates_identity_and_calls_tool_without_retrying(self):
        calls = []

        def respond(request):
            calls.append(request)
            self.assertEqual(request.headers["authorization"], "Bearer synthetic-token")
            if request.url.path == "/userinfo":
                return httpx.Response(200, json={"sub": "synthetic-subject"})
            body = json.loads(request.content)
            result = (
                {"protocolVersion": "2025-06-18", "capabilities": {}}
                if body["method"] == "initialize"
                else {"content": [{"type": "text", "text": "test"}]}
            )
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": body["id"], "result": result})

        with tempfile.TemporaryDirectory() as directory:
            session = Path(directory) / "session"
            CorosClient.save_session(
                session,
                {
                    "access_token": "synthetic-token",
                    "expires_at_epoch": 9999999999,
                    "client_id": "test",
                },
            )
            client = CorosClient(
                session, "us", http=httpx.Client(transport=httpx.MockTransport(respond))
            )
            self.assertEqual(client.account_id, "coros:us:synthetic-subject")
            self.assertEqual(
                client.call_tool("queryTrainingSchedule", {"startDate": "20261022"})["content"][0][
                    "text"
                ],
                "test",
            )
            self.assertEqual(len(calls), 3)
            self.assertEqual((session / "token.json").stat().st_mode & 0o777, 0o600)

    def test_account_mismatch_blocks_tools(self):
        def respond(request):
            self.assertEqual(request.url.path, "/userinfo")
            return httpx.Response(200, json={"sub": "other"})

        with tempfile.TemporaryDirectory() as directory:
            session = Path(directory) / "session"
            CorosClient.save_session(
                session, {"access_token": "synthetic", "expires_at_epoch": 9999999999}
            )
            with self.assertRaises(ValueError):
                CorosClient(
                    session,
                    "us",
                    expected_account="coros:us:test",
                    http=httpx.Client(transport=httpx.MockTransport(respond)),
                )

    def test_write_timeout_is_not_retried(self):
        writes = []

        def respond(request):
            if request.url.path == "/userinfo":
                return httpx.Response(200, json={"sub": "test"})
            body = json.loads(request.content)
            if body["method"] == "initialize":
                return httpx.Response(200, json={"jsonrpc": "2.0", "id": body["id"], "result": {}})
            writes.append(body)
            raise httpx.ReadTimeout("synthetic")

        with tempfile.TemporaryDirectory() as directory:
            session = Path(directory) / "session"
            CorosClient.save_session(
                session, {"access_token": "synthetic", "expires_at_epoch": 9999999999}
            )
            client = CorosClient(
                session, "us", http=httpx.Client(transport=httpx.MockTransport(respond))
            )
            with self.assertRaises(ValueError):
                client.call_tool("createScheduledWorkout", {})
            self.assertEqual(len(writes), 1)

    def test_untrusted_region_rejected(self):
        with self.assertRaises(ValueError):
            CorosClient(Path("/tmp/unused"), "https://untrusted.example")

    def test_tool_error_does_not_expose_remote_secrets(self):
        def respond(request):
            if request.url.path == "/userinfo":
                return httpx.Response(200, json={"sub": "test"})
            body = json.loads(request.content)
            return httpx.Response(
                200,
                json={
                    "jsonrpc": "2.0",
                    "id": body["id"],
                    "result": {"isError": True, "content": [{"type": "text", "text": "secret"}]},
                },
            )

        with tempfile.TemporaryDirectory() as directory:
            session = Path(directory) / "session"
            CorosClient.save_session(
                session, {"access_token": "synthetic", "expires_at_epoch": 9999999999}
            )
            client = CorosClient(
                session, "us", http=httpx.Client(transport=httpx.MockTransport(respond))
            )
            with self.assertRaisesRegex(ValueError, "^COROS tool failed; outcome requires review$"):
                client.call_tool("createScheduledWorkout", {})
