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
