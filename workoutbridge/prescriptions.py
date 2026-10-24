"""Provider-independent workout shorthand and Final Surge metadata handling."""

import re
from dataclasses import replace

from .calendar import Event
from .parser import EFFORT, Repeat, Step, parse
from .shorthand import clauses as split_clauses
from .shorthand import infer_shorthand_units, normalize_bookend, normalize_clause
from .sports import event_sport

METADATA = re.compile(
    r"(?:Workout:\s*(?:Run|Bike|Cycling)(?:\s*-\s*(?:Easy|Moderate|Hard|Long Run))?"
    r"|Planned:\s*(?:\d+(?:\.\d+)?\s*(?:mi|km)(?:\s*~\s*\d+:\d{2}:\d{2})?|\d+:\d{2}:\d{2}))",
    re.I,
)


def canonical_coaching_policy(value):
    # Read old saved sources without requiring a migration or guessing a coach.
    if value == "cj":
        return "athlete_preferences"
    if value not in ("strict", "athlete_preferences"):
        raise ValueError("Unknown conversion policy")
    return value


def incomplete_description(title, details, sport):
    draft = parse(
        "; ".join(normalize_bookend(part) for part in split_clauses(details)), sport=sport
    )
    return bool(
        details
        and not draft.unresolved
        and all(
            isinstance(step, Step) and step.kind in ("warm_up", "cool_down") for step in draft.steps
        )
        and re.search(
            r"\d\s*[x×]|\b(fartlek|tempo|strides|sprints|hills|intervals|fast|progression|workout)\b",
            title,
            re.I,
        )
    )


def normalize_finalsurge(
    event: Event,
    *,
    recovery_choice: str = "lap",
    coaching_policy: str = "strict",
    distance_unit: str = "auto",
) -> Event:
    coaching_policy = canonical_coaching_policy(coaching_policy)
    if distance_unit not in ("auto", "mi", "km"):
        raise ValueError("Unknown distance unit")
    event = replace(
        event,
        sport=event_sport(
            event.title, event.description, event.sport if event.sport != "running" else ""
        ),
    )
    if event.structured_text:
        return event
    title = re.fullmatch(
        r"\s*(?:Run|Bike|Cycling)(?:\s*-\s*(?:Easy|Moderate|Hard|Long Run))?:\s*(.+)",
        event.title,
        re.I,
    )
    if not title:
        return replace(event, structured_text="Unsupported Final Surge event: " + event.title)
    details = "\n".join(
        line.strip()
        for line in event.description.splitlines()
        if line.strip() and not METADATA.fullmatch(line.strip())
    )
    if incomplete_description(title[1], details, event.sport):
        return replace(event, structured_text="Incomplete description: main workout missing")
    # Never hide substantive instructions behind the title's shorter summary.
    return _normalize(event, details or title[1], recovery_choice, coaching_policy, distance_unit)


def normalize_workout(
    event: Event,
    *,
    recovery_choice: str = "lap",
    coaching_policy: str = "strict",
    distance_unit: str = "auto",
) -> Event:
    coaching_policy = canonical_coaching_policy(coaching_policy)
    if distance_unit not in ("auto", "mi", "km"):
        raise ValueError("Unknown distance unit")
    event = replace(
        event,
        sport=event_sport(
            event.title, event.description, event.sport if event.sport != "running" else ""
        ),
    )
    if event.structured_text:
        return event
    # An explicit author-supplied section distinguishes executable steps from
    # coaching notes. Never guess boundaries or choose among multiple sections.
    text = event.description
    if "[workoutbridge]" in text.lower() or "[/workoutbridge]" in text.lower():
        blocks = re.findall(r"(?im)^\[WorkoutBridge\]\s*\n([\s\S]*?)^\[/WorkoutBridge\]\s*$", text)
        if (
            len(blocks) == 1
            and text.lower().count("[workoutbridge]") == 1
            and text.lower().count("[/workoutbridge]") == 1
            and blocks[0].strip()
        ):
            return replace(event, structured_text=blocks[0].strip())
        return replace(event, structured_text="Invalid structured workout section; review required")
    if incomplete_description(event.title, event.description, event.sport):
        return replace(event, structured_text="Incomplete description: main workout missing")
    if not parse(event.prescription, sport=event.sport).unresolved:
        return event
    if re.search(r"(?im)^Workout:\s*(?:Run|Bike|Cycling)\b", event.description):
        return normalize_finalsurge(
            event,
            recovery_choice=recovery_choice,
            coaching_policy=coaching_policy,
            distance_unit=distance_unit,
        )
    text = re.sub(
        r"^\s*(?:Run(?:\s*-\s*Long Run)?|Bike|Cycling|Ride):\s*",
        "",
        event.prescription,
        flags=re.I,
    )
    return _normalize(event, text, recovery_choice, coaching_policy, distance_unit)


