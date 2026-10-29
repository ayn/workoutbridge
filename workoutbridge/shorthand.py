"""Complete-clause coaching syntax. Unknown instructions are never consumed."""

import re
from dataclasses import dataclass

from .parser import (
    DISTANCE_EFFORT,
    EFFORT,
    EFFORT_QUALIFIER,
    FACTORS,
    TERRAIN,
    TIME_UNITS,
    Repeat,
    Step,
    clock_label,
    clock_seconds,
    parse,
)

DURATION_UNITS = rf"(?:{TIME_UNITS}|s|')"
CLAUSE_START = re.compile(
    r"\s*(?:\d|(?:warmup|warm-up|warm up|wup|wu|cooldown|cool-down|cool down|cd)(?=\s*:?\s*\d|\s+until lap)|(?:run|rest|ride|bike)\b)",
    re.I,
)


@dataclass(frozen=True)
class Conversion:
    text: str
    implied_recovery: bool = False
    total_bookends: bool = False


def normalize_bookend(text):
    suffix = re.fullmatch(
        rf"(\d+(?:\.\d+)?\s*(?:{TIME_UNITS}|miles|mile|mi|km|m))\s+(wup|wu|cd)", text, re.I
    )
    if suffix:
        text = suffix[2] + " " + suffix[1]
    text = re.sub(
        r"^(?:warmup|warm-up|warm up|wup|wu)(?=\s*:?\s*\d|\s+until lap)\s*:?\s*",
        "Warm up ",
        text,
        flags=re.I,
    )
    text = re.sub(
        r"^(?:cooldown|cool-down|cool down|cd)(?=\s*:?\s*\d|\s+until lap)\s*:?\s*",
        "Cool down ",
        text,
        flags=re.I,
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
        elif depth == 0 and (
            char in "+;\n"
            or (char == "," and CLAUSE_START.match(text, i + 1))
            or (
                i > 0
                and text[i - 1].isspace()
                and text[i : i + 4].lower() == "plus"
                and text[i + 4 : i + 5].isspace()
            )
        ):
            parts.append(text[start:i].strip())
            start = i + (4 if text[i : i + 4].lower() == "plus" else 1)
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
        match = re.fullmatch(rf"(\d+(?:\.\d+)?)\s*({DURATION_UNITS})", text)
        if not match:
            return None
        value = float(match[1]) * {"s": 1, "'": 60}.get(match[2], FACTORS.get(match[2]))
    return value if 0 < value <= 86400 else None


def recovery_duration(text, coaching_policy):
    """Return an explicit duration, or the athlete-approved upper range bound."""
    if (duration := seconds(text)) is not None:
        return duration, ""
    if coaching_policy != "athlete_preferences":
        return None, ""
    match = re.fullmatch(
        r"\s*(\d+(?::[0-5]\d|\.\d+)?)\s*[-–]\s*(\d+(?::[0-5]\d|\.\d+)?)\s*(s|sec|seconds|min|mins|minutes)?\s*",
        text,
    )
    if not match:
        return None, ""
    first, second, unit = match.groups()
    unit = " " + unit if unit else ""
    values = [seconds(value + unit) for value in (first, second)]
    if any(value is None for value in values):
        return None, ""
    return max(values), text.strip()


def recovery_annotation(text, span, effort="rest"):
    return text + (f" [recovery note: {span} {effort}]" if span else "")


def infer_shorthand_units(text):
    """Opt-in dialect; only fill units in bounded, recognized rep positions."""
    text = re.sub(r"^(\d+\s*x\s*)(\d+)\s+(hill sprints)\b", r"\1\2 sec \3", text, flags=re.I)
    text = re.sub(
        rf"^(\d+\s*x\s*)~?\s*(\d+)(?=\s*(?:at\b|@|\(|$|{DISTANCE_EFFORT}\b))",
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


def distance_recovery_clause(part):
    match = re.fullmatch(
        r"(?:Rest\s+)?(\d+(?:\.\d+)?)\s*(m|km|mi)\s+(jog|easy|walk/jog)\s+in\s+"
        r"(?:~\s*|about\s+|around\s+)?(\d+(?::[0-5]\d)?)(?:\s*[-–]\s*(\d+(?::[0-5]\d)?))?"
        r"\s*(s|secs|sec|seconds)?",
        part,
        re.I,
    )
    if not match or (not match[6] and ":" not in match[4]):
        return None
    amount, unit, effort, fast, slow, _ = match.groups()
    candidate = f"Rest {amount} {unit.lower()} {effort.lower()} in {fast}-{slow or fast} sec"
    return candidate if not parse(candidate).unresolved else None


def one_sided_pace(part, pace_unit, coaching_policy):
    if coaching_policy != "athlete_preferences":
        return None
    header = (
        r"(?P<head>(?:Run\s+)?\d+(?:\.\d+)?\s*(?P<unit>miles|mile|mi|km|m|min|sec)(?:\s+"
        + EFFORT
        + r")?)"
    )
    match = re.fullmatch(
        header
        + r"\s+(?:(?:at|@)\s+)?(?P<before>under|sub)\s*~?\s*(?P<limit>\d{1,2}:[0-5]\d)(?:/(?P<pace_unit>mi|km))?",
        part,
        re.I,
    )
    if match is None:
        match = re.fullmatch(
            header
            + r"\s+(?:at|@)\s*~?\s*(?P<limit>\d{1,2}:[0-5]\d)(?:/(?P<pace_unit>mi|km))?\s+(?:or faster|or under|and faster)",
            part,
            re.I,
        )
    if match is None:
        return None
    unit = (
        match["pace_unit"]
        or pace_unit
        or ("mi" if match["unit"].lower() in {"miles", "mile", "mi"} else None)
    )
    if unit not in {"mi", "km"}:
        return None
    limit = clock_seconds(match["limit"])
    width = 45 if unit == "mi" else round(45 / 1.609344)
    if limit <= width:
        return None
    head = match["head"]
    if not head.lower().startswith("run "):
        head = "Run " + head
    candidate = f"{head} at {clock_label(limit - width)}-{clock_label(limit)}/{unit} [target note: {match['limit']}/{unit} or faster]"
    return Conversion(candidate) if not parse(candidate).unresolved else None


def unclear_recovery_clause(part, *, phase=False):
    """Recognize the recovery role without fabricating its endpoint duration."""
    part = part.strip()
    vague = re.fullmatch(
        r"(?:(?:a )?(?:short|full|brief|unspecified|unclear|unknown)?\s*(?:rest|recovery)(?: (?:as needed|as required|by feel|until ready))?"
        r"|recover (?:until ready|as needed|by feel)|choose (?:your own |own )?recovery)",
        part,
        re.I,
    )
    effort = phase and part.lower() in {"easy", "moderate", "jog", "walk/jog", "recovery"}
    if not vague and not effort:
        return None
    label = " " + part.lower() if effort and part.lower() != "recovery" else ""
    return f"Rest until lap{label} [buffer note: {part}]"


def phase_clause(phase, pace_unit, coaching_policy="strict", *, recovery_phase=False):
    phase = re.sub(r"^~\s*(?=\d)", "", phase.strip().removesuffix("."))
    if coaching_policy == "athlete_preferences":
        if buffer := unclear_recovery_clause(phase, phase=recovery_phase):
            return buffer
        if recovery_phase and (duration := seconds(phase)) is not None:
            return f"Rest {duration:g} sec"
    if recovery := distance_recovery_clause(phase):
        return recovery
    target_source = phase
    phase = re.sub(r"\bharda little\b", "hard a little", phase, flags=re.I)
    phase = re.sub(rf"\s*@\s*~?\s*(?={EFFORT}\b)", " at ", phase, flags=re.I)
    phase = re.sub(rf"\s+~\s*(?={EFFORT_QUALIFIER}\b)", " at ", phase, flags=re.I)
    phase = re.sub(rf"\s+at\s*~\s*(?={EFFORT}\b)", " at ", phase, flags=re.I)
    phase = re.sub(r"\s+", " ", phase).strip()
    rest = re.fullmatch(r"(.+?)\s+(rest|walk/jog)", phase, re.I)
    effort = re.fullmatch(rf"(.+?)\s+(?:at\s+)?({DISTANCE_EFFORT})", phase, re.I)
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
    if (
        targeted := targeted_clause(target_source, pace_unit, coaching_policy, elapsed_target=True)
    ) is not None:
        draft = parse(targeted.text)
        if not draft.unresolved and len(draft.steps) == 1 and isinstance(draft.steps[0], Step):
            return targeted.text
    return None


def targeted_clause(part, pace_unit=None, coaching_policy="strict", *, elapsed_target=False):
    part = re.sub(r"\bstarting\s+at\b", "at", part, flags=re.I)
    part = re.sub(r"\b(at|@)\s+around\s+(?=\d)", r"\1 ~", part, flags=re.I)
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
    if (progression or approximate) and coaching_policy != "athlete_preferences":
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
        (not count and not (elapsed_target and unit in {"m", "km"}))
        or fields["pace"]
        or fields["pace_unit"]
        or (coaching_policy == "athlete_preferences" and unit == "mi")
    )
    if count and unit == "mi" and float(fields["amount"]) != 1 and not target_is_pace:
        return None  # Multi-mile reps need an explicit pace/elapsed-time distinction.
    target_unit = fields["pace_unit"] or pace_unit or ("mi" if unit == "mi" else None)
    if target_is_pace and (target_unit not in {"mi", "km"} or ":" not in fields["first"]):
        return None
    equivalent_blocks = re.findall(
        r"\((\d{1,2}:[0-5]\d)\s*[-–]\s*(\d{1,2}:[0-5]\d)\s+(?:pace(?:/(mi|km))?|/(mi|km))\)",
        fields["tail"],
        re.I,
    )
    equivalent = None
    if equivalent_blocks:
        if len(equivalent_blocks) != 1 or target_is_pace:
            return None
        first, second, explicit_unit, alternate_unit = equivalent_blocks[0]
        equivalent_unit = explicit_unit or alternate_unit or target_unit
        distance = float(fields["amount"]) * FACTORS[unit]
        if equivalent_unit not in {"mi", "km"} or not 0 < distance < float("inf"):
            return None
        bounds = sorted((clock_seconds(first), clock_seconds(second)))
        if any(
            abs(a - b) > 1
            for a, b in zip(
                bounds,
                (
                    fast * FACTORS[equivalent_unit] / distance,
                    slow * FACTORS[equivalent_unit] / distance,
                ),
            )
        ):
            return None
        fast, slow = bounds
        target_is_pace, target_unit = True, equivalent_unit
        equivalent = equivalent_blocks[0]
    if approximate:
        if not target_is_pace:
            distance = float(fields["amount"]) * FACTORS[unit]
            if not 0 < distance < float("inf"):
                return None
            # Garmin/COROS express elapsed rep targets as pace alerts; apply the
            # same approved tolerance after converting the stated rep time.
            fast = slow = fast * FACTORS["mi"] / distance
            target_is_pace, target_unit = True, "mi"
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
    recovery_note, after_note = "", ""
    recovery_buffer, after_buffer = None, None
    implied_recovery = False
    for block in blocks:
        buffer = (
            unclear_recovery_clause(block) if coaching_policy == "athlete_preferences" else None
        )
        if buffer and recovery is None:
            recovery, recovery_buffer = ("lap", "rest"), block.strip()
            implied_recovery = True
            continue
        if equivalent and re.fullmatch(
            r"\d{1,2}:[0-5]\d\s*[-–]\s*\d{1,2}:[0-5]\d\s+(?:pace(?:/(mi|km))?|/(mi|km))",
            block.strip(),
            re.I,
        ):
            continue
        rest = re.fullmatch(r"(.+?)\s+(rest|easy|walk/jog)(?:\s+recovery)?", block.strip(), re.I)
        post = re.fullmatch(
            r"(.+?)\s+(?:rest\s+)?after\s+(?:the\s+)?(set|last one|last rep|last repetition|\d+(?:st|nd|rd|th))",
            block.strip(),
            re.I,
        )
        rest_duration, rest_range = (
            recovery_duration(rest[1], coaching_policy) if rest else (None, "")
        )
        post_duration, post_range = (
            recovery_duration(post[1], coaching_policy) if post else (None, "")
        )
        if (
            post
            and post_duration is None
            and after is None
            and coaching_policy == "athlete_preferences"
        ):
            if unclear_recovery_clause(post[1]) or unclear_recovery_clause(post[1] + " rest"):
                if post[2].lower() not in {"set", "last one", "last rep", "last repetition"} and (
                    count is None or int(re.match(r"\d+", post[2])[0]) != int(count)
                ):
                    return None
                after, after_buffer = "lap", block.strip()
                implied_recovery = True
                continue
        if rest and recovery is None and rest_duration is not None:
            recovery = (rest_duration, rest[2].lower())
            recovery_note = rest_range + " " + rest[2].lower() if rest_range else ""
        elif (
            rest
            and recovery is not None
            and after is None
            and rest_duration is not None
            and count
            and coaching_policy == "athlete_preferences"
        ):
            after = rest_duration
            after_note = rest_range + " rest" if rest_range else ""
        elif post and after is None and post_duration is not None:
            if post[2].lower() not in {"set", "last one", "last rep", "last repetition"} and (
                count is None or int(re.match(r"\d+", post[2])[0]) != int(count)
            ):
                return None
            after = post_duration
            after_note = post_range + " rest" if post_range else ""
        else:
            return None
    label = f" {effort.lower()}" if effort else ""
    band = f"{clock_label(fast)}-{clock_label(slow)}"
    if count:
        if recovery is None:
            if coaching_policy != "athlete_preferences":
                return None
            recovery, recovery_buffer = ("lap", "rest"), "Recovery unspecified"
            implied_recovery = True
        target = f"at {band}/{target_unit}" if target_is_pace else f"in {band} sec"
        endpoint = (
            "lap recovery"
            if recovery[0] == "lap"
            else f"{recovery[0]:g} sec {recovery[1]} recovery"
        )
        canonical = f"{count} x {fields['amount']} {unit}{label} {target} with {endpoint}"
        if recovery_buffer:
            canonical += f" [buffer note: {recovery_buffer}]"
        if progression:
            canonical += f" [target note: {fields['first']} -> {fields['second']}/{target_unit if target_is_pace else 'sec'} progression]"
        if recovery_note:
            canonical += f" [recovery note: {recovery_note}]"
        if after is not None:
            canonical += (
                f"; Rest until lap [buffer note: {after_buffer}]"
                if after == "lap"
                else f"; Rest {after:g} sec"
            )
            if after_note:
                canonical += f" [recovery note: {after_note}]"
    else:
        if after is not None:
            return None
        verb = fields["verb"] or "Run"
        target = f"at {band}/{target_unit}" if target_is_pace else f"in {band} sec"
        canonical = f"{verb} {fields['amount']} {unit}{label} {target}"
        if progression:
            canonical += f" [target note: {fields['first']} -> {fields['second']}/{target_unit if target_is_pace else 'sec'} progression]"
        if recovery is not None:
            recovery_label = "" if recovery[1] == "rest" else " " + recovery[1]
            canonical += (
                f"; Rest until lap [buffer note: {recovery_buffer}]"
                if recovery[0] == "lap"
                else f"; {'Run' if recovery[1] == 'easy' else 'Rest'} {recovery[0]:g} sec{recovery_label}"
            )
            if recovery_note:
                canonical += f" [recovery note: {recovery_note}]"
    return Conversion(canonical, implied_recovery)


def minimum_distance(step):
    if isinstance(step, Repeat):
        distance = step.count * sum(minimum_distance(child) for child in step.steps)
        if step.skip_last_recovery and step.steps[-1].kind == "rest":
            distance -= minimum_distance(step.steps[-1])
        return distance
    if step.unit == "meters":
        return step.duration
    if step.unit == "seconds" and step.speed_min is not None:
        return step.duration * step.speed_min
    return 0


def slash_effort_clause(part, pace_unit, coaching_policy):
    """Explicit work/recovery pairs, with opted-in note-only set recovery."""
    part = re.sub(r"\bHMP(?: race pace)?\b", "half marathon pace", part, flags=re.I)
    note = re.fullmatch(
        r"(.+?)\s+[-–]\s+(\d+(?:\.\d+)?\s*(?:min|mins|minutes|sec|seconds) walk recovery after the set)",
        part,
        re.I,
    )
    if note:
        if coaching_policy != "athlete_preferences":
            return None
        part = note[1]
    if "/" not in part:
        phase = phase_clause(part, pace_unit, coaching_policy)
        return Conversion(phase) if phase and not note else None
    pair = part.split("/")
    if len(pair) != 2:
        return None
    repeated = re.fullmatch(r"(\d+)\s*x\s*(.+)", pair[0].strip(), re.I)
    work = phase_clause(repeated[2] if repeated else pair[0], pace_unit, coaching_policy)
    recovery = pair[1].strip()
    # Accept both '3 min easy' and 'easy 3 min jog recovery'.
    recovery = re.sub(r"^easy\s+(.+?)\s+jog recovery$", r"\1 jog", recovery, flags=re.I)
    recovery = re.sub(r"\s+recovery$", "", recovery, flags=re.I)
    rest = phase_clause(recovery, pace_unit, coaching_policy, recovery_phase=True)
    if not work or not rest:
        return None
    if repeated:
        if not 1 <= int(repeated[1]) <= 100:
            return None
        text = f"{int(repeated[1])} x [{work} | {rest}]"
        if note:
            text += f" [coaching note: {note[2]} (instruction only, not a timed step)]"
    elif note:
        return None
    else:
        text = work + "; " + rest.replace("Run ", "Rest ", 1)
    return Conversion(text) if not parse(text).unresolved else None


def normalize_clause(part, *, pace_unit=None, coaching_policy="strict", allow_total=False):
    if converted := slash_effort_clause(part, pace_unit, coaching_policy):
        return converted
    part = re.sub(r"^(\d+\s*x\s*\d+(?:\.\d+)?)k(?=\s|$)", r"\1km", part, flags=re.I)
    easy_typo = re.fullmatch(
        r"((?:Run\s+)?\d+(?:\.\d+)?\s*(?:miles|mile|mi|km|m))\s+easys", part, re.I
    )
    if easy_typo:
        return Conversion("Run " + re.sub(r"^Run\s+", "", easy_typo[1], flags=re.I) + " easy")
    elapsed_jogs = re.fullmatch(
        r"(\d+)\s*x\s*(\d+(?:\.\d+)?)\s*(miles|mile|mi|km|m)\s+in\s+"
        r"(\d+:[0-5]\d)\s*[-–]\s*(\d+:[0-5]\d)\s+(\d+:[0-5]\d)\s+jogs?",
        part,
        re.I,
    )
    if elapsed_jogs:
        count, amount, unit, fast, slow, recovery = elapsed_jogs.groups()
        canonical = (
            f"{count} x {amount} {unit.lower()} in {fast}-{slow} "
            f"with {clock_seconds(recovery)} sec jog recovery"
        )
        return Conversion(canonical) if not parse(canonical).unresolved else None
    if coaching_policy == "athlete_preferences":
        if buffer := unclear_recovery_clause(part):
            return Conversion(buffer, True)
        bracket = re.fullmatch(r"([^()]+)\s*\(([^()]+)\)", part, re.I)
        if bracket and (buffer := unclear_recovery_clause(bracket[2])):
            work = normalize_clause(
                bracket[1].strip(), pace_unit=pace_unit, coaching_policy=coaching_policy
            )
            if work and "with lap recovery" in work.text:
                base = re.sub(r" \[buffer note: [^\[\]]+\]", "", work.text)
                return Conversion(base + f" [buffer note: {bracket[2].strip()}]", True)
            phase = phase_clause(bracket[1], pace_unit, coaching_policy)
            if phase:
                return Conversion(phase + "; " + buffer, True)
    if recovery := distance_recovery_clause(part):
        return Conversion(recovery)
    if limited := one_sided_pace(part, pace_unit, coaching_policy):
        return limited
    distance_rest = re.fullmatch(
        r"(.+?)\s+(?:w/|with)\s+([^()]+?)(?:\s*\(([^()]+)\))?",
        part,
        re.I,
    )
    if distance_rest is None:
        distance_rest = re.fullmatch(r"([^()]+)\s*\(([^()]+)\)(?:\s*\(([^()]+)\))?", part, re.I)
    if distance_rest and (recovery := distance_recovery_clause(distance_rest[2])):
        work = targeted_clause(
            distance_rest[1].strip() + " (1 sec rest)", pace_unit, coaching_policy
        )
        if work is None and re.fullmatch(
            rf"\d+\s*x\s*\d+(?:\.\d+)?\s*(?:m|km|mi)(?:\s+{DISTANCE_EFFORT})?",
            distance_rest[1].strip(),
            re.I,
        ):
            work = normalize_clause(
                distance_rest[1].strip() + " (1 sec rest)",
                pace_unit=pace_unit,
                coaching_policy=coaching_policy,
            )
        if work:
            draft = parse(work.text)
            if (
                not draft.unresolved
                and len(draft.steps) == 1
                and isinstance(draft.steps[0], Repeat)
            ):
                text = work.text.removesuffix(" with 1 sec rest recovery")
                if text == work.text:
                    return None
                text += " with " + recovery.removeprefix("Rest ") + " recovery"
                if distance_rest[3]:
                    after = re.fullmatch(r"(.+?)\s+rest after (?:the )?set", distance_rest[3], re.I)
                    duration, span = (
                        recovery_duration(after[1], coaching_policy) if after else (None, "")
                    )
                    if duration is None:
                        return None
                    text += "; " + recovery_annotation(f"Rest {duration:g} sec", span)
                return Conversion(text)
    total = (
        re.fullmatch(
            rf"(?P<range>(?P<low>\d+(?:\.\d+)?)(?:\s*[-–]\s*(?P<high>\d+(?:\.\d+)?))?)\s*(?P<unit>miles|mile|mi|km)\s+(?P<effort>(?:easy(?:/mod(?:erate)?)?|moderate)(?: {TERRAIN})?)?\s*(?:with|including|w/)\s+(?P<block>.+)",
            part,
            re.I,
        )
        if allow_total and coaching_policy == "athlete_preferences"
        else None
    )
    if total:
        bounds = [float(total["low"]), float(total["high"] or total["low"])]
        if not 0 < min(bounds) <= max(bounds) < float("inf"):
            return None
        body = total["block"]
        body = re.sub(r"\s+mixed in(?=\s*\)$)", "", body, flags=re.I)
        opening = re.fullmatch(r"(.+)\s+after (\d+(?:\.\d+)?)\s*(miles|mile|mi|km)", body, re.I)
        opening_distance = 0
        if opening:
            body = opening[1]
            opening_distance = float(opening[2]) * FACTORS[opening[3].lower()]
            if not 0 < opening_distance < max(bounds) * FACTORS[total["unit"].lower()]:
                return None
        draft = parse(body)
        inner = None
        if draft.unresolved:
            inner = normalize_clause(body, pace_unit=pace_unit, coaching_policy=coaching_policy)
            if inner is None:
                return None
            body, draft = inner.text, parse(inner.text)
        if (
            draft.unresolved
            or not draft.steps
            or any(
                isinstance(step, Step) and step.kind in ("warm_up", "cool_down")
                for step in draft.steps
            )
            or not any(isinstance(step, Repeat) or step.kind == "run" for step in draft.steps)
        ):
            return None
        unit = total["unit"].lower()
        distance_goal = max(bounds) * FACTORS[unit]
        if (
            not 0 < distance_goal < float("inf")
            or opening_distance + sum(minimum_distance(step) for step in draft.steps)
            >= distance_goal
        ):
            return None
        goal = f"{max(bounds):g} {unit} total"
        if total["high"]:
            goal += f" (prescribed {total['range']} {unit})"
        label = (" " + total["effort"].lower()) if total["effort"] else ""
        start = (
            f"Run {opening[2]} {opening[3]}{label}"
            if opening
            else f"Warm up until lap{label} [total note: {goal}]"
        )
        text = f"{start}; {body}; Cool down until lap{label} [total note: Finish {goal}]"
        return Conversion(text, inner.implied_recovery if inner else False, True)
    rest = re.fullmatch(r"Rest\s+(.+)", part, re.I)
    if rest:
        duration, span = recovery_duration(rest[1], coaching_policy)
        if duration is not None:
            return Conversion(recovery_annotation(f"Rest {duration:g} sec", span))
    scalar_rest = re.fullmatch(r"([^()]+)\s*\(([^()]+)\s+(rest|easy)\)", part, re.I)
    if scalar_rest:
        work = phase_clause(scalar_rest[1], pace_unit, coaching_policy)
        duration, span = recovery_duration(scalar_rest[2], coaching_policy)
        if work and duration is not None:
            recovery = (
                f"Run {duration:g} sec easy"
                if scalar_rest[3].lower() == "easy"
                else f"Rest {duration:g} sec"
            )
            return Conversion(
                work + "; " + recovery_annotation(recovery, span, scalar_rest[3].lower())
            )
    timed_rest = re.fullmatch(
        rf"(\d+)\s*x\s*(\d+(?:\.\d+)?\s*{DURATION_UNITS})(?:\s+({EFFORT}))?\s*\(([^()]*)\s+rest\)",
        part,
        re.I,
    )
    if timed_rest:
        count, duration, effort, recovery = timed_rest.groups()
        duration = seconds(duration)
        recovery, span = recovery_duration(recovery, coaching_policy)
        if duration is None or recovery is None or not float(duration).is_integer():
            return None
        label = " " + effort.lower() if effort else ""
        return Conversion(
            recovery_annotation(
                f"{count} x {int(duration)} sec{label} with {recovery:g} sec rest recovery", span
            )
        )
    hill = re.fullmatch(
        rf"(\d+)\s*x\s*(~?\s*\d+(?:\.\d+)?\s*{DURATION_UNITS})\s+"
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
        if coaching_policy == "athlete_preferences":
            inner = infer_shorthand_units(inner)
        converted = targeted_clause(inner, pace_unit, coaching_policy)
        duration, span = recovery_duration(rest, coaching_policy)
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
        separator = "; " + recovery_annotation(f"Rest {duration:g} sec", span) + "; "
        return Conversion(separator.join([converted.text] * int(count)))
    if (targeted := targeted_clause(part, pace_unit, coaching_policy)) is not None:
        return targeted
    explicit = re.fullmatch(
        rf"(\d+)\s*x\s*(\d+(?:\.\d+)?)\s*(miles|mi|km|m)(?:\s+({DISTANCE_EFFORT}))?"
        r"\s*\(\s*([^()]+?)"
        r"\s+(rest|easy|walk/jog)(?:\s+recovery)?\s*\)",
        part,
        re.I,
    )
    if explicit:
        count, amount, unit, effort, rest, recovery_effort = explicit.groups()
        duration, span = recovery_duration(rest, coaching_policy)
        if duration is None:
            return None
        label = f" {effort.lower()}" if effort else ""
        return Conversion(
            recovery_annotation(
                f"{count} x {amount} {unit.lower()}{label} with {duration:g} sec {recovery_effort.lower()} recovery",
                span,
                recovery_effort.lower(),
            )
        )

    stride = re.fullmatch(
        r"(?:(\d+)\s*(?:x\s*)?)?(?:(easy|smooth|hard|fast)\s+)?(?:(uphill|downhill|hill)\s+)?strides",
        part,
        re.I,
    )
    if stride:
        if stride[1] is None and coaching_policy != "athlete_preferences":
            return None
        label = " ".join(filter(None, ((stride[2] or "").lower(), (stride[3] or "").lower())))
        note = (
            " [coaching note: Default 4 strides - count unspecified by coach. Effort and recovery end at Lap.]"
            if stride[1] is None
            else ""
        )
        return Conversion(
            f"{stride[1] or 4} "
            + (label + " " if label else "")
            + "strides with lap recovery"
            + note,
            True,
        )

    timed = re.fullmatch(
        rf"(\d+)\s*x\s*(\d+(?:\.\d+)?\s*{DURATION_UNITS})\s+"
        rf"((?:uphill |downhill |hill |fast |hard |smooth )?(?:strides|sprints)|{EFFORT})",
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
        rf"(\d+)\s*x\s*(\d+(?:\.\d+)?)\s*(miles|mi|km|m)(?:\s+({DISTANCE_EFFORT}))?",
        part,
        re.I,
    )
    if distance:
        count, amount, unit, label = distance.groups()
        return Conversion(
            f"{count} x {amount} {unit.lower()}"
            + (f" {label.lower()}" if label else "")
            + " with lap recovery",
            True,
        )

    repeated = re.fullmatch(r"(\d+)\s*x\s*(?:\((.*)\)|([^()]+))", part, re.I | re.S)
    if (
        repeated
        and "(" not in (repeated[2] or repeated[3])
        and ")" not in (repeated[2] or repeated[3])
    ):
        body = (repeated[2] or repeated[3]).strip()
        phases = re.split(
            rf"\s*[,;+]\s*|(?<=[a-z])\s*:\s*(?=\d)|\s+plus\s+|(?<!\d)/\s*(?=~?(?:\d+:[0-5]\d\b|\d+(?:\.\d+)?\s*(?:{TIME_UNITS}|s|miles|mile|mi|km|m)\b))",
            body,
            flags=re.I,
        )
        duration = r"(?:\d+(?:\.\d+)?\s*(?:seconds|secs|sec|s|minutes|mins|min)|\d+:[0-5]\d)"
        adjacent = re.fullmatch(
            rf"\s*({duration}\s+{EFFORT})\s+({duration}\s+{EFFORT})\s*", body, re.I
        )
        if len(phases) == 1 and adjacent:
            phases = [adjacent[1], adjacent[2]]
        if not 2 <= len(phases) <= 8:
            return None
        steps = []
        for phase_index, phase in enumerate(phases):
            step = phase_clause(phase, pace_unit, coaching_policy, recovery_phase=phase_index > 0)
            if step is None:
                return None
            steps.append(step)
        # Preserve the old two-phase form where it already has the same semantics.
        if len(steps) == 2:
            legacy = f"{repeated[1]} x {steps[0][4:]} with {steps[1][4:]} recovery"
            if not parse(legacy).unresolved:
                return Conversion(legacy)
        return Conversion(
            f"{repeated[1]} x [" + " | ".join(steps) + "]",
            any("[buffer note:" in step for step in steps),
        )
    return None
