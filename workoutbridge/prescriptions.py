"""Provider-independent workout shorthand and Final Surge metadata handling."""

import re
from dataclasses import replace

from .calendar import Event
from .parser import Step, parse

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
    detail_draft = parse(details)
    if (
        details
        and not detail_draft.unresolved
        and all(
            isinstance(step, Step) and step.kind in ("warm_up", "cool_down")
            for step in detail_draft.steps
        )
        and re.search(r"\d\s*[x×]|\b(fartlek|tempo|strides|hills|intervals)\b", title[1], re.I)
    ):
        return replace(event, structured_text="Incomplete description: main workout missing")
    # Never hide substantive instructions behind the title's shorter summary.
    return _normalize(event, details or title[1], recovery_choice)


def normalize_workout(event: Event, *, recovery_choice: str = "lap") -> Event:
    if event.structured_text or not parse(event.prescription).unresolved:
        return event
    text = re.sub(r"^\s*Run:\s*", "", event.prescription, flags=re.I)
    return _normalize(event, text, recovery_choice)


def _normalize(event: Event, text: str, recovery_choice: str) -> Event:
    if not parse(text).unresolved:
        return replace(event, structured_text=text)
    clauses = []
    fallback_used = False
    transition_added = False
    for part in text.replace("×", "x").split("+"):
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
        hills = re.fullmatch(
            r"(\d+)\s*x\s*(\d+)\s*('|min|mins|s|sec|seconds)\s+hills?"
            r"(?:\s+(hard|smooth|easy|moderate))?",
            part,
            re.I,
        )
        strides = re.fullmatch(r"(\d+)\s+strides", part, re.I)
        if strides and recovery_choice == "lap":
            canonical = f"{strides[1]} strides with lap recovery"
            fallback_used = True
        elif distance and recovery_choice == "lap":
            count, amount, unit, effort = distance.groups()
            canonical = f"{count} x {amount} {unit.lower()}"
            if effort:
                canonical += f" {effort.lower()}"
            canonical += " with lap recovery"
            fallback_used = True
        elif hills and recovery_choice == "lap":
            count, amount, unit, effort = hills.groups()
            seconds = int(amount) * (60 if unit.lower() in ("'", "min", "mins") else 1)
            canonical = f"{count} x {seconds} sec hills"
            if effort:
                canonical += f" {effort.lower()}"
            canonical += " with lap recovery"
            fallback_used = True
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
            transition_added = True
        clauses.append(canonical)
    notes = f"Original title: {event.title}\n{event.description}"
    if fallback_used:
        notes += "\nDefault policy: implied interval recovery until Lap between reps."
    if transition_added:
        notes += "\nRun-until-Lap transition before intervals."
    notes += "\nNo added warm-up or cooldown."
    return replace(event, structured_text="; ".join(clauses), description=notes)
