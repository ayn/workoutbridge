"""Conservative calendar sport identification; conflicting cues require review."""

import re

WORDS = re.compile(
    r"\b(running|run|jogging|jog|cycling|cycle|biking|bike|ride|swimming|swim|strength|cross[ -]training)\b",
    re.I,
)
ALIASES = {
    "running": "running",
    "run": "running",
    "jogging": "running",
    "jog": "running",
    "cycling": "cycling",
    "cycle": "cycling",
    "biking": "cycling",
    "bike": "cycling",
    "ride": "cycling",
    "swimming": "swimming",
    "swim": "swimming",
    "strength": "strength",
    "cross training": "cross_training",
    "cross-training": "cross_training",
}


def event_sport(title: str, description: str, explicit: str = "") -> str:
    cues = {ALIASES[word.lower()] for word in WORDS.findall(title)}
    metadata = re.findall(r"(?im)^Workout:\s*([^\n]+)", description)
    for value in metadata:
        match = WORDS.match(value.strip())
        cues.add(ALIASES[match[0].lower()] if match else "unsupported")
    if explicit:
        cues.add(ALIASES.get(explicit.strip().lower(), "unsupported"))
    # Read commands only at the start of an unmarked prescription or within
    # the explicit machine-readable section, never arbitrary coaching prose.
    block = re.search(r"(?is)\[WorkoutBridge\]\s*(.*?)\[/WorkoutBridge\]", description)
    commands = block[1] if block else description.splitlines()[0] if description else ""
    for command in re.findall(r"(?:^|;)\s*(run|ride|bike|cycle|swim)\b", commands, re.I):
        cues.add(ALIASES[command.lower()])
    if len(cues) > 1:
        return "ambiguous"
    return next(iter(cues), "running")
