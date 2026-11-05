"""Conservative direct-to-calendar publishing with durable COROS receipts."""

import json
import re
from datetime import date

from .calendar_blocks import is_calendar_block
from .coros import workout_payload
from .parser import parse
from .publishing import Publisher, ReviewRequired, confirm_publication, digest, matches
from .races import is_race
from .rest_days import is_rest_day


def event_values(event):
    if is_race(event):
        raise ReviewRequired("Not published — race")
    if is_calendar_block(event):
        raise ReviewRequired("Not published — calendar block")
    if is_rest_day(event):
        raise ReviewRequired("Not published — rest day")
    if event.cancelled:
        raise ReviewRequired("Cancelled COROS event requires manual reconciliation")
    return dict(
        source=event.source,
        uid=digest([event.uid, event.recurrence_id]),
        day=event.date,
        course=workout_payload(
            event.title, event.description, parse(event.prescription, sport=event.sport)
        ),
    )


class CorosEventPublisher:
    def __init__(self, database, client):
        self.publisher = CorosPublisher(database, client)

    def publish(self, event, approved):
        return self.publisher.publish(**event_values(event), approved=approved)


def approval_token(account, *, source, uid, day, course):
    return digest(["coros-scheduled-v1", account, source, uid, day, course])


def result_data(result):
    if isinstance(result.get("structuredContent"), dict):
        return result["structuredContent"]
    blocks = result.get("content", [])
    if len(blocks) == 1 and blocks[0].get("type") == "text":
        try:
            return json.loads(blocks[0]["text"])
        except (ValueError, TypeError, KeyError):
            pass
    raise ReviewRequired("Unrecognized COROS result; inspect privately before continuing")


