"""Identify explicit walk-only entries without discarding running prescriptions."""

import re


def is_walk(event):
    if (
        event.structured_text.strip()
        or "[workoutbridge]" in event.description.casefold()
        or re.search(
            r"(?im)^\s*(?:run|ride|bike|cycle|swim|warm up|cool down)\s+\d", event.description
        )
    ):
        return False
    title = event.title.strip()
    metadata = re.findall(r"(?im)^Workout:\s*([^\n]+)", event.description)
    if metadata:
        return all(
            value.strip().casefold() in {"walk", "walking"} for value in metadata
        ) and not re.match(r"^(?:run|bike|cycling|swim)\b", title, re.I)
    return title.casefold() in {"walk", "walking"} and event.description.strip().casefold() in {
        "",
        "walk",
        "walking",
    }
