"""Garmin payload translation, independent of authentication and publishing."""

from datetime import date
from pathlib import Path

from .parser import Draft, Repeat, Step

SPORT = {"sportTypeId": 1, "sportTypeKey": "running"}


class GarminProvider:
    """Thin adapter for the methods already exercised in the personal workflow."""

    def __init__(self, client, *, expected_account: str, max_pages: int = 100):
        if not isinstance(client.profile_id, int) or str(client.profile_id) != expected_account:
            raise ValueError("Garmin account mismatch or missing stable profile ID")
        self.account_id = str(client.profile_id)
        self.client = client
        self.max_pages = max_pages

    @classmethod
    def connect(cls, session: Path, *, expected_account: str, client_factory=None):
        if client_factory is None:
            from garminconnect import Garmin

            client_factory = Garmin
        client = client_factory()
        client.login(str(session))
        return cls(client, expected_account=expected_account)

    def list_workouts(self) -> list[dict]:
        result = []
        for offset in range(0, self.max_pages * 100, 100):
            page = self.client.get_workouts(offset, 100)
            if not isinstance(page, list) or any(
                not isinstance(item, dict) or not item.get("workoutId") for item in page
            ):
                raise ValueError("Unexpected Garmin workout enumeration")
            result.extend(page)
            if len(page) < 100:
                return result
        raise ValueError("Incomplete Garmin workout enumeration; refusing writes")

    def get_workout(self, wid: str) -> dict:
        return self.client.get_workout_by_id(wid)

    def upload(self, payload: dict) -> str:
        result = self.client.upload_workout(payload)
        if not isinstance(result, dict) or not str(result.get("workoutId", "")).isdigit():
            raise ValueError("Upload outcome uncertain: no valid workout ID")
        return str(result["workoutId"])

    def update(self, wid: str, payload: dict):
        return self.client.update_workout(wid, payload)

    def list_schedule(self, day: str) -> list[dict]:
        result = self.client.get_calendar_week(day)
        entries = result.get("calendarItems") if isinstance(result, dict) else None
        if not isinstance(entries, list) or any(not isinstance(e, dict) for e in entries):
            raise ValueError("Unexpected Garmin calendar response; refusing writes")
        for entry in entries:
            if entry.get("workoutId") is not None:
                if not isinstance(entry.get("date"), str):
                    raise ValueError("Scheduled workout has no valid date; refusing writes")
                date.fromisoformat(entry["date"])
        return [e for e in entries if e.get("date") == day]

    def schedule(self, wid: str, day: str):
        return self.client.schedule_workout(wid, day)


def workout_payload(title: str, description: str, draft: Draft) -> dict:
    if draft.unresolved or not draft.steps:
        raise ValueError("Resolve the full prescription before exporting")
    order = 0

    def convert(step: Step | Repeat) -> dict:
        nonlocal order
        order += 1
        position = order
        if isinstance(step, Repeat):
            return {
                "type": "RepeatGroupDTO",
                "stepOrder": position,
                "stepType": {"stepTypeId": 6, "stepTypeKey": "repeat"},
                "numberOfIterations": step.count,
                "endCondition": {"conditionTypeId": 7, "conditionTypeKey": "iterations"},
                "endConditionValue": step.count,
                "smartRepeat": False,
                "skipLastRestStep": step.skip_last_recovery,
                "workoutSteps": [convert(child) for child in step.steps],
            }
        kind, kind_id = {
            "warm_up": ("warmup", 1),
            "cool_down": ("cooldown", 2),
            "run": ("interval", 3),
            "rest": ("recovery", 4),
        }[step.kind]
        condition, condition_id = {
            "lap_button": ("lap.button", 1),
            "seconds": ("time", 2),
            "meters": ("distance", 3),
        }[step.unit]
        result = {
            "type": "ExecutableStepDTO",
            "stepOrder": position,
            "stepType": {"stepTypeId": kind_id, "stepTypeKey": kind},
            "endCondition": {"conditionTypeId": condition_id, "conditionTypeKey": condition},
            "targetType": {"workoutTargetTypeId": 1, "workoutTargetTypeKey": "no.target"},
            "description": step.note or step.label or "",
        }
        if step.duration is not None:
            result["endConditionValue"] = step.duration
        if step.speed_min is not None:
            result.update(
                targetType={"workoutTargetTypeId": 6, "workoutTargetTypeKey": "pace.zone"},
                targetValueOne=step.speed_min,
                targetValueTwo=step.speed_max,
            )
        return result

    return {
        "workoutName": title,
        "description": description,
        "sportType": SPORT,
        "workoutSegments": [
            {
                "segmentOrder": 1,
                "sportType": SPORT,
                "workoutSteps": [convert(step) for step in draft.steps],
            }
        ],
    }
