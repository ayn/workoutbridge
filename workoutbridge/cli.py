"""Local review workflow; live publishing requires explicit opt-in."""

import argparse
import json
import logging
import sys
from dataclasses import asdict
from datetime import date
from pathlib import Path

from .calendar import Event, import_calendar
from .feed import read_calendar
from .garmin import GarminProvider
from .parser import parse
from .publishing import Publisher, ReviewRequired, approval_token, digest, event_payload
from .races import is_race


def emit(value):
    json.dump(value, sys.stdout, indent=2)
    sys.stdout.write("\n")


def review_item(account: str, event: Event) -> dict:
    result = {
        "event": asdict(event),
        "draft": parse(event.prescription, sport=event.sport).to_dict(),
    }
    if is_race(event):
        return {**result, "skipped": "race", "error": "Not published — race"}
    try:
        if account.startswith("coros:"):
            from .coros_publishing import approval_token as coros_approval
            from .coros_publishing import event_values

            values = event_values(event)
            result.update(payload=values["course"], approval=coros_approval(account, **values))
        else:
            result.update(payload=event_payload(event), approval=approval_token(account, event))
    except ValueError:
        result["error"] = "Cancelled event or unresolved prescription; review required"
    return result


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if not argv:
        from .sports import event_sport

        text = sys.stdin.read()
        draft = parse(text, sport=event_sport("", text))
        emit(draft.to_dict())
        return 2 if draft.unresolved else 0
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    auth = sub.add_parser("auth", help="Interactively authenticate; no workout changes")
    auth.add_argument("provider", choices=["garmin", "coros"])
    auth.add_argument(
        "--region", choices=["us", "eu", "cn"], default="us", help="COROS account region"
    )
    auth.add_argument(
        "--finish", action="store_true", help="Finish pending COROS browser authorization"
    )
    auth.add_argument("--session-dir", type=Path, help="New private session directory")
    auth.add_argument(
        "--state-db",
        type=Path,
        help="When creating a profile, retain an existing publishing database",
    )
    check = sub.add_parser("garmin-check", help="Verify existing session and read access only")
    check.add_argument("--account-id")
    check.add_argument("--session-dir", type=Path)
    check.add_argument("--date", type=date.fromisoformat, required=True)
    plan = sub.add_parser("plan", help="Import local ICS or HTTPS feed and emit a JSON review plan")
    plan.add_argument("calendar", help="Local ICS path or authorized HTTPS feed URL")
    plan.add_argument("--calendar-format", choices=["generic", "finalsurge"], default="generic")
    plan.add_argument(
        "--interval-recovery",
        choices=["lap", "review"],
        default="lap",
        help="Implied interval recovery: lap (default) or require review, for all calendar formats",
    )
    plan.add_argument("--source", required=True, help="Stable source label, not a secret feed URL")
    plan.add_argument("--timezone", required=True)
    plan.add_argument("--start", required=True, type=date.fromisoformat)
    plan.add_argument("--end", required=True, type=date.fromisoformat, help="Exclusive end date")
    plan.add_argument("--account-id", help="Expected Garmin numeric profile ID")
    plan.add_argument("--uid", action="append", help="Include only these event UIDs")
    plan.add_argument(
        "--easy-run-range",
        choices=["higher"],
        help="Opt into upper distance bounds and lap warm-up/cooldown for supported easy runs",
    )
    plan.add_argument(
        "--hill-recovery",
        choices=["lap"],
        help="Explicitly use lap recovery for otherwise unspecified hill recoveries",
    )
    publish = sub.add_parser("publish", help="Validate review plan; dry-run by default")
    publish.add_argument("plan", type=Path)
    publish.add_argument("--account-id")
    publish.add_argument("--session-dir", type=Path)
    publish.add_argument("--state-db", type=Path)
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
    for command in (auth, check, plan, publish):
        command.add_argument("--profile", help="Named private connection saved during login")
    args = parser.parse_args(argv)
    try:
        if args.command == "auth" and args.provider == "coros":
            from .coros_auth import begin_login, finish_login
            from .profiles import authenticate_profile, load_profile, profile_path

            if args.profile is None or args.session_dir is None:
                raise ReviewRequired("COROS login requires --profile and a new --session-dir")
            path = profile_path(args.profile)
            if path.exists() and load_profile(args.profile)["destination"] != "coros":
                raise ReviewRequired("Profile belongs to another provider")
            if not args.finish:
                emit({"status": "pending", **begin_login(args.session_dir, args.region)})
                return 0

            class Pending(Exception):
                pass

            def authenticate_coros(session):
                account = finish_login(session)
                if account is None:
                    raise Pending
                return account

            try:
                profile = authenticate_profile(
                    args.profile,
                    args.session_dir,
                    args.state_db,
                    destination="coros",
                    authenticator=authenticate_coros,
                )
            except Pending:
                emit({"status": "pending"})
                return 0
            emit(
                {
                    "status": "authenticated",
                    "profile": args.profile,
                    "account_id": profile["account_id"],
                }
            )
            return 0
        if args.command != "auth":
            if args.profile is not None:
                from .profiles import load_profile

                if any(
                    getattr(args, field, None) is not None
                    for field in ("account_id", "session_dir", "state_db")
                ):
                    raise ReviewRequired("Use --profile or explicit connection flags, not both")
                profile = load_profile(args.profile)
                args.account_id = profile["account_id"]
                args.session_dir = Path(profile["session_dir"])
                args.state_db = Path(profile["state_db"])
            required = ["account_id"]
            if args.command in ("publish", "garmin-check"):
                required.append("session_dir")
            if args.command == "publish":
                required.append("state_db")
            if any(getattr(args, field, None) is None for field in required):
                raise ReviewRequired("Provide --profile or all explicit connection flags")
        if args.command == "auth":
            from .auth import authenticate

            try:
                if args.profile is not None:
                    from .profiles import authenticate_profile

                    profile = authenticate_profile(args.profile, args.session_dir, args.state_db)
                    account = profile["account_id"]
                elif args.session_dir is not None and args.state_db is None:
                    account = authenticate(args.session_dir)
                else:
                    raise ValueError("Provide --profile or --session-dir")
            except (Exception, KeyboardInterrupt):  # noqa: BLE001 - never print auth secrets.
                print(
                    "Authentication failed or cancelled. Use Python 3.12+ with --extra garmin, "
                    "an interactive terminal, and a new session directory. Existing sessions "
                    "are never overwritten. Avoid repeated attempts if rate limited.",
                    file=sys.stderr,
                )
                return 2
            result = {"status": "authenticated", "account_id": account}
            if args.profile is not None:
                result["profile"] = args.profile
            emit(result)
            return 0
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
            data = read_calendar(args.calendar)
            events = import_calendar(
                data,
                source=args.source,
                timezone=args.timezone,
                start=args.start,
                end=args.end,
            )
            if args.uid:
                events = [event for event in events if event.uid in args.uid]
            if args.easy_run_range:
                from .reviewed import review_easy_run

                reviewed = []
                for event in events:
                    try:
                        event = review_easy_run(
                            event,
                            range_choice=args.easy_run_range,
                            recovery_choice=args.hill_recovery,
                        )
                    except ValueError:
                        pass  # Preserve unsupported prescriptions for normal review.
                    reviewed.append(event)
                events = reviewed
            from .prescriptions import normalize_finalsurge, normalize_workout

            normalizer = (
                normalize_finalsurge if args.calendar_format == "finalsurge" else normalize_workout
            )
            events = [normalizer(event, recovery_choice=args.interval_recovery) for event in events]
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
        coros_client = None
        try:
            if args.account_id.startswith("coros:"):
                from .coros_client import CorosClient
                from .coros_publishing import CorosEventPublisher

                coros_client = CorosClient(
                    args.session_dir,
                    args.account_id.split(":")[1],
                    expected_account=args.account_id,
                )
                publisher = CorosEventPublisher(args.state_db, coros_client)
            else:
                provider = GarminProvider.connect(
                    args.session_dir, expected_account=args.account_id
                )
                publisher = Publisher(args.state_db, provider)
            for event, item in zip(events, bundle["items"]):
                wid = publisher.publish(event, item["approval"])
                emit({"date": event.date, "workout_id": wid, "status": "verified"})
        finally:
            if coros_client is not None:
                coros_client.close()
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
