"""Private, single-owner review server. Never schedules unattended publication."""

import hashlib
import json
import logging
import os
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
from .feed import read_calendar
from .garmin import GarminProvider
from .prescriptions import normalize_finalsurge, normalize_workout
from .profiles import load_profile, profile_path
from .publishing import Publisher, digest


def create_app(root: Path, origin: str, password: str, *, poll=True) -> FastAPI:
    if len(password) < 32 or urlsplit(origin).scheme not in ("https", "http"):
        raise ValueError("Set an origin and a random password of at least 32 characters")
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    root.chmod(0o700)
    database = root / "web.sqlite"
    fd = os.open(database, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    os.fchmod(fd, 0o600)
    os.close(fd)
    sessions = {}
    attempts = []
    operation = threading.Lock()

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
        rule = get("sync", rule_id)
        source = get("source", rule["source"])
        profile = load_profile(rule["profile"])
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

    def poll_once():
        if not operation.acquire(blocking=False):
            return
        try:
            for rule in values("sync"):
                if rule.get("paused"):
                    continue
                try:
                    preview(rule["id"])
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
        if poll:
            thread.join(timeout=35)

    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    app.state.poll_once = poll_once

    @app.middleware("http")
    async def protect(request: Request, call_next):
        if request.headers.get("host") != urlsplit(origin).netloc:
            return JSONResponse({"detail": "Invalid host"}, status_code=400)
        if request.url.path.startswith("/api/"):
            if request.method != "GET" and request.headers.get("origin") != origin:
                return JSONResponse({"detail": "Invalid origin"}, status_code=403)
            if request.url.path != "/api/login":
                token = request.cookies.get("wb_session", "")
                if sessions.get(token, 0) < time.time():
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

    @app.post("/api/login")
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
        for key in list(sessions):
            if sessions[key] < now:
                del sessions[key]
        if len(sessions) >= 100:
            sessions.clear()
        token = secrets.token_urlsafe(32)
        sessions[token] = now + 43200
        response = JSONResponse({"ok": True})
        response.set_cookie(
            "wb_session",
            token,
            httponly=True,
            secure=origin.startswith("https:"),
            samesite="strict",
            max_age=43200,
        )
        return response

    @app.post("/api/logout")
    def logout(request: Request):
        sessions.pop(request.cookies.get("wb_session", ""), None)
        response = JSONResponse({"ok": True})
        response.delete_cookie("wb_session")
        return response

    @app.get("/api/state")
    def state():
        connections = []
        for path in sorted(profile_path("placeholder").parent.glob("*.json")):
            try:
                profile = load_profile(path.stem)
                connections.append(
                    {
                        "id": path.stem,
                        "provider": "Garmin Connect",
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
            "history": values("history")[-50:],
        }

    @app.post("/api/sources")
    def source(body: dict):
        url = body.get("url", "")
        if not isinstance(url, str) or len(url) > 2048:
            raise HTTPException(422, "Invalid feed URL")
        parsed = urlsplit(url)
        if (
            parsed.scheme != "https"
            or parsed.hostname not in ("log.finalsurge.com", "calendar.google.com")
            or parsed.port not in (None, 443)
            or parsed.username
            or parsed.password
            or parsed.fragment
        ):
            raise HTTPException(422, "Use a Final Surge or Google Calendar HTTPS feed")
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
        if any(s["url"] == url for s in values("source")):
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

    @app.post("/api/syncs")
    def sync(body: dict):
        get("source", body.get("source"))
        load_profile(body.get("profile", ""))
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

    @app.post("/api/syncs/{key}/preview")
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

    @app.post("/api/syncs/{key}/pause")
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

    @app.post("/api/syncs/{key}/publish")
    def publish(key: str, body: dict):
        if not operation.acquire(blocking=False):
            raise HTTPException(409, "Another operation is running")
        try:
            rule = get("sync", key)
            plan = get("plan", key)
            if rule.get("paused"):
                raise HTTPException(409, "Resume this sync before publishing")
            profile = load_profile(rule["profile"])
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
            previous = logging.root.manager.disable
            logging.disable(logging.CRITICAL)
            try:
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
                logging.disable(previous)
            record = {
                "id": uuid4().hex,
                "sync": key,
                "at": stamp(),
                "status": "Verified",
                "results": results,
            }
            put("history", record["id"], record)
            return record
        finally:
            operation.release()

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
