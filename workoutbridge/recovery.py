"""Safe operational diagnostics. Never persist arbitrary provider exception text."""

from datetime import datetime, timedelta

from .publishing import ReviewRequired


class ProviderUnavailable(ValueError):
    """Transient transport failure; replay must still pass durable receipt checks."""


SAFE_REASONS = {
    "COROS event changed or moved; reconcile the existing entry": "prescription_changed",
    "COROS write is pending; do not retry creation": "uncertain_creation",
    "COROS creation outcome uncertain; do not repeat": "uncertain_creation",
    "Upload outcome uncertain; not repeating remote creation": "uncertain_creation",
    "Schedule outcome uncertain; not scheduling again": "uncertain_schedule",
    "COROS read-back differs; reconcile before continuing": "destination_changed",
    "Destination read-back differs; reconcile before retry": "destination_changed",
    "COROS day is not verifiably empty; review its existing schedule": "existing_schedule",
    "Overlapping COROS publication already exists": "overlapping_workout",
    "Possible existing workout or overlapping source feed": "overlapping_workout",
    "Another publisher is active; retry later": "publisher_busy",
    "Garmin description is too long; shorten notes before publishing": "notes_too_long",
}


def publication_failure(exc, previous, now, stage):
    # Import optional web transport dependencies only when present.
    transient = isinstance(exc, (ProviderUnavailable, TimeoutError, ConnectionError))
    try:
        import httpx

        transient = transient or isinstance(exc, httpx.TransportError)
        if isinstance(exc, httpx.HTTPStatusError):
            transient = exc.response.status_code in {408, 429, 500, 502, 503, 504}
    except ImportError:
        pass
    try:
        import requests

        transient = transient or isinstance(exc, (requests.Timeout, requests.ConnectionError))
    except ImportError:
        pass
    try:
        from garminconnect import GarminConnectConnectionError, GarminConnectTooManyRequestsError

        if isinstance(exc, GarminConnectTooManyRequestsError):
            transient = True
        elif isinstance(exc, GarminConnectConnectionError):
            response = getattr(exc, "response", None)
            transient = response is None or getattr(response, "status_code", None) in {
                408,
                429,
                500,
                502,
                503,
                504,
            }
    except ImportError:
        pass
    reason = str(exc) if isinstance(exc, ReviewRequired) else ""
    code = SAFE_REASONS.get(reason, "publication_requires_review")
    transient = transient or code == "publisher_busy"
    if transient:
        code, message = (
            "provider_unavailable",
            "Destination temporarily unavailable; receipts will be checked before retrying.",
        )
    else:
        message = (
            reason
            if reason in SAFE_REASONS
            else "Publication requires review; inspect the saved receipts before retrying."
        )
    attempt = (previous or {}).get("attempt", 0) + 1
    delays = (300, 1800, 7200)
    retry = (
        (datetime.fromisoformat(now) + timedelta(seconds=delays[attempt - 1])).isoformat()
        if transient and attempt <= len(delays)
        else None
    )
    return dict(
        code=code,
        message=message,
        at=now,
        stage=stage,
        attempt=attempt,
        next_retry=retry,
        retryable=transient,
    )
