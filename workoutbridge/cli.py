"""Local review workflow; live publishing requires explicit opt-in."""

import argparse
import json
import logging
import sys
from dataclasses import asdict
from datetime import date
from pathlib import Path

from .calendar import Event, import_calendar
from .garmin import GarminProvider
from .parser import parse
from .publishing import Publisher, ReviewRequired, approval_token, digest, event_payload


def emit(value):
    json.dump(value, sys.stdout, indent=2)
    sys.stdout.write("\n")


def review_item(account: str, event: Event) -> dict:
    result = {"event": asdict(event), "draft": parse(event.prescription).to_dict()}
    try:
        result.update(payload=event_payload(event), approval=approval_token(account, event))
    except ValueError:
        result["error"] = "Cancelled event or unresolved prescription; review required"
    return result


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if not argv:
        draft = parse(sys.stdin.read())
        emit(draft.to_dict())
        return 2 if draft.unresolved else 0
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    check = sub.add_parser("garmin-check", help="Verify existing session and read access only")
    check.add_argument("--account-id", required=True)
    check.add_argument("--session-dir", type=Path, required=True)
    check.add_argument("--date", type=date.fromisoformat, required=True)
    plan = sub.add_parser("plan", help="Import local ICS and emit a JSON review plan")
    plan.add_argument("calendar", type=Path)
    plan.add_argument("--source", required=True, help="Stable source label, not a secret feed URL")
    plan.add_argument("--timezone", required=True)
    plan.add_argument("--start", required=True, type=date.fromisoformat)
    plan.add_argument("--end", required=True, type=date.fromisoformat, help="Exclusive end date")
    plan.add_argument("--account-id", required=True, help="Expected Garmin numeric profile ID")
    plan.add_argument("--uid", action="append", help="Include only these event UIDs")
    publish = sub.add_parser("publish", help="Validate review plan; dry-run by default")
    publish.add_argument("plan", type=Path)
    publish.add_argument("--account-id", required=True)
    publish.add_argument("--session-dir", type=Path, required=True)
    publish.add_argument("--state-db", type=Path, required=True)
    modes = publish.add_mutually_exclusive_group()
    modes.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate locally without contacting Garmin (default)",
    )
    modes.add_argument(
        "--apply", action="store_true", help="Publish with exact review-hash confirmation"
    )
    modes.add_argument(
        "--yolo",
        action="store_true",
        help="Publish without hash confirmation; all validation and duplicate checks remain",
    )
    publish.add_argument("--approve", help="Exact review_hash of the reviewed plan")
    args = parser.parse_args(argv)
    try:
        if args.command == "garmin-check":
            previous = logging.root.manager.disable
            logging.disable(logging.CRITICAL)
            try:
                provider = GarminProvider.connect(
                    args.session_dir, expected_account=args.account_id
                )
                workouts = provider.list_workouts()
                entries = provider.list_schedule(args.date.isoformat())
            finally:
                logging.disable(previous)
            emit(
                {
                    "status": "read-access-verified",
                    "account_id": provider.account_id,
                    "date": args.date.isoformat(),
                    "workouts": len(workouts),
                    "scheduled_workouts": sum(e.get("workoutId") is not None for e in entries),
                }
            )
            return 0
        if args.command == "plan":
            with args.calendar.open("rb") as handle:
                data = handle.read(2_000_001)
            events = import_calendar(
                data,
                source=args.source,
                timezone=args.timezone,
                start=args.start,
                end=args.end,
            )
            if args.uid:
                events = [event for event in events if event.uid in args.uid]
            bundle = {
                "version": 1,
                "account_id": args.account_id,
                "items": [review_item(args.account_id, event) for event in events],
            }
            bundle["review_hash"] = digest(bundle)
            emit(bundle)
            return 0

        with args.plan.open("rb") as handle:
            data = handle.read(2_000_001)
        if len(data) > 2_000_000:
            raise ReviewRequired("Review plan exceeds size limit")
        bundle = json.loads(data)
        review_hash = bundle.pop("review_hash")
        if (
            bundle["version"] != 1
            or bundle["account_id"] != args.account_id
            or digest(bundle) != review_hash
        ):
            raise ReviewRequired("Plan changed or account differs; regenerate and review")
        if not bundle["items"] or len(bundle["items"]) > 500:
            raise ReviewRequired("Select between 1 and 500 events")
        events = []
        for item in bundle["items"]:
            event = Event(**item["event"])
            if "error" in item or digest(review_item(args.account_id, event)) != digest(item):
                raise ReviewRequired("Plan is unresolved or outdated; regenerate and review")
            events.append(event)
        if not (args.apply or args.yolo):
            emit({"mode": "dry-run", "events": len(events), "review_hash": review_hash})
            return 0
        if not args.yolo and args.approve != review_hash:
            raise ReviewRequired("Pass --approve with the exact reviewed plan hash")

        # Third-party auth logs may contain session details; never expose them here.
        previous = logging.root.manager.disable
        logging.disable(logging.CRITICAL)
        try:
            provider = GarminProvider.connect(args.session_dir, expected_account=args.account_id)
            publisher = Publisher(args.state_db, provider)
            for event, item in zip(events, bundle["items"]):
                wid = publisher.publish(event, item["approval"])
                emit({"date": event.date, "workout_id": wid, "status": "verified"})
        finally:
            logging.disable(previous)
        return 0
    except ReviewRequired as exc:
        print(f"Review required: {exc}", file=sys.stderr)
        return 2
    except Exception:  # noqa: BLE001 - redact arbitrary third-party authentication errors.
        if args.command == "garmin-check":
            print(
                "Garmin read check failed. Check the session, expected account, and connectivity. "
                "No workouts were changed; sensitive details suppressed.",
                file=sys.stderr,
            )
            return 2
        print(
            "Operation failed. Check local input/session and retry the same plan with the "
            "same state database. Remote writes may need reconciliation; details suppressed.",
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
