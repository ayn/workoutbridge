"""Bounded local-file or HTTPS calendar input for the local CLI."""

import base64
import binascii
import re
from pathlib import Path
from urllib.parse import parse_qs, quote, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

MAX_BYTES = 2_000_000


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def calendar_feed_url(location: str) -> str:
    """Normalize a supported calendar subscription without fetching a web page."""
    parsed = urlsplit(location)
    if re.fullmatch(r"p[0-9]+-caldav\.icloud\.com", parsed.hostname or ""):
        if (
            parsed.scheme not in ("https", "webcal")
            or parsed.username
            or parsed.password
            or parsed.port not in (None, 443)
            or parsed.query
            or parsed.fragment
            or not re.fullmatch(r"/published/[0-9]+/[A-Za-z0-9_-]+", parsed.path)
        ):
            raise ValueError("Use the public iCloud calendar subscription link")
        return parsed._replace(scheme="https").geturl()
    if parsed.hostname != "calendar.google.com":
        return location
    message = "Use a Google Calendar sharing link or its Secret address in iCal format"
    if (
        parsed.scheme != "https"
        or parsed.username
        or parsed.password
        or parsed.port not in (None, 443)
        or parsed.fragment
    ):
        raise ValueError(message)
    if parsed.path.startswith("/calendar/ical/") and parsed.path.endswith(".ics"):
        return location
    query = parse_qs(parsed.query, keep_blank_values=True)
    sources, encoded = query.get("src", []), query.get("cid", [])
    if len(sources) + len(encoded) != 1:
        raise ValueError(message)
    if not re.fullmatch(r"/calendar(?:/embed|/u/\d+(?:/r)?)?/?", parsed.path):
        raise ValueError(message)
    if encoded:
        try:
            calendar = base64.b64decode(
                encoded[0] + "=" * (-len(encoded[0]) % 4), altchars=b"-_", validate=True
            ).decode("utf-8")
        except (ValueError, UnicodeError, binascii.Error):
            raise ValueError(message) from None
    else:
        calendar = sources[0]
    if len(calendar) > 512 or not re.fullmatch(r"[A-Za-z0-9_.+#-]+@[A-Za-z0-9.-]+", calendar):
        raise ValueError(message)
    return (
        "https://calendar.google.com/calendar/ical/"
        + quote(calendar, safe="")
        + "/public/basic.ics"
    )


def read_calendar(location: str) -> bytes:
    location = calendar_feed_url(location)
    parsed = urlsplit(location)
    if parsed.scheme:
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
        ):
            raise ValueError("Use a local path or HTTPS feed without embedded credentials")
        request = Request(location, headers={"Accept": "text/calendar"})
        # Refuse redirects rather than forwarding a private feed to another endpoint.
        with build_opener(NoRedirect()).open(request, timeout=30) as response:
            data = response.read(MAX_BYTES + 1)
    else:
        with Path(location).open("rb") as handle:
            data = handle.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise ValueError("Calendar exceeds size limit")
    return data
