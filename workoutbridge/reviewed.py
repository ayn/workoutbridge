"""Explicit, narrow review policies; never guess at unsupported prescriptions."""

import math
import re
from dataclasses import replace

from .calendar import Event


def review_easy_run(
    event: Event, *, range_choice: str, recovery_choice: str | None = None
) -> Event:
    """Select the approved upper distance and add lap-ended bookends.

    Only recognizes complete easy-run prescriptions with optional additional
    timed hills. More complex instructions stay blocked for separate review.
    """
    if event.cancelled or event.structured_text or range_choice != "higher":
        raise ValueError("Requires an unreviewed run and explicit higher-range policy")
    original = event.description.strip() or event.title.strip()
    match = re.fullmatch(
        r"(\d+(?:\.\d+)?)(?:-(\d+(?:\.\d+)?))? miles (easy(?:/mod)?)"
        r"(?: plus (\d+) x (\d+) second hills)?",
        original,
        re.IGNORECASE,
    )
    if not match:
        raise ValueError("Unsupported prescription; manual review required")
    low, high, effort, count, seconds = match.groups()
    distance = float(high or low)
    if not math.isfinite(distance) or not 0 < float(low) <= distance:
        raise ValueError("Invalid distance range")
    if count and (
        recovery_choice != "lap" or not 1 <= int(count) <= 100 or not 0 < int(seconds) <= 3600
    ):
        raise ValueError("Hills require explicit lap recovery and valid repetition limits")
    steps = ["Warm up until lap", f"Run {distance:g} miles"]
    if count:
        steps.append(f"{count} x {seconds} sec hills with lap recovery")
    steps.append("Cool down until lap")
    notes = (
        f"Original prescription: {original}\n"
        f"Reviewed settings: {distance:g} miles at {effort.lower()}; "
        "upper bound selected when a range is given. "
        "Added warm-up and cooldown until Lap; no numeric pace target."
    )
    if count:
        notes += " Hills recovery until Lap between repetitions; no recovery after the last rep."
    return replace(event, description=notes, structured_text="; ".join(steps))


def review_progression(event: Event, *, pace_choice: str, transition_choice: str) -> Event:
    """Explicit approval of a single range with a Lap transition, never a default."""
    from .parser import parse

    if (
        event.cancelled
        or event.sport != "running"
        or pace_choice != "range"
        or transition_choice != "lap"
    ):
        raise ValueError("Approve the running pace range and Lap transition explicitly")
    match = re.fullmatch(
        r"Warm up (\d+(?:\.\d+)?) (?:miles?|mi)[;\n]+\s*"
        r"(\d+(?:\.\d+)?) (?:miles?|mi) progression from ~?(\d{1,2}:[0-5]\d)\s*(?:->|→|to)\s*~?(\d{1,2}:[0-5]\d)"
        r"[;\n]+\s*Cool down (\d+(?:\.\d+)?) (?:miles?|mi)",
        event.prescription.strip(),
        re.I,
    )
    if not match:
        raise ValueError("Unsupported progression; preserve it for manual review")
    warm, distance, start, finish, cool = match.groups()
    text = (
        f"Warm up {warm} miles; Run until lap easy; "
        f"Run {distance} miles progression from {start} to {finish}/mi; Cool down {cool} miles"
    )
    draft = parse(text)
    if draft.unresolved or len(draft.steps) != 4:
        raise ValueError("Invalid progression distances or pace direction")
    notes = (
        event.description
        + "\nAthlete-approved progression conversion: one continuous distance step "
        "with a pace range, not separate pace stages. "
        "Added easy run-until-Lap transition after the prescribed warm-up. "
        "Original warm-up and cooldown distances retained."
    )
    return replace(event, structured_text=text, description=notes)
