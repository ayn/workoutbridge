"""COROS browser authorization through its documented public OAuth gateway."""

import base64
import hashlib
import json
import os
import secrets
import time
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

import httpx

from .coros_client import REGIONS, CorosClient, private_http

REDIRECT = "http://127.0.0.1:43123/callback"


@private_http()
def begin_login(session: Path, region: str, *, http=None):
    session = Path(session)
    if region not in REGIONS or session.exists():
        raise ValueError("Choose a COROS region and a new private session directory")
    session.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    session.mkdir(mode=0o700)
    issuer = REGIONS[region]
    owned_http = http is None
    http = http or httpx.Client(timeout=30, follow_redirects=False)
    try:

        def post(path, value):
            response = http.post(issuer + path, json=value)
            response.raise_for_status()
            return response.json()

        client_id = post(
            "/connect/register",
            {
                "client_name": "WorkoutBridge",
                "redirect_uris": [REDIRECT],
                "grant_types": ["authorization_code", "refresh_token"],
                "response_types": ["code"],
                "scope": "openid mcp.tools offline_access",
                "token_endpoint_auth_method": "none",
            },
        ).get("client_id")
        if not isinstance(client_id, str) or not client_id:
            raise ValueError("COROS client registration failed")
        login = post("/api/v1/cli/login-sessions", {"clientId": client_id})
        for key in ("sessionId", "pollToken", "loginUrl"):
            if not isinstance(login.get(key), str) or not login[key]:
                raise ValueError("Invalid COROS browser login response")
        parsed = urlparse(login["loginUrl"])
        if parsed.scheme != "https" or parsed.netloc != urlparse(issuer).netloc:
            raise ValueError("Untrusted COROS browser login URL")
        verifier = secrets.token_urlsafe(48)
        challenge = (
            base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
            .rstrip(b"=")
            .decode()
        )
        pending = {
            "region": region,
            "client_id": client_id,
            "session_id": login["sessionId"],
            "poll_token": login["pollToken"],
            "verifier": verifier,
            "challenge": challenge,
            "state": secrets.token_urlsafe(32),
            "expires": time.time() + 600,
        }
        CorosClient.save_document(session, "pending.json", pending)
        return {"login_url": login["loginUrl"], "expires_in": 600}
    except httpx.HTTPError:
        raise ValueError("COROS browser login could not start") from None
    finally:
        if owned_http:
            http.close()


@private_http()
def finish_login(session: Path, *, http=None):
    session = Path(session)
    owned_http = http is None
    http = http or httpx.Client(timeout=30, follow_redirects=False)
    try:
        fd = os.open(session / "pending.json", os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(fd) as handle:
            if os.fstat(handle.fileno()).st_mode & 0o077:
                raise ValueError("COROS pending login must be private")
            pending = json.load(handle)
        if pending["expires"] < time.time() or pending["region"] not in REGIONS:
            raise ValueError("COROS browser login expired")
        issuer = REGIONS[pending["region"]]
        response = http.post(
            issuer + "/api/v1/cli/login-sessions/" + pending["session_id"] + "/claim",
            headers={"X-Poll-Token": pending["poll_token"]},
        )
        response.raise_for_status()
        claim = response.json()
        if claim.get("status") == "pending":
            return None
        if claim.get("status") != "authorized" or not claim.get("loginTicket"):
            raise ValueError("COROS browser login expired or was cancelled")
        query = {
            "response_type": "code",
            "client_id": pending["client_id"],
            "redirect_uri": REDIRECT,
            "scope": "openid mcp.tools offline_access",
            "code_challenge": pending["challenge"],
            "code_challenge_method": "S256",
            "resource": issuer + "/mcp",
            "state": pending["state"],
            "login_ticket": claim["loginTicket"],
        }
        response = http.get(
            issuer + "/oauth2/authorize?" + urlencode(query), follow_redirects=False
        )
        if response.status_code not in (302, 303):
            raise ValueError("COROS did not authorize the browser session")
        callback = urlparse(response.headers.get("location", ""))
        if callback._replace(query="", fragment="").geturl() != REDIRECT:
            raise ValueError("Unexpected COROS authorization callback")
        values = parse_qs(callback.query)
        if values.get("state") != [pending["state"]] or len(values.get("code", [])) != 1:
            raise ValueError("COROS authorization state mismatch")
        response = http.post(
            issuer + "/oauth2/token",
            data={
                "grant_type": "authorization_code",
                "client_id": pending["client_id"],
                "code": values["code"][0],
                "redirect_uri": REDIRECT,
                "code_verifier": pending["verifier"],
            },
        )
        response.raise_for_status()
        token = response.json()
        if not isinstance(token.get("access_token"), str) or not isinstance(
            token.get("expires_in"), (int, float)
        ):
            raise ValueError("Invalid COROS OAuth response")
        token.update(
            client_id=pending["client_id"], expires_at_epoch=time.time() + token["expires_in"]
        )
        CorosClient.save_session(session, token)
        client = CorosClient(session, pending["region"], http=http)
        (session / "pending.json").unlink()
        return client.account_id
    except httpx.HTTPError:
        raise ValueError("COROS browser login failed; restart sign-in") from None
    finally:
        if owned_http:
            http.close()
