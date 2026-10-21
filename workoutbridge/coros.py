"""Translate reviewed running prescriptions into COROS scheduled courses."""

import math

from .parser import Draft, Repeat, Step


def workout_payload(title: str, description: str, draft: Draft) -> dict:
    if not title.strip() or len(title) > 100:
        raise ValueError("COROS requires a title of 1-100 characters")
    if draft.unresolved or not draft.steps:
        raise ValueError("Resolve the full prescription before exporting")
    notes = [description, draft.original_text]

    def integer(value):
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            or value <= 0
        ):
            raise ValueError("COROS targets must be finite positive numbers")
        result = math.floor(value + 0.5)
        if result < 1:
            raise ValueError("COROS target rounds to zero")
        return result

    def plain(step):
        if not isinstance(step, Step) or step.kind not in {"warm_up", "run", "rest", "cool_down"}:
            raise ValueError("Unsupported COROS step")
        result = {"sectionType": {"warm_up": 1, "run": 2, "rest": 3, "cool_down": 4}[step.kind]}
        if step.unit == "lap_button":
            if step.duration is not None:
                raise ValueError("Lap steps cannot have a duration")
            result["targetType"] = 4
        elif step.unit in {"meters", "seconds"}:
            result.update(
                targetType=1 if step.unit == "meters" else 2, targetValue=integer(step.duration)
            )
        else:
            raise ValueError("Unsupported COROS duration")
        if step.speed_min is not None or step.speed_max is not None:
            for speed in (step.speed_min, step.speed_max):
                integer(speed)
            if step.speed_min > step.speed_max:
                raise ValueError("Invalid pace range")
            fast, slow = integer(1000 / step.speed_max), integer(1000 / step.speed_min)
            if not 120 <= fast <= slow <= 1499:
                raise ValueError("Pace outside COROS supported range")
            result.update(intensityType=2, intensityValueStart=fast, intensityValueEnd=slow)
        notes.extend([step.label, step.note])
        return result

    sections = []
    for step in draft.steps:
        if isinstance(step, Repeat):
            if type(step.count) is not int or not 1 <= step.count <= 20 or not step.steps:
                raise ValueError("COROS repeats require 1-20 repetitions and steps")
            if any(
                not isinstance(child, Step) or child.kind not in {"run", "rest"}
                for child in step.steps
            ):
                raise ValueError("COROS repeat members must be run or recovery steps")
            members = [plain(child) for child in step.steps]
            skip = step.skip_last_recovery and step.steps[-1].kind == "rest"
            count = step.count - int(skip)
            if count:
                sections.append({"intervalGroup": True, "repeats": count, "sets": members})
            if skip:
                sections.extend(members[:-1])
        else:
            sections.append(plain(step))
    if not sections:
        raise ValueError("COROS course has no executable steps")
    return {
        "courseName": title,
        "courseDescription": "\n\n".join(
            dict.fromkeys(note for note in notes if note and note.strip())
        )
        or title,
        "sportType": 1,
        "sections": sections,
    }
