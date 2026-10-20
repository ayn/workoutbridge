"""Deliberately narrow parser: unknown clauses remain visible for review."""

import re
from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class Step:
    kind: str
    duration: float | None
    unit: str
    label: str | None = None
    note: str = ""
    speed_min: float | None = None
    speed_max: float | None = None


@dataclass(frozen=True)
class Repeat:
    count: int
    steps: tuple[Step, ...]
    skip_last_recovery: bool = True


@dataclass(frozen=True)
class Draft:
    original_text: str
    steps: tuple[Step | Repeat, ...]
    unresolved: tuple[str, ...]
    requires_review: bool = True

    def to_dict(self) -> dict:
        return asdict(self)


UNITS = {
    "min": "seconds",
    "mins": "seconds",
    "minutes": "seconds",
    "sec": "seconds",
    "secs": "seconds",
    "seconds": "seconds",
    "m": "meters",
    "km": "meters",
    "mi": "meters",
    "miles": "meters",
}
FACTORS = {
    "min": 60,
    "mins": 60,
    "minutes": 60,
    "sec": 1,
    "secs": 1,
    "seconds": 1,
    "m": 1,
    "km": 1000,
    "mi": 1609.344,
    "miles": 1609.344,
}
PATTERN = re.compile(
    r"(warm up|run|rest|cool down)\s+"
    r"(?:(\d+(?:\.\d+)?)\s*(minutes|mins|min|seconds|secs|sec|miles|mi|km|m)"
    r"|until lap)"
    r"(?:\s+(easy|moderate|hard|smooth))?",
    re.IGNORECASE,
)
INTERVAL = re.compile(
    r"(\d+)\s*x\s*(\d+(?:\.\d+)?)\s*(m|km)\s+in\s+"
    r"(\d+(?::[0-5]\d)?)-(\d+(?::[0-5]\d)?)(?:\s+sec)?\s+with\s+"
    r"(\d+(?:\.\d+)?)\s*(min|sec)\s+(walk/jog|easy|rest)\s+recovery",
    re.IGNORECASE,
)


def clock_seconds(value: str) -> int:
    parts = value.split(":")
    return int(parts[0]) * 60 + int(parts[1]) if len(parts) == 2 else int(value)


def clock_label(seconds: int) -> str:
    return f"{seconds // 60}:{seconds % 60:02}"


def interval(clause: str) -> Repeat | None:
    strides = re.fullmatch(r"(\d+) strides with lap recovery", clause, re.IGNORECASE)
    if strides and 1 <= int(strides[1]) <= 100:
        return Repeat(
            int(strides[1]),
            (
                Step("run", None, "lap_button", note="stride"),
                Step("rest", None, "lap_button"),
            ),
            skip_last_recovery=False,
        )
    lap = re.fullmatch(
        r"(\d+) x (\d+(?:\.\d+)?) (m|km)(?: (smooth|hard|easy|moderate))? with lap recovery",
        clause,
        re.IGNORECASE,
    )
    if lap:
        count, amount, unit, effort = lap.groups()
        distance = float(amount) * FACTORS[unit.lower()]
        if not 1 <= int(count) <= 100 or not 0 < distance < float("inf"):
            return None
        return Repeat(
            int(count),
            (
                Step("run", distance, "meters", effort.lower() if effort else None),
                Step("rest", None, "lap_button"),
            ),
        )
    fartlek = re.fullmatch(
        r"(\d+) x (\d+) sec (hard|smooth|easy|moderate) with "
        r"(\d+) sec (easy|moderate) recovery",
        clause,
        re.IGNORECASE,
    )
    if fartlek:
        count, work, effort, recovery, recovery_effort = fartlek.groups()
        if not 1 <= int(count) <= 100 or not 0 < int(work) <= 3600 or not 0 < int(recovery) <= 3600:
            return None
        return Repeat(
            int(count),
            (
                Step("run", int(work), "seconds", effort.lower()),
                Step("run", int(recovery), "seconds", recovery_effort.lower()),
            ),
            skip_last_recovery=False,
        )
    timed = re.fullmatch(
        r"(\d+) x (\d+) sec hills(?: (hard|smooth|easy|moderate))? with lap recovery",
        clause,
        re.IGNORECASE,
    )
    if timed:
        count, seconds = map(int, timed.groups()[:2])
        effort = timed[3]
        if not 1 <= count <= 100 or not 0 < seconds <= 3600:
            return None
        return Repeat(
            count,
            (
                Step(
                    "run",
                    seconds,
                    "seconds",
                    note="Hills" + (f" {effort.lower()}" if effort else ""),
                ),
                Step("rest", None, "lap_button"),
            ),
        )
    match = INTERVAL.fullmatch(clause)
    if not match:
        return None
    count, distance, unit, fast, slow, recovery, recovery_unit, effort = match.groups()
    count = int(count)
    distance = float(distance) * FACTORS[unit.lower()]
    fast, slow = clock_seconds(fast), clock_seconds(slow)
    recovery = float(recovery) * FACTORS[recovery_unit.lower()]
    if not (
        1 <= count <= 100
        and 0 < fast <= slow
        and 0 < distance < float("inf")
        and 0 < recovery < float("inf")
    ):
        return None
    effort = effort.lower()
    return Repeat(
        count,
        (
            Step(
                "run",
                distance,
                "meters",
                note=f"{clock_label(fast)}-{clock_label(slow)}",
                speed_min=distance / slow,
                speed_max=distance / fast,
            ),
            Step("run" if effort == "easy" else "rest", recovery, "seconds", effort),
        ),
    )


def parse(text: str) -> Draft:
    steps: list[Step | Repeat] = []
    unresolved: list[str] = []
    for clause in filter(None, (part.strip() for part in text.split(";"))):
        repeated = interval(clause)
        if repeated:
            steps.append(repeated)
            continue
        match = PATTERN.fullmatch(clause)
        if not match:
            unresolved.append(clause)
            continue
        kind, amount, unit, label = match.groups()
        kind = kind.lower().replace(" ", "_")
        label = label.lower() if label else None
        if amount is None:
            steps.append(Step(kind, None, "lap_button", label))
        else:
            unit = unit.lower()
            value = float(amount) * FACTORS[unit]
            if not 0 < value < float("inf"):
                unresolved.append(clause)
                continue
            steps.append(Step(kind, value, UNITS[unit], label))
    if not steps and not unresolved:
        unresolved.append("Empty prescription")
    return Draft(text, tuple(steps), tuple(unresolved))
