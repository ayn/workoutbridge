"""Account-bound COROS MCP transport with private, refreshable OAuth sessions."""

import fcntl
import json
import logging
import os
import tempfile
import threading
import time
from contextlib import contextmanager
from pathlib import Path

import httpx
from httpx_sse import EventSource

REGIONS = {region: f"https://mcp{region}.coros.com" for region in ("us", "eu", "cn")}
_HTTP_LOG_LOCK = threading.RLock()


@contextmanager
def private_http():
    with _HTTP_LOG_LOCK:
        previous = logging.root.manager.disable
        logging.disable(logging.CRITICAL)
        try:
            yield
        finally:
            logging.disable(previous)


class CorosClient:
    def __init__(self, session: Path, region: str, *, expected_account=None, http=None):
        if region not in REGIONS:
            raise ValueError("Unsupported COROS region")
        self.session = Path(session)
        self.issuer = REGIONS[region]
        self.http = http or httpx.Client(timeout=30, follow_redirects=False)
        self._sequence = 0
        with self.locked_session():
            self.token = self.load_session()
            if self.token.get("expires_at_epoch", 0) < time.time() + 120:
                self.refresh()
            identity = self.request("GET", "/userinfo", headers=self.headers()).json()
        subject = identity.get("sub") if isinstance(identity, dict) else None
        if not isinstance(subject, str) or not subject.strip() or len(subject) > 256:
            raise ValueError("COROS did not verify an account identity")
        self.account_id = f"coros:{region}:{subject}"
        if expected_account is not None and self.account_id != expected_account:
            raise ValueError("COROS account mismatch")

    @staticmethod
    def save_session(session, token):
        CorosClient.save_document(session, "token.json", token)

    @staticmethod
    def save_document(session, filename, token):
        session = Path(session)
        if session.is_symlink():
            raise ValueError("Session must not be a symlink")
        session.mkdir(mode=0o700, parents=True, exist_ok=True)
        session.chmod(0o700)
        fd, name = tempfile.mkstemp(dir=session, prefix=".token-")
        try:
            with os.fdopen(fd, "w") as handle:
                json.dump(token, handle)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(name, session / filename)
        finally:
            Path(name).unlink(missing_ok=True)

    @contextmanager
    def locked_session(self):
        if self.session.is_symlink():
            raise ValueError("Session must not be a symlink")
        fd = os.open(self.session / "session.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "r+") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            yield

    def load_session(self):
        fd = os.open(self.session / "token.json", os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(fd) as handle:
            if os.fstat(handle.fileno()).st_mode & 0o077:
                raise ValueError("COROS session must have private permissions")
            token = json.load(handle)
        if not isinstance(token, dict) or not isinstance(token.get("access_token"), str):
            raise ValueError("Invalid COROS session")
        return token

    @private_http()
    def request(self, method, path, **kwargs):
        try:
            response = self.http.request(method, self.issuer + path, **kwargs)
            response.raise_for_status()
            return response
        except httpx.HTTPError:
            raise ValueError("COROS request failed; outcome requires review") from None

    def headers(self):
        return {"Authorization": "Bearer " + self.token["access_token"]}

    def refresh(self):
        if not self.token.get("refresh_token") or not self.token.get("client_id"):
            raise ValueError("COROS authentication expired; reconnect")
        value = self.request(
            "POST",
            "/oauth2/token",
            data={
                "grant_type": "refresh_token",
                "client_id": self.token["client_id"],
                "refresh_token": self.token["refresh_token"],
            },
        ).json()
        if (
            not isinstance(value, dict)
            or not value.get("access_token")
            or not isinstance(value.get("expires_in"), (int, float))
        ):
            raise ValueError("COROS returned an invalid refreshed session")
        self.token = {**self.token, **value, "expires_at_epoch": time.time() + value["expires_in"]}
        self.save_session(self.session, self.token)

    def rpc(self, method, params):
        self._sequence += 1
        response = self.request(
            "POST",
            "/mcp",
            headers={
                **self.headers(),
                "Accept": "application/json, text/event-stream",
            },
            json={"jsonrpc": "2.0", "id": self._sequence, "method": method, "params": params},
        )
        if response.headers.get("content-type", "").startswith("text/event-stream"):
            values = [event.json() for event in EventSource(response).iter_sse() if event.data]
            values = [
                value
                for value in values
                if isinstance(value, dict) and value.get("id") == self._sequence
            ]
            if len(values) != 1:
                raise ValueError("Unexpected COROS stream response")
            value = values[0]
        else:
            value = response.json()
        if (
            not isinstance(value, dict)
            or value.get("id") != self._sequence
            or "error" in value
            or not isinstance(value.get("result"), dict)
        ):
            raise ValueError("Unexpected COROS RPC response; outcome requires review")
        return value["result"]

    def call_tool(self, name, arguments):
        self.rpc(
            "initialize",
            {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "WorkoutBridge", "version": "0.1.0"},
            },
        )
        result = self.rpc("tools/call", {"name": name, "arguments": arguments})
        if result.get("isError"):
            raise ValueError("COROS tool failed; outcome requires review")
        return result

    def close(self):
        self.http.close()
