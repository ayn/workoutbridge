"""Identify empty calendar busy placeholders without hiding workout details."""


def is_calendar_block(event):
    return (
        event.title.strip().casefold() == "busy"
        and event.description.strip().casefold() in {"", "busy"}
        and event.structured_text.strip().casefold() in {"", "busy"}
    )
