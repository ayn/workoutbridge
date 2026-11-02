"""Recognize explicit rest days without discarding substantive instructions."""

import re


def is_rest_day(event):
    title = event.title.strip()
    if not re.fullmatch(r"rest\s+day", title, re.I):
        return False
    if event.structured_text.strip() not in (
        "",
        title,
        "Unsupported Final Surge event: " + event.title,
    ):
        return False
    return all(
        re.fullmatch(r"(?:Workout:\s*)?Rest\s+Day|Planned:\s*0(?:\.0+)?\s*(?:mi|km)", line, re.I)
        for line in (line.strip() for line in event.description.splitlines())
        if line
    )
