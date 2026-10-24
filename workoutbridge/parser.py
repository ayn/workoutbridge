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
    display_unit: str | None = None


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
    sport: str = "running"

    def to_dict(self) -> dict:
        return asdict(self)


UNITS = {
    "hr": "seconds",
    "hour": "seconds",
    "hours": "seconds",
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
    "hr": 3600,
    "hour": 3600,
    "hours": 3600,
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
    r"(warm up|run|ride|bike|cycle|rest|cool down)\s+"
    r"(?:(\d+(?:\.\d+)?)\s*(hours|hour|hr|minutes|mins|min|seconds|secs|sec|miles|mi|km|m)"
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


def interval(clause: str, sport: str = "running") -> Repeat | None:
    if sport == "cycling":
        match = re.fullmatch(
            r"(\d+)\s*x\s*(\d+(?:\.\d+)?)\s*(min|sec|minutes|seconds)"
            r"(?:\s+(easy|moderate|hard|smooth))?\s+with\s+"
            r"(\d+(?:\.\d+)?)\s*(min|sec|minutes|seconds)\s+(easy|rest)\s+recovery",
            clause,
            re.I,
        )
        if not match:
            return None
        count, work, unit, effort, recovery, recovery_unit, recovery_effort = match.groups()
        work = float(work) * FACTORS[unit.lower()]
        recovery = float(recovery) * FACTORS[recovery_unit.lower()]
        if not 1 <= int(count) <= 100 or not 0 < work <= 86400 or not 0 < recovery <= 86400:
            return None
        return Repeat(
            int(count),
            (
                Step("ride", work, "seconds", effort.lower() if effort else None),
                Step("rest", recovery, "seconds", recovery_effort.lower()),
            ),
        )

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
                Step(
                    "run",
                    distance,
                    "meters",
                    effort.lower() if effort else None,
                    display_unit=unit.lower(),
                ),
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
        r"(\d+) x (\d+) sec (hills|strides)(?: (hard|smooth|easy|moderate))? with lap recovery",
        clause,
        re.IGNORECASE,
    )
    if timed:
        count, seconds = map(int, timed.groups()[:2])
        activity, effort = timed[3], timed[4]
        if not 1 <= count <= 100 or not 0 < seconds <= 3600:
            return None
        return Repeat(
            count,
            (
                Step(
                    "run",
                    seconds,
                    "seconds",
                    note=activity.capitalize() + (f" {effort.lower()}" if effort else ""),
                ),
                Step("rest", None, "lap_button"),
            ),
        )
    sprints = re.fullmatch(
        r"(\d+) x (\d+) sec uphill sprints with lap recovery", clause, re.IGNORECASE
    )
    if sprints:
        count, seconds = map(int, sprints.groups())
        if not 1 <= count <= 100 or not 0 < seconds <= 3600:
            return None
        return Repeat(
            count,
            (
                Step("run", seconds, "seconds", note="uphill sprint"),
                Step("rest", None, "lap_button"),
            ),
            skip_last_recovery=False,
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
                display_unit=unit.lower(),
            ),
            Step("run" if effort == "easy" else "rest", recovery, "seconds", effort),
        ),
    )


def parse(text: str, *, sport: str = "running") -> Draft:
    if sport not in {"running", "cycling"}:
        return Draft(text, (), ("Unsupported or ambiguous sport; review required",), sport=sport)
    steps: list[Step | Repeat] = []
    unresolved: list[str] = []
    for clause in filter(None, (part.strip() for part in text.split(";"))):
        fast_finish = (
            re.fullmatch(
                r"Run (\d+(?:\.\d+)?) (miles|mi) (?:w/|with) last "
                r"(\d+(?:\.\d+)?) (?:miles|mi) fast",
                clause,
                re.I,
            )
            if sport == "running"
            else None
        )
        if fast_finish:
            total, _, finish = fast_finish.groups()
            total, amount = float(total), float(finish)
            if not 0 < amount < total < float("inf") or total * FACTORS["mi"] == float("inf"):
                unresolved.append(clause)
                continue
            steps.extend(
                (
                    Step("run", (total - amount) * FACTORS["mi"], "meters", display_unit="mi"),
                    Step(
                        "run",
                        amount * FACTORS["mi"],
                        "meters",
                        note=f"last {finish} miles fast",
                        display_unit="mi",
                    ),
                )
            )
            continue
        progression = (
            re.fullmatch(
                r"Run (\d+(?:\.\d+)?) (?:miles|mi) progression from (\d{1,2}:[0-5]\d) to (\d{1,2}:[0-5]\d)/mi",
                clause,
                re.I,
            )
            if sport == "running"
            else None
        )
        if progression:
            amount, start, finish = progression.groups()
            distance = float(amount) * FACTORS["mi"]
            slow, fast = clock_seconds(start), clock_seconds(finish)
            if not 0 < distance < float("inf") or not 0 < fast <= slow:
                unresolved.append(clause)
                continue
            steps.append(
                Step(
                    "run",
                    distance,
                    "meters",
                    note=f"Progression: start around {start}/mi and gradually build toward {finish}/mi.",
                    speed_min=FACTORS["mi"] / slow,
                    speed_max=FACTORS["mi"] / fast,
                    display_unit="mi",
                )
            )
            continue
        repeated = interval(clause, sport)
        if repeated:
            steps.append(repeated)
            continue
        match = PATTERN.fullmatch(clause)
        if not match:
            unresolved.append(clause)
            continue
        kind, amount, unit, label = match.groups()
        kind = kind.lower().replace(" ", "_")
        if kind in {"run", "ride", "bike", "cycle"}:
            if (sport == "running" and kind != "run") or (sport == "cycling" and kind == "run"):
                unresolved.append(clause)
                continue
            kind = "run" if sport == "running" else "ride"
        label = label.lower() if label else None
        if amount is None:
            steps.append(Step(kind, None, "lap_button", label))
        else:
            unit = unit.lower()
            value = float(amount) * FACTORS[unit]
            if not 0 < value < float("inf"):
                unresolved.append(clause)
                continue
            steps.append(
                Step(
                    kind,
                    value,
                    UNITS[unit],
                    label,
                    display_unit={"mi": "mi", "miles": "mi", "km": "km", "m": "m"}.get(unit),
                )
            )
    if not steps and not unresolved:
        unresolved.append("Empty prescription")
    return Draft(text, tuple(steps), tuple(unresolved), sport=sport)
