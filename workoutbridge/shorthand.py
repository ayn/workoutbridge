"""Complete-clause coaching syntax. Unknown instructions are never consumed."""

import re
from dataclasses import dataclass

from .parser import (
    DISTANCE_EFFORT,
    EFFORT,
    EFFORT_QUALIFIER,
    Repeat,
    Step,
    clock_label,
    clock_seconds,
    parse,
)


@dataclass(frozen=True)
class Conversion:
    text: str
    implied_recovery: bool = False


def normalize_bookend(text):
    text = re.sub(r"^(?:warmup|warm-up|wu)(?=\s*\d|\s+until lap)", "Warm up ", text, flags=re.I)
    text = re.sub(
        r"^(?:cooldown|cool-down|cd)(?=\s*\d|\s+until lap)", "Cool down ", text, flags=re.I
    )
    return re.sub(r"^cool\s+donw\b", "Cool down", text, flags=re.I).strip()


def clauses(text):
    """Split only outside groups; preserve malformed group text for review."""
    parts, start, depth = [], 0, 0
    for i, char in enumerate(text):
        if char in "([":
            depth += 1
        elif char in ")]":
            depth -= 1
            if depth < 0:
                return [text]
        elif char in "+;\n" and depth == 0:
            parts.append(text[start:i].strip())
            start = i + 1
    if depth:
        return [text]
    parts.append(text[start:].strip())
    parts = [part for part in parts if part]
    joined = []
    for part in parts:
        if (
            joined
            and re.match(r"^\d+\s*x\s*\(\s*\d+\s*x", joined[-1], re.I)
            and re.fullmatch(r".+? rest (?:in-between|between) sets", part, re.I)
        ):
            joined[-1] += " " + part
        else:
            joined.append(part)
    return joined


def seconds(text):
    text = text.strip().lower().lstrip("~").strip()
    if match := re.fullmatch(r"(\d+:[0-5]\d)(?:\s*(?:min|mins|minutes))?", text):
        value = clock_seconds(match[1])
    else:
        match = re.fullmatch(
            r"(\d+(?:\.\d+)?)\s*(s|sec|secs|second|seconds|min|mins|minute|minutes|')", text
        )
        if not match:
            return None
        value = float(match[1]) * (1 if match[2].startswith("s") else 60)
    return value if 0 < value <= 86400 else None


def cj_units(text):
    """Opt-in dialect; only fill units in bounded, recognized rep positions."""
    text = re.sub(r"^(\d+\s*x\s*)(\d+)\s+(hill sprints)\b", r"\1\2 sec \3", text, flags=re.I)
    text = re.sub(
        r"^(\d+\s*x\s*)(\d+)(?=\s*(?:at\b|@|\(|$))",
        lambda m: m[1] + m[2] + ("m" if 100 <= int(m[2]) <= 10000 else ""),
        text,
        flags=re.I,
    )
    group = re.fullmatch(r"(\d+\s*x\s*)\(([^()]*)\)", text, re.I)
    if group:
        phases = group[2].split(";")
        slash = re.fullmatch(
            rf"\s*(\d+(?:\.\d+)?\s+{EFFORT})\s*/\s*(\d+(?:\.\d+)?\s+{EFFORT})\s*", group[2], re.I
        )
        if slash:
            phases = [slash[1], slash[2]]
        if 2 <= len(phases) <= 8:
            converted = []
            for phase in phases:
                match = re.fullmatch(rf"\s*(\d+(?:\.\d+)?)\s+({EFFORT})\s*", phase, re.I)
                converted.append(f"{match[1]} min {match[2]}" if match else phase)
            text = group[1] + "(" + ";".join(converted) + ")"
    return text