def _normalize(
    event: Event, text: str, recovery_choice: str, coaching_policy: str, distance_unit: str
) -> Event:
    if event.sport == "cycling":
        # Only add the cycling verb to an otherwise fully supported duration or
        # distance, never strip target instructions or borrow running shorthand.
        candidate = "Ride " + text
        if not parse(candidate, sport="cycling").unresolved:
            text = candidate
        return replace(event, structured_text=text)
    if not parse(text, sport=event.sport).unresolved:
        return replace(event, structured_text=text)
    # Only explicit distance fractions: effort ratios and unitless text remain unknown.
    text = re.sub(r"(?<![\d/])(?:1/2|½)(?=\s*(?:miles|mile|mi|km)\b)", "0.5", text, flags=re.I)
    text = re.sub(r"(?<![\d/])(?:3/4|¾)(?=\s*(?:miles|mile|mi|km)\b)", "0.75", text, flags=re.I)
    text = re.sub(
        r"~\s*(?=\d+(?:\.\d+)?\s*(?:miles|mile|mi|km|m|hours|hour|hr|minutes|mins|min|seconds|sec|s)\b)",
        "",
        text,
        flags=re.I,
    )
    clauses = []
    fallback_used = False
    transition_added = False
    total_bookends_added = False
    pace_metadata = re.search(r"(?im)^Planned:\s*\d+(?:\.\d+)?\s*(mi|km)\b", event.description)
    pace_unit = pace_metadata[1].lower() if pace_metadata else None
    bare_unit = pace_unit or (distance_unit if distance_unit != "auto" else None)
    pace_unit = bare_unit
    unspecified_distance_used = False
    parts = split_clauses(text.replace("×", "x"))
    for index, part in enumerate(parts):
        part = normalize_bookend(part.strip().removesuffix("."))
        original_part = part
        condition = None
        if coaching_policy == "athlete_preferences" and len(parts) == 1:
            condition = re.fullmatch(r"(.+?)\s+(if\s+\S[^\[\];\n|]{0,249})", part, re.I)
            if condition and re.search(r"\d|\b(then|also|add|followed|plus)\b", condition[2], re.I):
                condition = None
            if condition is None:
                condition = re.fullmatch(
                    r"(.+?)\.\s+(Optional easy double(?: or x-train)?)", part, re.I
                )
        if condition:
            part = condition[1].strip().removesuffix(".")
        if coaching_policy == "athlete_preferences":
            part = infer_shorthand_units(part)
            distance_range = re.fullmatch(
                rf"(?P<range>(\d+(?:\.\d+)?)\s*[-–]\s*(\d+(?:\.\d+)?)(?:\s*(miles|mile|mi|km))?)(?:\s+({EFFORT}))?",
                part,
                re.I,
            )
            if distance_range:
                first, second, unit, effort = distance_range.group(2, 3, 4, 5)
                unit = unit or bare_unit
                if unit and 0 < min(float(first), float(second)):
                    label = " " + effort if effort else ""
                    part = f"Run {max(float(first), float(second)):g} {unit}{label} [distance note: {distance_range['range']}]"
        bare = re.fullmatch(rf"(?:Run\s+)?(\d+(?:\.\d+)?)\s+({EFFORT})", part, re.I)
        if bare and bare_unit:
            part = f"{bare[1]} {bare_unit} {bare[2]}"
            unspecified_distance_used = True
        if (
            re.fullmatch(r"\d+\s*x\s*(uphill|downhill)", part, re.I)
            and index + 1 < len(parts)
            and re.fullmatch(r"\d+\s*x\s*(uphill|downhill)\s+strides", parts[index + 1], re.I)
        ):
            part += " strides"
        candidate = part if part.lower().startswith("run ") else "Run " + part
        if condition:
            nominal = parse(candidate)
            if (
                nominal.unresolved
                or len(nominal.steps) != 1
                or not isinstance(nominal.steps[0], Step)
                or nominal.steps[0].kind != "run"
                or nominal.steps[0].unit != "meters"
            ):
                clauses.append(original_part)
                continue
            candidate += f" [condition note: {condition[2]}]"
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
        sprints = re.fullmatch(
            r"(\d+)\s*x\s*(\d+)\s*(?:s|sec|seconds)\s+uphill sprints", part, re.I
        )
        if sprints and recovery_choice == "lap":
            canonical = f"{sprints[1]} x {sprints[2]} sec uphill sprints with lap recovery"
            fallback_used = True
        elif strides and recovery_choice == "lap":
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
        elif (
            converted := normalize_clause(
                part,
                pace_unit=pace_unit,
                coaching_policy=coaching_policy,
                allow_total=len(parts) == 1,
            )
        ) is not None and (not converted.implied_recovery or recovery_choice == "lap"):
            canonical = converted.text
            fallback_used |= converted.implied_recovery
            total_bookends_added |= converted.total_bookends
        else:
            clauses.append(part)
            continue
        previous = parse(clauses[-1]) if clauses else None
        current = parse(canonical)
        if (
            previous
            and not previous.unresolved
            and previous.steps
            and isinstance(previous.steps[-1], Step)
            and previous.steps[-1].kind == "run"
            and previous.steps[-1].unit != "lap_button"
            and not current.unresolved
            and current.steps
            and isinstance(current.steps[0], Repeat)
        ):
            clauses.append("Run until lap")
            transition_added = True
        clauses.append(canonical)
    notes = f"Original title: {event.title}\n{event.description}"
    if unspecified_distance_used:
        notes += f"\nUnspecified distances interpreted as {bare_unit} from feed metadata or source preference."
    if coaching_policy == "athlete_preferences":
        notes += "\nAthlete conversion preferences: unitless track reps in meters, fartlek phases in minutes, hill sprints in seconds; pace arrows use a progression band; approximate pace uses ±5 sec/mi; distance/recovery ranges use the longer bound with the original range on the step; simple conditions stay on the nominal run as athlete-decision notes."
    if fallback_used:
        notes += "\nDefault policy: implied interval recovery until Lap between reps."
        if any(
            re.search(r"\b(?:uphill |hill )?sprints with lap recovery", clause)
            for clause in clauses
        ):
            notes += "\nUphill sprint policy: retain recovery until Lap after the final sprint too."
    if transition_added:
        notes += "\nRun-until-Lap transition before intervals."
    notes += (
        "\nAdded Lap-ended easy bookends under the approved total-distance policy; finish the stated total distance including the interval block."
        if total_bookends_added
        else "\nNo added warm-up or cooldown."
    )
    return replace(event, structured_text="; ".join(clauses), description=notes)
