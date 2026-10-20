"""Conservative normalization of Final Surge titles and metadata-only descriptions."""

import re
from dataclasses import replace

from .calendar import Event
from .parser import parse

METADATA = re.compile(r"(?:Workout:\s*Run|Planned:\s*\d+(?:\.\d+)?\s*(?:mi|km))", re.I)


def normalize_finalsurge(event: Event, *, recovery_choice: str = "lap") -> Event:
    if event.structured_text:
        return event
    title = re.fullmatch(r"\s*Run:\s*(.+)", event.title, re.I)
    if not title:
        return replace(event, structured_text="Unsupported Final Surge event: " + event.title)
    details = "\n".join(
        line.strip()
        for line in event.description.splitlines()
        if line.strip() and not METADATA.fullmatch(line.strip())
    )
    # Never hide substantive instructions behind the title's shorter summary.
    if details:
        return replace(event, structured_text=details)
    clauses = []
    for part in title[1].replace("×", "x").split("+"):
        part = part.strip()
        candidate = part if part.lower().startswith("run ") else "Run " + part
        if not parse(candidate).unresolved:
            clauses.append(candidate)
            continue
        distance = re.fullmatch(
            r"(\d+)\s*x\s*(\d+(?:\.\d+)?)\s*(km|m)(?:\s+(smooth|hard|easy|moderate))?",
            part,
            re.I,
        )
        fartlek = re.fullmatch(
            r"(\d+)\s*x\s*\((\d+)s\s+(hard|smooth|easy|moderate)\s*;\s*"
            r"(\d+)s\s+(easy|moderate)\)",
            part,
            re.I,
        )
        if distance and recovery_choice == "lap":
            count, amount, unit, effort = distance.groups()
            canonical = f"{count} x {amount} {unit.lower()}"
            if effort:
                canonical += f" {effort.lower()}"
            canonical += " with lap recovery"
        elif fartlek:
            count, work, effort, recovery, recovery_effort = fartlek.groups()
            canonical = (
                f"{count} x {work} sec {effort.lower()} with "
                f"{recovery} sec {recovery_effort.lower()} recovery"
            )
        else:
            clauses.append(part)
            continue
        if clauses and not parse(clauses[-1]).unresolved and clauses[-1].startswith("Run "):
            clauses.append("Run until lap")
        clauses.append(canonical)
    notes = f"Original title: {event.title}\n{event.description}"
    if recovery_choice == "lap":
        notes += "\nFS default policy: unspecified distance-repeat recovery until Lap between reps."
    notes += "\nRun-until-Lap transition before intervals; no added warm-up or cooldown."
    return replace(event, structured_text="; ".join(clauses), description=notes)
