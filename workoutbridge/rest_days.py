"""Recognize explicit rest days without discarding substantive instructions."""

import re

REST = r"(?:rest\s+day|rest\s+and\s+recovery)"


def is_rest_day(event):
    title = event.title.strip()
    if not re.fullmatch(REST, title, re.I):
        return False
    if event.structured_text.strip() not in (
        "",
        title,
        "Unsupported Final Surge event: " + event.title,
    ):
        return False
    return all(
        re.fullmatch(rf"(?:Workout:\s*)?{REST}|Planned:\s*0(?:\.0+)?\s*(?:mi|km)", line, re.I)
        for line in (line.strip() for line in event.description.splitlines())
        if line
    )
