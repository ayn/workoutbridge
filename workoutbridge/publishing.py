"""Durable publishing intents. Uncertain remote outcomes fail closed."""

import fcntl
import hashlib
import json
import math
import os
import sqlite3
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path

from .calendar import Event
from .garmin import workout_payload
from .parser import parse


class ReviewRequired(ValueError):
    """A human must resolve approval, overlap, or an uncertain remote write."""


def digest(value) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def event_key(account: str, event: Event) -> str:
    return digest([account, event.source, event.uid, event.recurrence_id])


def event_payload(event: Event) -> dict:
    if event.cancelled:
        raise ReviewRequired("Cancelled event requires manual reconciliation")
    return workout_payload(event.title, event.description, parse(event.prescription))


def approval_token(account: str, event: Event) -> str:
    return digest([account, asdict(event), event_payload(event)])


def matches(expected, actual) -> bool:
    """Compare our fields, tolerating server-added IDs and float rounding."""
    if isinstance(expected, dict):
        return isinstance(actual, dict) and all(
            key in actual and matches(value, actual[key]) for key, value in expected.items()
        )
    if isinstance(expected, list):
        return (
            isinstance(actual, list)
            and len(expected) == len(actual)
            and all(matches(a, b) for a, b in zip(expected, actual))
        )
    if isinstance(expected, (int, float)) and not isinstance(expected, bool):
        return isinstance(actual, (int, float)) and math.isclose(
            expected, actual, rel_tol=1e-6, abs_tol=1e-6
        )
    return expected == actual


class Publisher:
    def __init__(self, database: Path, provider):
        self.database = Path(database)
        self.provider = provider

    @contextmanager
    def locked_database(self):
        self.database.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        # A process-held lock has no lease expiry during a slow remote request.
        # All publishers must share this database path; separate hosts are not supported.
        lock_path = self.database.with_suffix(self.database.suffix + ".lock")
        fd = os.open(lock_path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "r+") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise ReviewRequired("Another publisher is active; retry later") from exc
            fd = os.open(self.database, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
            os.fchmod(fd, 0o600)
            os.close(fd)
            db = sqlite3.connect(self.database)
            try:
                db.execute("PRAGMA synchronous=FULL")
                db.execute(
                    "CREATE TABLE IF NOT EXISTS publications "
                    "(identity TEXT PRIMARY KEY, record TEXT NOT NULL)"
                )
                db.commit()
                yield db
            finally:
                db.close()

    def publish(self, event: Event, approved: str) -> str:
        account = self.provider.account_id
        if not account or approved != approval_token(account, event):
            raise ReviewRequired("Review and approve this exact account and prescription")
        payload = event_payload(event)
        content_hash = digest(payload)
        key = event_key(account, event)
        marker = f"[WorkoutBridge:{key}]"
        payload["description"] = f"{payload['description']}\n\n{marker}".strip()

        with self.locked_database() as db:

            def save(record):
                db.execute(
                    "INSERT INTO publications VALUES (?, ?) "
                    "ON CONFLICT(identity) DO UPDATE SET record=excluded.record",
                    (key, json.dumps(record)),
                )
                db.commit()

            found = db.execute(
                "SELECT record FROM publications WHERE identity=?", (key,)
            ).fetchone()
            record = json.loads(found[0]) if found else None
            if record and record["date"] != event.date:
                raise ReviewRequired("Event moved; reconcile the previous scheduled entry")
            if record and record["phase"].endswith("_pending") and record["hash"] != content_hash:
                raise ReviewRequired("Resolve the earlier pending write before applying edits")

            workouts = self.provider.list_workouts()
            marked = [w for w in workouts if marker in (w.get("description") or "")]
            if len(marked) > 1:
                raise ReviewRequired("Multiple destination workouts have this identity")
            entries = self.provider.list_schedule(event.date)
            if record is None:
                if marked:
                    raise ReviewRequired("Remote identity exists but local receipt is missing")
                ids = {str(e.get("workoutId")) for e in entries}
                conflicts = [
                    w
                    for w in workouts
                    if str(w.get("workoutId")) in ids
                    and (
                        (w.get("workoutName") or "").strip().casefold()
                        == event.title.strip().casefold()
                        or matches(payload["workoutSegments"], w.get("workoutSegments"))
                    )
                ]
                if conflicts:
                    raise ReviewRequired("Possible existing workout or overlapping source feed")
                record = {
                    "date": event.date,
                    "hash": content_hash,
                    "phase": "upload_pending",
                    "workout_id": None,
                }
                save(record)
                wid = str(self.provider.upload(payload))
                record.update(workout_id=wid, phase="uploaded")
                save(record)
            elif record["workout_id"] is None:
                if not marked:
                    raise ReviewRequired("Upload outcome uncertain; not repeating remote creation")
                record.update(workout_id=str(marked[0]["workoutId"]), phase="uploaded")
                save(record)

            wid = record["workout_id"]
            if (record.get("scheduled_once") or record["phase"] == "schedule_pending") and not any(
                str(e.get("workoutId")) == wid and e.get("date") == event.date for e in entries
            ):
                raise ReviewRequired("Previously scheduled entry is absent; reconcile manually")
            saved = self.provider.get_workout(wid)
            if marker not in (saved.get("description") or ""):
                raise ReviewRequired("Recorded destination identity is missing; refusing overwrite")
            if not matches(payload, saved):
                if record["hash"] == content_hash or record["phase"].endswith("_pending"):
                    raise ReviewRequired("Destination read-back differs; reconcile before retry")
                record.update(hash=content_hash, phase="update_pending")
                save(record)
                self.provider.update(wid, payload)
                saved = self.provider.get_workout(wid)
                if not matches(payload, saved):
                    raise ReviewRequired("Updated workout did not verify")
                record["phase"] = "uploaded"
                save(record)

            scheduled = [
                e for e in entries if str(e.get("workoutId")) == wid and e.get("date") == event.date
            ]
            if len(scheduled) > 1:
                raise ReviewRequired("Duplicate destination calendar entries require review")
            if not scheduled:
                if record["phase"] in ("schedule_pending", "done"):
                    raise ReviewRequired("Schedule outcome uncertain; not scheduling again")
                record.update(hash=content_hash, phase="schedule_pending")
                save(record)
                self.provider.schedule(wid, event.date)
                scheduled = [
                    e
                    for e in self.provider.list_schedule(event.date)
                    if str(e.get("workoutId")) == wid and e.get("date") == event.date
                ]
                if len(scheduled) != 1:
                    raise ReviewRequired("Scheduled entry did not verify uniquely")
            record.update(hash=content_hash, phase="done", scheduled_once=True)
            save(record)
            return wid
