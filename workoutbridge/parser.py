"""Deliberately narrow parser: unknown clauses remain visible for review."""

from dataclasses import asdict, dataclass
import re


@dataclass(frozen=True)
class Step:
    kind: str
    duration: float | None
    unit: str
    label: str | None = None


@dataclass(frozen=True)
class Draft:
    original_text: str
    steps: tuple[Step, ...]
    unresolved: tuple[str, ...]
    requires_review: bool = True

    def to_dict(self) -> dict:
        return asdict(self)


UNITS = {
    "min": "seconds", "mins": "seconds", "minutes": "seconds",
    "sec": "seconds", "secs": "seconds", "seconds": "seconds",
    "m": "meters", "km": "meters", "mi": "meters", "miles": "meters",
}
FACTORS = {
    "min": 60, "mins": 60, "minutes": 60,
    "sec": 1, "secs": 1, "seconds": 1,
    "m": 1, "km": 1000, "mi": 1609.344, "miles": 1609.344,
}
PATTERN = re.compile(
    r"(warm up|run|rest|cool down)\s+"
    r"(?:(\d+(?:\.\d+)?)\s*(minutes|mins|min|seconds|secs|sec|miles|mi|km|m)"
    r"|until lap)"
    r"(?:\s+(easy|moderate|hard|smooth))?",
    re.IGNORECASE,
)


def parse(text: str) -> Draft:
    steps: list[Step] = []
    unresolved: list[str] = []
    for clause in filter(None, (part.strip() for part in text.split(";"))):
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
