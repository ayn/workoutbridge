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
    "minute": "seconds",
    "mins": "seconds",
    "minutes": "seconds",
    "sec": "seconds",
    "second": "seconds",
    "secs": "seconds",
    "seconds": "seconds",
    "m": "meters",
    "km": "meters",
    "mi": "meters",
    "mile": "meters",
    "miles": "meters",
}
FACTORS = {
    "hr": 3600,
    "hour": 3600,
    "hours": 3600,
    "min": 60,
    "minute": 60,
    "mins": 60,
    "minutes": 60,
    "sec": 1,
    "second": 1,
    "secs": 1,
    "seconds": 1,
    "m": 1,
    "km": 1000,
    "mi": 1609.344,
    "mile": 1609.344,
    "miles": 1609.344,
}
BASIC_EFFORT = r"(?:easy/moderate|easy/mod|super hard|very hard|easy jog|jog|easy|moderate|hard|smooth|fast|steady|tempo|progression|recovery)"
EFFORT_QUALIFIER = (
    r"(?:tempo effort|long run pace|5k effort|10k effort|half marathon effort|marathon effort)"
)
EFFORT = rf"(?:{BASIC_EFFORT}(?: progression)?(?:(?: at | a little faster than | a bit faster than ){EFFORT_QUALIFIER})?|{EFFORT_QUALIFIER})"
DISTANCE_EFFORT = rf"(?:{EFFORT}|(?:(?:hard|smooth|fast) )?strides|sprints)"
PATTERN = re.compile(
    r"(warm up|run|ride|bike|cycle|rest|cool down)\s+"
    r"(?:(\d+(?:\.\d+)?)\s*(hours|hour|hr|minutes|minute|mins|min|seconds|second|secs|sec|miles|mile|mi|km|m)"
    r"|until lap)"
    rf"(?:\s+({EFFORT}|walk/jog))?",
    re.IGNORECASE,
)
INTERVAL = re.compile(
    rf"(\d+)\s*x\s*(\d+(?:\.\d+)?)\s*(miles|mile|mi|km|m)(?:\s+({EFFORT}))?\s+in\s+"
    r"(\d+(?::[0-5]\d)?)-(\d+(?::[0-5]\d)?)(?:\s+sec)?\s+with\s+"
    r"(\d+(?:\.\d+)?)\s*(min|sec)\s+(walk/jog|easy|rest)\s+recovery",
    re.IGNORECASE,
)


def clock_seconds(value: str) -> int:
    parts = value.split(":")
    return int(parts[0]) * 60 + int(parts[1]) if len(parts) == 2 else int(value)


def clock_label(seconds: int) -> str:
    return f"{seconds // 60}:{seconds % 60:02}"


