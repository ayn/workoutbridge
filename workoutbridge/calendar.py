"""Bounded local ICS import. No remote URLs or account credentials."""

from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from zoneinfo import ZoneInfo

import recurring_ical_events
from icalendar import Calendar


@dataclass(frozen=True)
class Event:
    source: str
    uid: str
    recurrence_id: str
    date: str
    title: str
    description: str
    cancelled: bool = False

    @property
    def prescription(self) -> str:
        return self.description.strip() or self.title.strip()


def identity_time(value) -> str:
    if isinstance(value, datetime) and value.tzinfo:
        return value.astimezone(UTC).isoformat()
    return value.isoformat()


def import_calendar(
    data: bytes,
    *,
    source: str,
    timezone: str,
    start: date,
    end: date,
    max_events: int = 500,
) -> list[Event]:
    if not source.strip() or not 0 < (end - start).days <= 93:
        raise ValueError("Require a source and a date window of 1-93 days")
    if len(data) > 2_000_000 or not 0 < max_events <= 5000:
        raise ValueError("Calendar exceeds import limits")
    zone = ZoneInfo(timezone)
    try:
        cal = Calendar.from_ical(data)
        if cal.name != "VCALENDAR":
            raise ValueError("Expected VCALENDAR")
        seen = set()
        recurring = set()
        for component in cal.walk("VEVENT"):
            uid = str(component.get("UID", "")).strip()
            if not uid or "DTSTART" not in component or component.errors:
                raise ValueError("Event requires valid UID and DTSTART")
            for name in ("DTSTART", "DTEND", "RECURRENCE-ID", "RDATE", "EXDATE"):
                fields = component.get(name, [])
                for field in fields if isinstance(fields, list) else [fields]:
                    if field.params.get("TZID"):
                        for value in getattr(field, "dts", [field]):
                            if not isinstance(value.dt, datetime) or value.dt.tzinfo is None:
                                raise ValueError("Unresolved explicit event timezone")
            rid = component.get("RECURRENCE-ID")
            key = (uid, identity_time(rid.dt) if rid else "")
            if key in seen:
                raise ValueError("Duplicate calendar event identity")
            seen.add(key)
            if rid or "RRULE" in component or "RDATE" in component:
                recurring.add(uid)
            # Disallow sub-daily or multiplying rules before expansion.
            rule = component.get("RRULE")
            if rule and (
                str(rule.get("FREQ", [""])[0]) not in {"DAILY", "WEEKLY", "MONTHLY", "YEARLY"}
                or any(k in rule for k in ("BYSECOND", "BYMINUTE", "BYHOUR"))
            ):
                raise ValueError("Only daily or less frequent recurrence is supported")
        events = recurring_ical_events.of(cal).between(
            datetime.combine(start, time.min, zone),
            datetime.combine(end, time.min, zone),
        )
        if len(events) > max_events:
            raise ValueError("Too many events in import window")
        result = []
        for component in events:
            when = component["DTSTART"].dt
            if isinstance(when, datetime):
                when = when.replace(tzinfo=zone) if when.tzinfo is None else when
                day = when.astimezone(zone).date()
            else:
                day = when
            if not start <= day < end:
                continue
            uid = str(component["UID"])
            rid = component.get("RECURRENCE-ID")
            recurrence_id = (
                identity_time(rid.dt if rid else component["DTSTART"].dt)
                if uid in recurring
                else ""
            )
            result.append(
                Event(
                    source,
                    uid,
                    recurrence_id,
                    day.isoformat(),
                    str(component.get("SUMMARY", "")),
                    str(component.get("DESCRIPTION", "")),
                    str(component.get("STATUS", "")).upper() == "CANCELLED",
                )
            )
        return sorted(result, key=lambda e: (e.date, e.uid, e.recurrence_id))
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("Invalid or unsupported calendar; review the local file") from exc
