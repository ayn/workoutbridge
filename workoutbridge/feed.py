"""Bounded local-file or HTTPS calendar input for the local CLI."""

from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

MAX_BYTES = 2_000_000


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def read_calendar(location: str) -> bytes:
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