def phase_clause(phase, pace_unit, coaching_policy="strict"):
    phase = re.sub(r"^~\s*(?=\d)", "", phase.strip().removesuffix("."))
    target_source = phase
    phase = re.sub(r"\bharda little\b", "hard a little", phase, flags=re.I)
    phase = re.sub(rf"\s*@\s*~?\s*(?={EFFORT}\b)", " at ", phase, flags=re.I)
    phase = re.sub(rf"\s+~\s*(?={EFFORT_QUALIFIER}\b)", " at ", phase, flags=re.I)
    phase = re.sub(rf"\s+at\s*~\s*(?={EFFORT}\b)", " at ", phase, flags=re.I)
    phase = re.sub(r"\s+", " ", phase).strip()
    rest = re.fullmatch(r"(.+?)\s+(rest|walk/jog)", phase, re.I)
    effort = re.fullmatch(rf"(.+?)\s+(?:at\s+)?({EFFORT})", phase, re.I)
    if rest or effort:
        match = rest or effort
        amount, label = match.groups()
        duration = seconds(amount)
        verb = "Rest" if rest else "Run"
        suffix = "" if label.lower() == "rest" else " " + label.lower()
        if duration is not None:
            return f"{verb} {duration:g} sec{suffix}"
        candidate = f"{verb} {amount}{suffix}"
        draft = parse(candidate)
        if not draft.unresolved and len(draft.steps) == 1 and isinstance(draft.steps[0], Step):
            return candidate
    if (targeted := targeted_clause(target_source, pace_unit, coaching_policy)) is not None:
        draft = parse(targeted.text)
        if not draft.unresolved and len(draft.steps) == 1 and isinstance(draft.steps[0], Step):
            return targeted.text
    return None


def targeted_clause(part, pace_unit=None, coaching_policy="strict"):
    part = re.sub(
        r"^(\d+\s*x\s*)(mile|kilometer|metre|meter)\b",
        lambda m: (
            m[1] + "1 " + {"kilometer": "km", "metre": "m", "meter": "m"}.get(m[2].lower(), m[2])
        ),
        part,
        flags=re.I,
    )
    unit_pattern = r"miles|mile|mi|km|k|m|min|mins|minutes|sec|seconds"
    target_pattern = r"(?P<approx>~\s*)?(?P<first>\d+(?::[0-5]\d)?)(?:\s*(?P<separator>->|→|>|[-–])\s*(?P<second>\d+(?::[0-5]\d)?))?"
    header = re.fullmatch(
        rf"(?:(?P<count>\d+)\s*x\s*)?(?:(?P<verb>Run|Warm up|Cool down)\s+)?"
        rf"(?P<amount>\d+(?:\.\d+)?)\s*(?P<unit>{unit_pattern})(?:\s+(?P<effort>{EFFORT}))?\s*(?:at|@)\s*"
        + target_pattern
        + r"\s*(?P<pace>pace)?\s*(?:/(?P<pace_unit>mi|km))?(?P<tail>.*)",
        part,
        re.I,
    )
    if not header:
        return None
    fields = header.groupdict()
    progression = fields["separator"] in ("->", "→", ">")
    approximate = bool(fields["approx"] and fields["second"] is None)
    if (progression or approximate) and coaching_policy != "cj":
        return None
    if ":" in fields["first"] and fields["second"] and ":" not in fields["second"]:
        if not int(fields["first"].split(":")[1]) <= int(fields["second"]) < 60:
            return None  # Do not guess a minute rollover or a different duration unit.
        fields["second"] = fields["first"].split(":")[0] + ":" + fields["second"].zfill(2)
    fast, slow = sorted(
        (clock_seconds(fields["first"]), clock_seconds(fields["second"] or fields["first"]))
    )
    if not 0 < fast <= slow <= 86400:
        return None
    unit = {
        "mile": "mi",
        "miles": "mi",
        "k": "km",
        "mins": "min",
        "minutes": "min",
        "seconds": "sec",
    }.get(fields["unit"].lower(), fields["unit"].lower())
    count, effort = fields["count"], fields["effort"]
    if count is not None and (fields["verb"] or unit in {"min", "sec"}):
        return None
    target_is_pace = bool(
        not count
        or fields["pace"]
        or fields["pace_unit"]
        or (coaching_policy == "cj" and unit == "mi")
    )
    if count and unit == "mi" and float(fields["amount"]) != 1 and not target_is_pace:
        return None  # Multi-mile reps need an explicit pace/elapsed-time distinction.
    target_unit = fields["pace_unit"] or pace_unit or ("mi" if unit == "mi" else None)
    if target_is_pace and (target_unit not in {"mi", "km"} or ":" not in fields["first"]):
        return None
    if approximate:
        if not target_is_pace:
            return None  # The approved tolerance applies to pace, not elapsed rep times.
        tolerance = 5 if target_unit == "mi" else 5 / 1.609344
        fast, slow = round(fast - tolerance), round(slow + tolerance)
        if fast <= 0:
            return None
    if progression:
        effort = (effort + " progression") if effort else "progression"
    tail = fields["tail"].strip()
    blocks = re.findall(r"\(([^()]*)\)", tail)
    if re.sub(r"\([^()]*\)", "", tail).strip():
        return None
    recovery, after = None, None
    for block in blocks:
        rest = re.fullmatch(r"(.+?)\s+(rest|easy|walk/jog)(?:\s+recovery)?", block.strip(), re.I)
        post = re.fullmatch(
            r"(.+?)\s+(?:rest\s+)?after\s+(?:the\s+)?(set|\d+(?:st|nd|rd|th))", block.strip(), re.I
        )
        if rest and recovery is None and (duration := seconds(rest[1])) is not None:
            recovery = (duration, rest[2].lower())
        elif post and after is None and (duration := seconds(post[1])) is not None:
            if post[2].lower() != "set" and (
                count is None or int(re.match(r"\d+", post[2])[0]) != int(count)
            ):
                return None
            after = duration
        else:
            return None
    label = f" {effort.lower()}" if effort else ""
    band = f"{clock_label(fast)}-{clock_label(slow)}"
    if count:
        if recovery is None:
            return None
        target = f"at {band}/{target_unit}" if target_is_pace else f"in {band} sec"
        canonical = f"{count} x {fields['amount']} {unit}{label} {target} with {recovery[0]:g} sec {recovery[1]} recovery"
        if after is not None:
            canonical += f"; Rest {after:g} sec"
    else:
        if after is not None:
            return None
        verb = fields["verb"] or "Run"
        canonical = f"{verb} {fields['amount']} {unit}{label} at {band}/{target_unit}"
        if recovery is not None:
            recovery_label = "" if recovery[1] == "rest" else " " + recovery[1]
            canonical += f"; {'Run' if recovery[1] == 'easy' else 'Rest'} {recovery[0]:g} sec{recovery_label}"
    return Conversion(canonical)


