"""Conservative recognition of race-day entries, separate from workout parsing."""

import re


def is_race(event):
    if re.search(r"(?im)^Workout:\s*(?:(?:Run|Bike|Cycling)\s*-\s*)?Race\s*$", event.description):
        return True
    title = event.title.strip()
    if re.match(r"(?i)^(?:Run|Bike|Cycling)\s*-\s*Race\s*:", title):
        return True
    title = re.sub(r"(?i)^(?:Run|Bike|Cycling)(?:\s*-\s*Easy)?\s*:\s*", "", title)
    if re.match(r"(?i)^Race(?: day)?\s*:", title):
        return True
    # Require a named race ending, not generic mentions of race-pace training.
    return bool(
        re.fullmatch(r".+\s+(?:half marathon|marathon|\d+(?:\.\d+)?\s*[kK] race)", title, re.I)
    )
