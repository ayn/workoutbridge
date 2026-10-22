"""Private, single-owner server with explicitly enabled hourly publishing."""

import hashlib
import hmac
import json
import logging
import os
import re
import secrets
import sqlite3
import threading
import time
from contextlib import asynccontextmanager, contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4
from zoneinfo import ZoneInfo

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from .calendar import Event, import_calendar
from .cli import review_item
from .feed import calendar_feed_url, read_calendar
from .garmin import GarminProvider
from .prescriptions import normalize_finalsurge, normalize_workout
from .profiles import load_profile, profile_path
from .publishing import Publisher, digest
from .web_auth import GarminLogin

SESSION_SECONDS = 30 * 86400
API_PREFIX = "/api/v1"


def create_app(
    root: Path,
    origin: str,
    password: str,
    *,
    poll=True,
    config_root=None,
    claim_account=None,
    authorize_profile=None,
    authenticate_request=None,
    on_publication=None,
    vault=None,
    operation=None,
) -> FastAPI:
    if len(password) < 32 or urlsplit(origin).scheme not in ("https", "http"):
        raise ValueError("Set an origin and a random password of at least 32 characters")
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    root.chmod(0o700)
    database = root / "web.sqlite"
    fd = os.open(database, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    os.fchmod(fd, 0o600)
    os.close(fd)
    attempts = []
    operation = operation if operation is not None else threading.RLock()
    garmin_login = GarminLogin(
        operation, config_root=config_root, claim_account=claim_account, vault=vault
    )

    # Explicit roots, rather than changing os.environ, isolate concurrent tenants and login threads.
    def load(name):
        profile = (
            load_profile(name, config_root=config_root)
            if config_root is not None
            else load_profile(name)
        )
        if vault is not None:
            vault.restore(Path(profile["session_dir"]))
        return profile

    def path_for(name):
        return (
            profile_path(name, config_root=config_root)
            if config_root is not None
            else profile_path(name)
        )

    def permitted(profile):
        if authorize_profile is not None:
            authorize_profile(profile)

    @contextmanager
    def db():
        connection = sqlite3.connect(database)
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    with db() as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS objects (kind TEXT, id TEXT, body TEXT, PRIMARY KEY(kind,id))"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS owner_sessions (token_hash TEXT PRIMARY KEY, expires REAL)"
        )

    def session_hash(token):
        # Bind persistent sessions to the configured password without storing bearer tokens.
        return hmac.new(password.encode(), token.encode(), hashlib.sha256).hexdigest()

    def session_cookie(response, token):
        response.set_cookie(
            "wb_session",
            token,
            httponly=True,
            secure=origin.startswith("https:"),
            samesite="strict",
            max_age=SESSION_SECONDS,
        )

    def put(kind, key, value):
        with db() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO objects VALUES (?,?,?)", (kind, key, json.dumps(value))
            )

    def values(kind):
        with db() as conn:
            return [
                json.loads(row[0])
                for row in conn.execute("SELECT body FROM objects WHERE kind=?", (kind,))
            ]

    def get(kind, key):
        with db() as conn:
            row = conn.execute(
                "SELECT body FROM objects WHERE kind=? AND id=?", (kind, key)
            ).fetchone()
        if not row:
            raise HTTPException(404, "Not found")
        return json.loads(row[0])

    def stamp():
        return datetime.now(ZoneInfo("UTC")).isoformat()

    def preview(rule_id):
        record = {
            "id": uuid4().hex,
            "sync": rule_id,
            "at": stamp(),
            "status": "Feed check failed",
            "results": [],
        }
        try:
            plan = build_preview(rule_id)
        except Exception:
            put("history", record["id"], record)
            raise
        record.update(status="Checked successfully", upcoming_count=len(plan["items"]))
        put("history", record["id"], record)
        return plan

    def build_preview(rule_id):
        rule = get("sync", rule_id)
        source = get("source", rule["source"])
        profile = load(rule["profile"])
        permitted(profile)
        data = read_calendar(source["url"])
        folder = root / "archive" / source["id"]
        folder.mkdir(parents=True, exist_ok=True, mode=0o700)
        archive = folder / (hashlib.sha256(data).hexdigest() + ".ics")
        if not archive.exists():
            with archive.open("xb") as handle:
                os.fchmod(handle.fileno(), 0o600)
                handle.write(data)
        start = datetime.now(ZoneInfo(source["timezone"])).date()
        events = import_calendar(
            data,
            source=source["id"],
            timezone=source["timezone"],
            start=start,
            end=start + timedelta(days=15),
        )
        normalize = normalize_finalsurge if source["format"] == "finalsurge" else normalize_workout
        items = [review_item(profile["account_id"], normalize(event)) for event in events]
        plan = {"id": rule_id, "account": profile["account_id"], "items": items, "created": stamp()}
        plan["hash"] = digest(plan)
        put("plan", rule_id, plan)
        rule.update(last_preview=stamp(), error=None)
        put("sync", rule_id, rule)
        return plan

    def poll_once(rule_id=None):
        if not operation.acquire(blocking=False):
            return
        try:
            for rule in values("sync"):
                if rule_id is not None and rule["id"] != rule_id:
                    continue
                if rule.get("paused"):
                    continue
                try:
                    plan = preview(rule["id"])
                    rule = get("sync", rule["id"])
                    if not rule.get("automatic") or rule.get("auto_blocked"):
                        continue
                    if rule.get("auto_account") != plan["account"]:
                        rule.update(
                            auto_blocked=True,
                            error="Destination changed. Review automatic publishing.",
                        )
                        put("sync", rule["id"], rule)
                        continue
                    selected = [i for i, item in enumerate(plan["items"]) if "error" not in item]
                    if not selected:
                        continue
                    # Persist before any remote request: crashes must also stop unattended retries.
                    rule["auto_blocked"] = True
                    put("sync", rule["id"], rule)
                    try:
                        publish(rule["id"], {"hash": plan["hash"], "selected": selected})
                    except Exception:  # noqa: BLE001 - preserve the stop latch and redact remote errors.
                        rule["error"] = (
                            "Automatic publishing stopped. Reconcile history before re-enabling."
                        )
                    else:
                        rule.update(auto_blocked=False, last_publish=stamp(), error=None)
                    put("sync", rule["id"], rule)
                except Exception:  # noqa: BLE001 - private feed/session details must not leak.
                    rule["error"] = "Feed refresh failed. Check feed access and connection profile."
                    put("sync", rule["id"], rule)
        finally:
            operation.release()

    @asynccontextmanager
    async def lifespan(app):
        stop = threading.Event()

        def worker():
            while not stop.wait(3600):
                poll_once()

        thread = threading.Thread(target=worker, daemon=True)
        if poll:
            thread.start()
        yield
        stop.set()
        garmin_login.close()
        if poll:
            thread.join(timeout=35)

    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    app.state.poll_once = poll_once
    app.state.close = garmin_login.close
    app.state.operation = operation

    @app.middleware("http")
    async def protect(request: Request, call_next):
        authenticated_session = None
        if request.headers.get("host") != urlsplit(origin).netloc:
            return JSONResponse({"detail": "Invalid host"}, status_code=400)
        if request.url.path.startswith("/api/"):
            if not request.url.path.startswith(API_PREFIX + "/"):
                return JSONResponse(
                    {"detail": "Unsupported API version. Refresh the app to use /api/v1."},
                    status_code=404,
                )
            if request.method != "GET" and request.headers.get("origin") != origin:
                return JSONResponse({"detail": "Invalid origin"}, status_code=403)
            if authenticate_request is not None:
                if not authenticate_request(request):
                    return JSONResponse({"detail": "Sign in required"}, status_code=401)
                if request.url.path in (API_PREFIX + "/login", API_PREFIX + "/logout"):
                    return JSONResponse(
                        {"detail": "Use the embedding application's authentication"},
                        status_code=404,
                    )
            elif request.url.path != API_PREFIX + "/login":
                token = request.cookies.get("wb_session", "")
                authenticated_session = session_hash(token)
                with db() as conn:
                    session = conn.execute(
                        "SELECT expires FROM owner_sessions WHERE token_hash=?",
                        (authenticated_session,),
                    ).fetchone()
                if not session or session[0] <= time.time():
                    return JSONResponse({"detail": "Sign in required"}, status_code=401)
            if request.method == "POST":
                # Bound actual bodies, including requests without Content-Length.
                size = 0
                chunks = []
                async for chunk in request.stream():
                    size += len(chunk)
                    if size > 16_384:
                        return JSONResponse({"detail": "Request too large"}, status_code=413)
                    chunks.append(chunk)
                request._body = b"".join(chunks)
        response = await call_next(request)
        if (
            authenticated_session
            and request.url.path != API_PREFIX + "/logout"
            and response.status_code < 400
        ):
            now = time.time()
            with db() as conn:
                renewed = conn.execute(
                    "UPDATE owner_sessions SET expires=? WHERE token_hash=? AND expires>?",
                    (now + SESSION_SECONDS, authenticated_session, now),
                ).rowcount
            # Do not recreate a session revoked by a concurrent logout.
            if renewed:
                session_cookie(response, token)
        response.headers.update(
            {
                "Cache-Control": "no-store",
                "X-Content-Type-Options": "nosniff",
                "Referrer-Policy": "no-referrer",
                "Content-Security-Policy": "default-src 'self'; style-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'; form-action 'self'",
            }
        )
        return response

    @app.exception_handler(Exception)
    async def redacted_error(request, exc):
        return JSONResponse(
            {
                "detail": "Operation failed. No automatic retry; inspect sync status before publishing again."
            },
            status_code=400,
        )

    @app.get("/health")
    def health():
        with db() as conn:
            conn.execute("SELECT 1").fetchone()
        return {"status": "ok"}

    @app.post(API_PREFIX + "/login")
    def login(body: dict):
        now = time.time()
        attempts[:] = [t for t in attempts if t > now - 300]
        if len(attempts) >= 10:
            raise HTTPException(429, "Wait five minutes before signing in again")
        attempts.append(now)
        supplied = body.get("password")
        if not isinstance(supplied, str) or not secrets.compare_digest(
            supplied.encode(), password.encode()
        ):
            raise HTTPException(401, "Incorrect password")
        attempts.clear()
        token = secrets.token_urlsafe(32)
        with db() as conn:
            conn.execute("DELETE FROM owner_sessions WHERE expires<=?", (now,))
            conn.execute(
                "DELETE FROM owner_sessions WHERE token_hash IN "
                "(SELECT token_hash FROM owner_sessions ORDER BY expires DESC LIMIT -1 OFFSET 99)"
            )
            conn.execute(
                "INSERT INTO owner_sessions VALUES (?,?)",
                (session_hash(token), now + SESSION_SECONDS),
            )
        response = JSONResponse({"ok": True})
        session_cookie(response, token)
        return response

    @app.post(API_PREFIX + "/logout")
    def logout(request: Request):
        with db() as conn:
            conn.execute(
                "DELETE FROM owner_sessions WHERE token_hash=?",
                (session_hash(request.cookies.get("wb_session", "")),),
            )
        response = JSONResponse({"ok": True})
        response.delete_cookie("wb_session")
        return response

    @app.get(API_PREFIX + "/state")
    def state():
        connections = []
        for path in sorted(path_for("placeholder").parent.glob("*.json")):
            try:
                profile = load(path.stem)
                connections.append(
                    {
                        "id": path.stem,
                        "provider": "COROS"
                        if profile.get("destination") == "coros"
                        else "Garmin Connect",
                        "account": profile["account_id"],
                    }
                )
            except ValueError:
                continue
        sources = [
            {key: value for key, value in source.items() if key != "url"}
            for source in values("source")
        ]
        return {
            "sources": sources,
            "connections": connections,
            "syncs": values("sync"),
            "plans": values("plan"),
            "history": sorted(values("history"), key=lambda entry: entry["at"])[-50:],
        }

    @app.post(API_PREFIX + "/coros/login")
    def coros_login_start(body: dict):
        from .coros_auth import begin_login

        if not origin.startswith("https://"):
            raise HTTPException(403, "COROS sign-in requires HTTPS")
        permitted({"destination": "coros"})
        if not operation.acquire(blocking=False):
            raise HTTPException(409, "Another operation is running")
        try:
            name = body.get("profile", "")
            path = path_for(name)
            if path.exists() and load(name)["destination"] != "coros":
                raise ValueError("Profile belongs to another provider")
            recent = [job for job in values("coros_login") if job["created"] > time.time() - 900]
            if len(recent) >= 3:
                raise ValueError("Sign-in rate limit")
            key = uuid4().hex
            session = (
                vault.new_path("coros")
                if vault is not None
                else path.parent.parent / "sessions" / ("coros-" + key)
            )
            put(
                "coros_login",
                key,
                {
                    "id": key,
                    "profile": name,
                    "session": str(session),
                    "created": time.time(),
                    "status": "starting",
                },
            )
            result = begin_login(session, body.get("region", "us"))
            if vault is not None:
                vault.save(session)
            put(
                "coros_login",
                key,
                {
                    "id": key,
                    "profile": name,
                    "session": str(session),
                    "created": time.time(),
                    "status": "pending",
                },
            )
            return {"id": key, "status": "pending", **result}
        except Exception:  # noqa: BLE001 - OAuth details must remain private.
            raise HTTPException(
                409,
                "COROS sign-in could not start. Check profile, region and connection; three attempts per 15 minutes are allowed.",
            ) from None
        finally:
            operation.release()

    @app.post(API_PREFIX + "/coros/login/finish")
    def coros_login_finish(body: dict):
        from .coros_auth import finish_login
        from .profiles import authenticate_profile

        if not origin.startswith("https://"):
            raise HTTPException(403, "COROS sign-in requires HTTPS")
        if not operation.acquire(blocking=False):
            raise HTTPException(409, "Another operation is running")
        try:
            job = get("coros_login", body.get("id", ""))
            if vault is not None:
                vault.restore(Path(job["session"]))
            if job["status"] == "complete":
                return {"status": "complete", "profile": job["profile"]}
            if job["status"] != "pending" or job["created"] < time.time() - 600:
                raise ValueError("Login expired")

            class Pending(Exception):
                pass

            def authenticate(session):
                account = finish_login(session)
                if account is None:
                    raise Pending
                return account

            try:
                authenticate_profile(
                    job["profile"],
                    Path(job["session"]),
                    destination="coros",
                    authenticator=authenticate,
                    **(
                        {"config_root": config_root, "claim_account": claim_account}
                        if config_root is not None
                        else {}
                    ),
                )
                if vault is not None:
                    vault.save(Path(job["session"]))
            except Pending:
                return {"status": "pending"}
            job["status"] = "complete"
            put("coros_login", job["id"], job)
            return {"status": "complete", "profile": job["profile"]}
        except Exception:  # noqa: BLE001 - do not return OAuth responses.
            raise HTTPException(
                409,
                "COROS sign-in could not finish. Complete browser authorization or restart sign-in.",
            ) from None
        finally:
            operation.release()

    @app.get(API_PREFIX + "/garmin/login")
    def garmin_login_status():
        return garmin_login.status()

    @app.post(API_PREFIX + "/garmin/login")
    def garmin_login_start(body: dict):
        if not origin.startswith("https://"):
            raise HTTPException(403, "Garmin sign-in requires HTTPS")
        permitted({"destination": "garmin"})
        try:
            return garmin_login.start(
                body.get("profile", ""), body.get("email"), body.get("password")
            )
        except (ValueError, TypeError):
            raise HTTPException(
                409,
                "Check profile and credentials; only one login and three attempts per 15 minutes are allowed",
            ) from None

    @app.post(API_PREFIX + "/garmin/login/mfa")
    def garmin_login_code(body: dict):
        if not origin.startswith("https://"):
            raise HTTPException(403, "Garmin sign-in requires HTTPS")
        try:
            return garmin_login.submit(body.get("id"), body.get("code"))
        except ValueError:
            raise HTTPException(
                409, "Use the current login and a six-digit verification code"
            ) from None

    @app.post(API_PREFIX + "/garmin/login/cancel")
    def garmin_login_cancel(body: dict):
        try:
            garmin_login.cancel(body.get("id"))
            return {"ok": True}
        except ValueError:
            raise HTTPException(409, "No matching login") from None

    @app.post(API_PREFIX + "/sources")
    def source(body: dict):
        url = body.get("url", "")
        if not isinstance(url, str) or len(url) > 2048:
            raise HTTPException(422, "Invalid feed URL")
        try:
            url = calendar_feed_url(url)
            parsed = urlsplit(url)
        except ValueError:
            raise HTTPException(
                422, "Use a supported calendar sharing link or an HTTPS iCal feed"
            ) from None
        if (
            parsed.scheme != "https"
            or not (
                parsed.hostname in ("log.finalsurge.com", "calendar.google.com", "ics.teamup.com")
                or re.fullmatch(r"p[0-9]+-caldav\.icloud\.com", parsed.hostname or "")
            )
            or parsed.port not in (None, 443)
            or parsed.username
            or parsed.password
            or parsed.fragment
        ):
            raise HTTPException(
                422, "Use a Final Surge, Google Calendar, public iCloud or Teamup feed"
            )
        name = body.get("name", "")
        if (
            not isinstance(name, str)
            or not 1 <= len(name.strip()) <= 80
            or body.get("format") not in ("finalsurge", "generic")
        ):
            raise HTTPException(422, "Enter a source name and format")
        try:
            ZoneInfo(body.get("timezone", ""))
        except (ValueError, KeyError, TypeError):
            raise HTTPException(422, "Invalid timezone") from None
        if len(values("source")) >= 20:
            raise HTTPException(409, "Source limit reached")
        for existing in values("source"):
            try:
                same = calendar_feed_url(existing["url"]) == url
            except ValueError:
                same = False
            if same:
                raise HTTPException(409, "This feed already exists")
        key = uuid4().hex
        put(
            "source",
            key,
            {
                "id": key,
                "name": name.strip(),
                "url": url,
                "format": body["format"],
                "timezone": body["timezone"],
            },
        )
        return {"id": key}

    @app.post(API_PREFIX + "/syncs")
    def sync(body: dict):
        get("source", body.get("source"))
        permitted(load(body.get("profile", "")))
        if any(
            r["source"] == body["source"] and r["profile"] == body["profile"]
            for r in values("sync")
        ):
            raise HTTPException(409, "Sync already exists")
        key = uuid4().hex
        put(
            "sync",
            key,
            {
                "id": key,
                "source": body["source"],
                "profile": body["profile"],
                "last_preview": None,
                "error": None,
            },
        )
        return {"id": key}

    @app.post(API_PREFIX + "/syncs/{key}/preview")
    def refresh(key: str):
        if not operation.acquire(blocking=False):
            raise HTTPException(409, "Another operation is running")
        try:
            return preview(key)
        except Exception:  # noqa: BLE001 - do not reflect URL-bearing errors.
            rule = get("sync", key)
            rule["error"] = "Feed refresh failed. Check feed access and connection profile."
            put("sync", key, rule)
            raise HTTPException(400, rule["error"]) from None
        finally:
            operation.release()

    @app.post(API_PREFIX + "/syncs/{key}/pause")
    def pause(key: str, body: dict):
        if type(body.get("paused")) is not bool:
            raise HTTPException(422, "Choose a paused state")
        if not operation.acquire(blocking=False):
            raise HTTPException(409, "Another operation is running")
        try:
            rule = get("sync", key)
            rule["paused"] = body["paused"]
            put("sync", key, rule)
            return {"ok": True}
        finally:
            operation.release()

    @app.post(API_PREFIX + "/syncs/{key}/automatic")
    def automatic(key: str, body: dict):
        if type(body.get("enabled")) is not bool:
            raise HTTPException(422, "Choose an automatic publishing state")
        if not operation.acquire(blocking=False):
            raise HTTPException(409, "Another operation is running")
        try:
            rule = get("sync", key)
            if body["enabled"]:
                profile = load(rule["profile"])
                permitted(profile)
                if body.get("account") != profile["account_id"]:
                    raise HTTPException(409, "Confirm the destination account")
                if rule.get("auto_blocked") and body.get("acknowledge_review") is not True:
                    raise HTTPException(
                        409, "Reconcile history and acknowledge review before resuming"
                    )
                rule.update(auto_account=profile["account_id"], auto_blocked=False, error=None)
            rule["automatic"] = body["enabled"]
            put("sync", key, rule)
            if body["enabled"]:
                poll_once(key)
            return {"ok": True}
        finally:
            operation.release()

    @app.post(API_PREFIX + "/syncs/{key}/publish")
    def publish(key: str, body: dict):
        if not operation.acquire(blocking=False):
            raise HTTPException(409, "Another operation is running")
        try:
            rule = get("sync", key)
            plan = get("plan", key)
            if rule.get("paused"):
                raise HTTPException(409, "Resume this sync before publishing")
            profile = load(rule["profile"])
            permitted(profile)
            selected = body.get("selected", [])
            if (
                body.get("hash") != plan["hash"]
                or profile["account_id"] != plan["account"]
                or datetime.fromisoformat(plan["created"])
                < datetime.now(ZoneInfo("UTC")) - timedelta(hours=24)
            ):
                raise HTTPException(409, "Preview changed or expired. Refresh and review again")
            if (
                not isinstance(selected, list)
                or not selected
                or len(selected) > 500
                or any(type(i) is not int or i < 0 or i >= len(plan["items"]) for i in selected)
                or len(set(selected)) != len(selected)
            ):
                raise HTTPException(422, "Select valid workouts")
            items = [plan["items"][i] for i in selected]
            if any("error" in item for item in items):
                raise HTTPException(409, "Unresolved workouts cannot be published")
            results = []
            if rule.get("automatic"):
                rule["auto_blocked"] = True
                put("sync", key, rule)
            previous = logging.root.manager.disable
            logging.disable(logging.CRITICAL)
            coros_client = None
            try:
                if profile.get("destination") == "coros":
                    from .coros_client import CorosClient
                    from .coros_publishing import CorosEventPublisher

                    coros_client = CorosClient(
                        Path(profile["session_dir"]),
                        profile["account_id"].split(":")[1],
                        expected_account=profile["account_id"],
                    )
                    publisher = CorosEventPublisher(Path(profile["state_db"]), coros_client)
                else:
                    provider = GarminProvider.connect(
                        Path(profile["session_dir"]), expected_account=profile["account_id"]
                    )
                    publisher = Publisher(Path(profile["state_db"]), provider)
                for item in items:
                    wid = publisher.publish(Event(**item["event"]), item["approval"])
                    results.append(
                        {
                            "title": item["event"]["title"],
                            "date": item["event"]["date"],
                            "workout_id": wid,
                        }
                    )
            except Exception:  # noqa: BLE001 - remote outcome may be uncertain; retain receipts.
                record = {
                    "id": uuid4().hex,
                    "sync": key,
                    "at": stamp(),
                    "status": "Review required",
                    "results": results,
                }
                put("history", record["id"], record)
                raise HTTPException(
                    409,
                    "Publish stopped. Some writes may have succeeded. Receipts preserved; reconcile before retrying",
                ) from None
            finally:
                if coros_client is not None:
                    coros_client.close()
                if vault is not None:
                    vault.save(Path(profile["session_dir"]))
                logging.disable(previous)
            record = {
                "id": uuid4().hex,
                "sync": key,
                "at": stamp(),
                "status": "Verified",
                "results": results,
            }
            put("history", record["id"], record)
            if on_publication is not None and results:
                on_publication()
            if rule.get("automatic"):
                rule.update(auto_blocked=False, last_publish=stamp())
                put("sync", key, rule)
            return record
        finally:
            operation.release()

    def run_action(action, key, body):
        if action == "preview":
            return refresh(key)
        if action == "publish":
            return publish(key, body)
        if action == "automatic":
            return automatic(key, body)
        raise ValueError("Unsupported application action")

    app.state.run_action = run_action
    static = Path(os.environ.get("WORKOUTBRIDGE_STATIC_DIR", "web/dist"))
    if static.is_dir():
        app.mount("/", StaticFiles(directory=static, html=True), name="ui")
    return app


def application():
    os.umask(0o077)
    # Avoid third-party logs containing session or private feed details.
    logging.disable(logging.CRITICAL)
    return create_app(
        Path(os.environ["WORKOUTBRIDGE_DATA_DIR"]),
        os.environ["WORKOUTBRIDGE_ORIGIN"],
        Path(os.environ["WORKOUTBRIDGE_PASSWORD_FILE"]).read_text().strip(),
    )