def normalize_clause(part, *, pace_unit=None, coaching_policy="strict"):
    rest = re.fullmatch(r"Rest\s+(.+)", part, re.I)
    if rest and (duration := seconds(rest[1])) is not None:
        return Conversion(f"Rest {duration:g} sec")
    scalar_rest = re.fullmatch(r"([^()]+)\s*\(([^()]+)\s+(rest|easy)\)", part, re.I)
    if scalar_rest:
        work = phase_clause(scalar_rest[1], pace_unit, coaching_policy)
        duration = seconds(scalar_rest[2])
        if work and duration is not None:
            recovery = (
                f"Run {duration:g} sec easy"
                if scalar_rest[3].lower() == "easy"
                else f"Rest {duration:g} sec"
            )
            return Conversion(work + "; " + recovery)
    timed_rest = re.fullmatch(
        rf"(\d+)\s*x\s*(\d+(?:\.\d+)?\s*(?:s|sec|seconds|min|mins|minutes))(?:\s+({EFFORT}))?\s*\(([^()]*)\s+rest\)",
        part,
        re.I,
    )
    if timed_rest:
        count, duration, effort, recovery = timed_rest.groups()
        duration, recovery = seconds(duration), seconds(recovery)
        if duration is None or recovery is None or not float(duration).is_integer():
            return None
        label = " " + effort.lower() if effort else ""
        return Conversion(
            f"{count} x {int(duration)} sec{label} with {recovery:g} sec rest recovery"
        )
    hill = re.fullmatch(
        rf"(\d+)\s*x\s*(~?\s*\d+(?:\.\d+)?\s*(?:s|sec|secs|seconds|min|mins|minutes))\s+"
        rf"(uphill|downhill|hills|hill strides|strides uphill|strides downhill)(?:\s+({EFFORT}))?"
        r"(?:\s*\((jog down|walk down|jog up)\))?",
        part,
        re.I,
    )
    if hill:
        count, duration, activity, effort, recovery = hill.groups()
        duration = seconds(duration)
        if duration is None or not float(duration).is_integer():
            return None
        activity = {"strides uphill": "uphill strides", "strides downhill": "downhill strides"}.get(
            activity.lower(), activity.lower()
        )
        label = " " + effort.lower() if effort else ""
        movement = " " + recovery.lower() if recovery else ""
        return Conversion(
            f"{count} x {int(duration)} sec {activity}{label} with lap recovery{movement}", True
        )
    sets = re.fullmatch(
        r"(\d+)\s*x\s*\((\d+\s*x\s*.+)\)\s*(.+?)\s+rest (?:in-between|between) sets",
        part,
        re.I,
    )
    if sets:
        count, inner, rest = sets.groups()
        inner = re.sub(r"\s+w/\s+([^()]+)$", r" (\1)", inner, flags=re.I)
        if coaching_policy == "cj":
            inner = cj_units(inner)
        converted = targeted_clause(inner, pace_unit, coaching_policy)
        duration = seconds(rest)
        if converted is None or duration is None or not 2 <= int(count) <= 20:
            return None
        draft = parse(converted.text)
        if (
            draft.unresolved
            or len(draft.steps) != 1
            or not isinstance(draft.steps[0], Repeat)
            or int(count) * draft.steps[0].count > 100
        ):
            return None
        return Conversion(f"; Rest {duration:g} sec; ".join([converted.text] * int(count)))
    if (targeted := targeted_clause(part, pace_unit, coaching_policy)) is not None:
        return targeted
    explicit = re.fullmatch(
        rf"(\d+)\s*x\s*(\d+(?:\.\d+)?)\s*(miles|mi|km|m)(?:\s+({DISTANCE_EFFORT}))?"
        r"\s*\(\s*(~?\s*\d+(?::[0-5]\d|\.\d+)?\s*(?:s|sec|secs|seconds|min|mins|minutes)?)"
        r"\s+(rest|easy|walk/jog)(?:\s+recovery)?\s*\)",
        part,
        re.I,
    )
    if explicit:
        count, amount, unit, effort, rest, recovery_effort = explicit.groups()
        duration = seconds(rest)
        if duration is None:
            return None
        label = f" {effort.lower()}" if effort else ""
        return Conversion(
            f"{count} x {amount} {unit.lower()}{label} with {duration:g} sec {recovery_effort.lower()} recovery"
        )

    stride = re.fullmatch(r"(\d+)\s*(?:x\s*)?(?:(uphill|downhill|hill)\s+)?strides", part, re.I)
    if stride:
        direction = (stride[2].lower() + " ") if stride[2] else ""
        return Conversion(f"{stride[1]} {direction}strides with lap recovery", True)

    timed = re.fullmatch(
        rf"(\d+)\s*x\s*(\d+(?:\.\d+)?\s*(?:s|sec|secs|seconds|min|mins|minutes|'))\s+"
        rf"((?:uphill |downhill |hill )?(?:strides|sprints)|{EFFORT})",
        part,
        re.I,
    )
    if timed:
        count, duration, label = timed.groups()
        duration = seconds(duration)
        if duration is None or not float(duration).is_integer():
            return None
        return Conversion(f"{count} x {int(duration)} sec {label.lower()} with lap recovery", True)

    distance = re.fullmatch(
        rf"(\d+)\s*x\s*(\d+(?:\.\d+)?)\s*(miles|mi|km|m)\s+({DISTANCE_EFFORT})",
        part,
        re.I,
    )
    if distance:
        count, amount, unit, label = distance.groups()
        return Conversion(
            f"{count} x {amount} {unit.lower()} {label.lower()} with lap recovery", True
        )

    repeated = re.fullmatch(r"(\d+)\s*x\s*\((.*)\)", part, re.I | re.S)
    if repeated and "(" not in repeated[2] and ")" not in repeated[2]:
        phases = re.split(r"\s*[,;+]\s*", repeated[2].strip())
        if not 2 <= len(phases) <= 8:
            return None
        steps = []
        for phase in phases:
            step = phase_clause(phase, pace_unit, coaching_policy)
            if step is None:
                return None
            steps.append(step)
        # Preserve the old two-phase form where it already has the same semantics.
        if len(steps) == 2:
            legacy = f"{repeated[1]} x {steps[0][4:]} with {steps[1][4:]} recovery"
            if not parse(legacy).unresolved:
                return Conversion(legacy)
        return Conversion(f"{repeated[1]} x [" + " | ".join(steps) + "]")
    return None