def pace_step(kind, amount, unit, effort, fast, slow, pace_unit):
    distance_or_time = float(amount) * FACTORS[unit.lower()]
    fast, slow = clock_seconds(fast), clock_seconds(slow)
    if not 0 < distance_or_time < float("inf") or not 0 < fast <= slow:
        return None
    label = effort.lower() if effort else None
    note = (
        label + ": " if label else ""
    ) + f"{clock_label(fast)}-{clock_label(slow)}/{pace_unit.lower()}"
    return Step(
        kind,
        distance_or_time,
        UNITS[unit.lower()],
        label,
        note,
        FACTORS[pace_unit.lower()] / slow,
        FACTORS[pace_unit.lower()] / fast,
        {"mi": "mi", "mile": "mi", "miles": "mi", "km": "km", "m": "m"}.get(unit.lower()),
    )


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

    strides = re.fullmatch(
        r"(\d+) (?:(uphill|downhill|hill) )?strides with lap recovery", clause, re.IGNORECASE
    )
    if strides and 1 <= int(strides[1]) <= 100:
        return Repeat(
            int(strides[1]),
            (
                Step(
                    "run",
                    None,
                    "lap_button",
                    note=((strides[2].lower() + " ") if strides[2] else "") + "stride",
                ),
                Step("rest", None, "lap_button"),
            ),
            skip_last_recovery=False,
        )
    lap = re.fullmatch(
        rf"(\d+) x (\d+(?:\.\d+)?) (m|km|mi|miles)(?: ({DISTANCE_EFFORT}))? with lap recovery",
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
                    display_unit="mi" if unit.lower() == "miles" else unit.lower(),
                ),
                Step("rest", None, "lap_button"),
            ),
        )
    fartlek = re.fullmatch(
        rf"(\d+) x (\d+) sec ({EFFORT}) with "
        rf"(\d+) sec ({EFFORT}) recovery",
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
        rf"(\d+) x (\d+) sec (hills|strides|hill strides|uphill strides|downhill strides)(?: ({EFFORT}))? with lap recovery",
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
        r"(\d+) x (\d+) sec ((?:uphill |hill )?sprints) with lap recovery", clause, re.IGNORECASE
    )
    if sprints:
        count, seconds = map(int, sprints.groups()[:2])
        if not 1 <= count <= 100 or not 0 < seconds <= 3600:
            return None
        return Repeat(
            count,
            (
                Step("run", seconds, "seconds", note=sprints[3].lower().removesuffix("s")),
                Step("rest", None, "lap_button"),
            ),
            skip_last_recovery=False,
        )
    timed_lap = re.fullmatch(rf"(\d+) x (\d+) sec ({EFFORT}) with lap recovery", clause, re.I)
    if timed_lap:
        count, seconds, effort = timed_lap.groups()
        if not 1 <= int(count) <= 100 or not 0 < int(seconds) <= 3600:
            return None
        return Repeat(
            int(count),
            (
                Step("run", int(seconds), "seconds", effort.lower()),
                Step("rest", None, "lap_button"),
            ),
        )
    distance_rest = re.fullmatch(
        rf"(\d+) x (\d+(?:\.\d+)?) (m|km|mi|miles)(?: ({DISTANCE_EFFORT}))? with "
        r"(\d+(?:\.\d+)?) sec (rest|easy|walk/jog) recovery",
        clause,
        re.I,
    )
    if distance_rest:
        count, amount, unit, effort, recovery, recovery_effort = distance_rest.groups()
        distance = float(amount) * FACTORS[unit.lower()]
        recovery = float(recovery)
        if (
            not 1 <= int(count) <= 100
            or not 0 < distance < float("inf")
            or not 0 < recovery <= 86400
        ):
            return None
        return Repeat(
            int(count),
            (
                Step(
                    "run",
                    distance,
                    "meters",
                    effort.lower() if effort else None,
                    display_unit="mi" if unit.lower() == "miles" else unit.lower(),
                ),
                Step(
                    "run" if recovery_effort.lower() == "easy" else "rest",
                    recovery,
                    "seconds",
                    recovery_effort.lower(),
                ),
            ),
        )
    paced = re.fullmatch(
        rf"(\d+) x (\d+(?:\.\d+)?) (miles|mile|mi|km|m)(?: ({EFFORT}))? at "
        r"(\d{1,2}:[0-5]\d)-(\d{1,2}:[0-5]\d)/(mi|km) with "
        r"(\d+(?:\.\d+)?) sec (rest|easy|walk/jog) recovery",
        clause,
        re.I,
    )
    if paced:
        count, amount, unit, effort, fast, slow, pace_unit, recovery, recovery_effort = (
            paced.groups()
        )
        work = pace_step("run", amount, unit, effort, fast, slow, pace_unit)
        if work is None or not 1 <= int(count) <= 100 or not 0 < float(recovery) <= 86400:
            return None
        return Repeat(
            int(count),
            (
                work,
                Step(
                    "run" if recovery_effort.lower() == "easy" else "rest",
                    float(recovery),
                    "seconds",
                    recovery_effort.lower(),
                ),
            ),
        )
    match = INTERVAL.fullmatch(clause)
    if not match:
        return None
    count, distance, unit, work_effort, fast, slow, recovery, recovery_unit, effort = match.groups()
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
                label=work_effort.lower() if work_effort else None,
                note=(work_effort.lower() + ": " if work_effort else "")
                + f"{clock_label(fast)}-{clock_label(slow)}",
                speed_min=distance / slow,
                speed_max=distance / fast,
                display_unit="mi" if unit.lower() in {"mile", "miles"} else unit.lower(),
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
        paced = (
            re.fullmatch(
                rf"(Run|Warm up|Cool down) (\d+(?:\.\d+)?) (miles|mile|mi|km|m|min|sec)(?: ({EFFORT}))? at "
                r"(\d{1,2}:[0-5]\d)-(\d{1,2}:[0-5]\d)/(mi|km)",
                clause,
                re.I,
            )
            if sport == "running"
            else None
        )
        if paced:
            kind, amount, unit, effort, fast, slow, pace_unit = paced.groups()
            work = pace_step(
                kind.lower().replace(" ", "_"), amount, unit, effort, fast, slow, pace_unit
            )
            if work is None:
                unresolved.append(clause)
            else:
                steps.append(work)
            continue
        group = re.fullmatch(r"(\d+) x \[([^\[\]]+)\]", clause, re.I)
        if group:
            members = [parse(part.strip(), sport=sport) for part in group[2].split("|")]
            if (
                1 <= int(group[1]) <= 100
                and 2 <= len(members) <= 8
                and all(
                    not member.unresolved
                    and len(member.steps) == 1
                    and isinstance(member.steps[0], Step)
                    for member in members
                )
            ):
                steps.append(
                    Repeat(
                        int(group[1]),
                        tuple(member.steps[0] for member in members),
                        skip_last_recovery=False,
                    )
                )
            else:
                unresolved.append(clause)
            continue
        fast_finish = (
            re.fullmatch(
                r"Run (\d+(?:\.\d+)?) (miles|mi) (?:w/|with) last "
                r"(\d+(?:\.\d+)?) (?:miles|mi) (fast|hard|moderate|steady)",
                clause,
                re.I,
            )
            if sport == "running"
            else None
        )
        if fast_finish:
            total, _, finish, effort = fast_finish.groups()
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
                        note=f"last {finish} miles {effort.lower()}",
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
                    display_unit={
                        "mi": "mi",
                        "mile": "mi",
                        "miles": "mi",
                        "km": "km",
                        "m": "m",
                    }.get(unit),
                )
            )
    if not steps and not unresolved:
        unresolved.append("Empty prescription")
    return Draft(text, tuple(steps), tuple(unresolved), sport=sport)