class CorosPublisher:
    def __init__(self, database, client):
        self.ledger = Publisher(database, None)
        self.client = client

    def publish(self, *, source, uid, day, course, approved):
        account = self.client.account_id
        if (
            not account.startswith("coros:")
            or not source
            or not uid
            or approved != approval_token(account, source=source, uid=uid, day=day, course=course)
        ):
            raise ReviewRequired("Approve this exact COROS account and prescription")
        compact_day = date.fromisoformat(day).strftime("%Y%m%d")
        key = digest(["coros-scheduled-v1", account, source, uid])
        content_hash = digest(course)
        with self.ledger.locked_database() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS coros_publications (identity TEXT PRIMARY KEY, record TEXT NOT NULL)"
            )
            db.commit()
            row = db.execute(
                "SELECT record FROM coros_publications WHERE identity=?", (key,)
            ).fetchone()
            if row:
                record = json.loads(row[0])
                if record["day"] != day:
                    raise ReviewRequired("COROS event moved; reconcile the existing entry")
                if record["hash"] != content_hash:
                    self.update(db, key, record, compact_day, course)
                if record["phase"] not in {
                    "done",
                    "verify_pending",
                    "update_pending",
                    "update_verify_pending",
                } or not record.get("id"):
                    raise ReviewRequired("COROS write is pending; do not retry creation")
                self.verify(compact_day, record["id"], course)
                confirm_publication(record)
                record["phase"] = "done"
                db.execute(
                    "UPDATE coros_publications SET record=? WHERE identity=?",
                    (json.dumps(record), key),
                )
                db.commit()
                return record["id"]
            for (stored,) in db.execute("SELECT record FROM coros_publications"):
                other = json.loads(stored)
                if (
                    other["account"] == account
                    and other["day"] == day
                    and (
                        other["title"] == course["courseName"].strip().casefold()
                        or other["sections"] == digest(course["sections"])
                    )
                ):
                    raise ReviewRequired("Overlapping COROS publication already exists")
            schedule = result_data(
                self.client.call_tool(
                    "queryTrainingSchedule", {"startDate": compact_day, "endDate": compact_day}
                )
            )
            if schedule != "No training schedule found." and schedule != {"workouts": []}:
                raise ReviewRequired(
                    "COROS day is not verifiably empty; review its existing schedule"
                )
            record = {
                "account": account,
                "day": day,
                "hash": content_hash,
                "title": course["courseName"].strip().casefold(),
                "sections": digest(course["sections"]),
                "phase": "create_pending",
                "id": None,
                "course": course,
            }

            def save():
                db.execute(
                    "INSERT INTO coros_publications VALUES (?, ?) ON CONFLICT(identity) DO UPDATE SET record=excluded.record",
                    (key, json.dumps(record)),
                )
                db.commit()

            save()
            result = result_data(
                self.client.call_tool(
                    "createScheduledWorkout", {"date": compact_day, "course": course}
                )
            )
            remote_id = result.get("idInPlan") if isinstance(result, dict) else None
            if isinstance(result, str):
                confirmation = re.match(
                    r"Workout created on "
                    + compact_day
                    + r": "
                    + re.escape(course["courseName"])
                    + r" \(Running\)\.\nidInPlan: ([0-9]+)\n",
                    result,
                )
                remote_id = confirmation.group(1) if confirmation else None
            if not isinstance(remote_id, str) or not remote_id.isdecimal():
                raise ReviewRequired("COROS creation outcome uncertain; do not repeat")
            record.update(id=remote_id, phase="verify_pending")
            save()
            self.verify(compact_day, remote_id, course)
            confirm_publication(record)
            record["phase"] = "done"
            save()
            return remote_id

    def details(self, day, remote_id):
        details = result_data(
            self.client.call_tool(
                "queryScheduledWorkoutDetails", {"date": day, "idInPlan": remote_id}
            )
        )
        if isinstance(details, str):
            expected_day = date.fromisoformat(f"{day[:4]}-{day[4:6]}-{day[6:]}").isoformat()
            prefix = f"Scheduled Workout Detail\n========================\nDate: {expected_day}\nidInPlan: {remote_id}\n"
            _, separator, encoded = details.rpartition("\nCourse JSON: ")
            if not details.startswith(prefix) or not separator:
                raise ReviewRequired("Unrecognized COROS scheduled detail")
            try:
                actual, _ = json.JSONDecoder().raw_decode(encoded)
            except ValueError:
                raise ReviewRequired("Invalid COROS inline course JSON") from None
            details = {
                "course": actual,
                "editable": bool(re.search(r"(?m)^Editable via MCP: yes\s*$", details)),
            }
        return details

    @staticmethod
    def course_matches(expected, actual):
        if isinstance(actual, dict) and isinstance(actual.get("courseName"), str):
            actual = {**actual, "courseName": actual["courseName"].strip()}
            expected = {**expected, "courseName": expected["courseName"].strip()}
        return matches(expected, actual)

    def verify(self, day, remote_id, course):
        details = self.details(day, remote_id)
        actual = details.get("course") if isinstance(details, dict) else None
        if not self.course_matches(course, actual):
            raise ReviewRequired("COROS read-back differs; reconcile before continuing")

    def update(self, db, key, record, day, course):
        if record["phase"] != "done" or not record.get("id"):
            raise ReviewRequired("COROS write is pending; reconcile before editing")
        details = self.details(day, record["id"])
        actual = details.get("course") if isinstance(details, dict) else None
        if not isinstance(actual, dict) or details.get("editable") is not True:
            raise ReviewRequired("COROS scheduled workout is not confirmed editable")
        if record.get("course"):
            old_title = record["course"]["courseName"]
            unchanged = (
                actual.get("courseName", "").strip() == old_title.strip()
                and digest({**actual, "courseName": old_title}) == record["hash"]
            )
        else:
            # Legacy receipts have a full content hash but no payload snapshot.
            # Restore only author-title whitespace from the new prescription;
            # the old complete hash must still prove every prior field matches.
            candidates = [actual]
            if actual.get("courseName", "").strip() == course["courseName"].strip():
                candidates.append({**actual, "courseName": course["courseName"]})
            unchanged = any(digest(value) == record["hash"] for value in candidates)
        if not unchanged:
            raise ReviewRequired(
                "COROS destination changed outside the publisher; review before editing"
            )
        for identity, raw in db.execute("SELECT identity,record FROM coros_publications"):
            other = json.loads(raw)
            if (
                identity != key
                and other["account"] == record["account"]
                and other["day"] == record["day"]
                and (
                    other["title"] == course["courseName"].strip().casefold()
                    or other["sections"] == digest(course["sections"])
                )
            ):
                raise ReviewRequired("Overlapping COROS publication already exists")

        def save():
            db.execute(
                "UPDATE coros_publications SET record=? WHERE identity=?", (json.dumps(record), key)
            )
            db.commit()

        record.setdefault("publication_count", 1)
        record.update(
            hash=digest(course),
            title=course["courseName"].strip().casefold(),
            sections=digest(course["sections"]),
            course=course,
            phase="update_pending",
            publication_pending=True,
        )
        save()
        result = result_data(
            self.client.call_tool(
                "updateScheduledWorkout",
                {"date": day, "idInPlan": record["id"], "course": {**actual, **course}},
            )
        )
        remote_id = result.get("idInPlan") if isinstance(result, dict) else None
        if isinstance(result, str):
            found = re.search(r"(?m)^idInPlan: ([0-9]+)\s*$", result)
            remote_id = found[1] if found else None
        if not isinstance(remote_id, str) or not remote_id.isdecimal():
            raise ReviewRequired("COROS update outcome uncertain; do not repeat")
        record.update(id=remote_id, phase="update_verify_pending")
        save()

    def reconcile(self, *, source, uid, day, course, remote_id, approved):
        account = self.client.account_id
        if (
            approved != approval_token(account, source=source, uid=uid, day=day, course=course)
            or not isinstance(remote_id, str)
            or not remote_id.isdecimal()
        ):
            raise ReviewRequired("Approve this exact COROS receipt before reconciling")
        key = digest(["coros-scheduled-v1", account, source, uid])
        with self.ledger.locked_database() as db:
            row = db.execute(
                "SELECT record FROM coros_publications WHERE identity=?", (key,)
            ).fetchone()
            record = json.loads(row[0]) if row else None
            if (
                not record
                or record["phase"] not in {"create_pending", "verify_pending"}
                or record["hash"] != digest(course)
                or record["day"] != day
            ):
                raise ReviewRequired("No matching pending COROS intent")
            if record["id"] is not None and record["id"] != remote_id:
                raise ReviewRequired("Cannot replace the recorded COROS identity")
            self.verify(date.fromisoformat(day).strftime("%Y%m%d"), remote_id, course)
            confirm_publication(record)
            record.update(id=remote_id, phase="done")
            db.execute(
                "UPDATE coros_publications SET record=? WHERE identity=?", (json.dumps(record), key)
            )
            db.commit()
            return remote_id
