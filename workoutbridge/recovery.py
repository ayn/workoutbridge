"""Safe operational diagnostics. Never persist arbitrary provider exception text."""

from datetime import datetime, timedelta

from .publishing import ReviewRequired


class ProviderUnavailable(ValueError):
    """Transient transport failure; replay must still pass durable receipt checks."""


SAFE_REASONS = {
    "COROS authentication expired; reconnect": "provider_authentication",
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
    "Previously scheduled entry is absent; reconcile manually": "scheduled_entry_missing",
    "Recorded destination identity is missing; refusing overwrite": "destination_identity_missing",
    "Multiple destination workouts have this identity": "duplicate_destination_identity",
    "Duplicate destination calendar entries require review": "duplicate_schedule",
    "Scheduled entry did not verify uniquely": "schedule_verification_failed",
    "Updated workout did not verify": "update_verification_failed",
    "Event moved; reconcile the previous scheduled entry": "event_moved",
    "Resolve the earlier pending write before applying edits": "pending_previous_revision",
    "Legacy receipt requires manual migration; do not reset it": "legacy_receipt",
    "Another source identity has an overlapping local intent": "overlapping_source",
    "Remote identity exists but local receipt is missing": "missing_local_receipt",
    "Review and approve this exact account and prescription": "approval_mismatch",
    "Cancelled event requires manual reconciliation": "cancelled_event",
    "Cancelled COROS event requires manual reconciliation": "cancelled_event",
    "Unrecognized COROS result; inspect privately before continuing": "invalid_destination_response",
    "Unrecognized COROS scheduled detail": "invalid_destination_response",
    "Invalid COROS inline course JSON": "invalid_destination_response",
    "Approve this exact COROS account and prescription": "approval_mismatch",
    "Approve this exact COROS receipt before reconciling": "approval_mismatch",
    "No matching pending COROS intent": "missing_pending_receipt",
    "Cannot replace the recorded COROS identity": "destination_identity_mismatch",
    "Unexpected Garmin workout enumeration": "invalid_destination_response",
    "Incomplete Garmin workout enumeration; refusing writes": "incomplete_destination_response",
    "Unexpected Garmin calendar response; refusing writes": "invalid_destination_response",
    "Scheduled workout has no valid date; refusing writes": "invalid_destination_response",
    "Upload outcome uncertain: no valid workout ID": "uncertain_creation",
    "Garmin account mismatch or missing stable profile ID": "account_mismatch",
    "COROS account mismatch": "account_mismatch",
}


def publication_failure(exc, previous, now, stage):
    # Keep status/type metadata, never arbitrary exception bodies, URLs or headers.
    status = getattr(getattr(exc, "response", None), "status_code", None)
    status = (
        int(status)
        if isinstance(status, int) and not isinstance(status, bool) and 100 <= status <= 599
        else None
    )
    authentication = False
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
        from garminconnect import (
            GarminConnectAuthenticationError,
            GarminConnectConnectionError,
            GarminConnectTooManyRequestsError,
        )

        authentication = isinstance(exc, GarminConnectAuthenticationError)

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
    transient = transient or status in {408, 429, 500, 502, 503, 504}
    reason = str(exc) if isinstance(exc, (ReviewRequired, ValueError)) else ""
    code = SAFE_REASONS.get(reason, "publication_requires_review")
    transient = transient or code == "publisher_busy"
    if transient:
        code, message = (
            "provider_unavailable",
            "Destination temporarily unavailable; receipts will be checked before retrying.",
        )
    elif authentication or status in {401, 403} or code == "provider_authentication":
        code = "provider_authentication"
        message = "Destination authentication or access check failed. Check the connection before retrying."
    elif status == 404:
        code = "destination_not_found"
        message = "Destination resource was not found. Review the saved receipts before retrying."
    elif status in {400, 409, 422}:
        code = "destination_rejected_request"
        message = "Destination rejected the request. Review the saved receipts before retrying."
    else:
        message = (
            reason
            if reason in SAFE_REASONS
            else "Publication requires review; inspect the saved receipts before retrying."
        )
    attempt = (previous or {}).get("attempt", 0) + 1
    delays = (300, 1800, 7200)
    # Retry checks indefinitely at a capped cadence. Publishers consult durable
    # intents before any write; a retry is never permission to repeat creation.
    delay = delays[min(attempt - 1, len(delays) - 1)]
    if code == "provider_authentication":
        delay = 6 * 3600
    retry = (datetime.fromisoformat(now) + timedelta(seconds=delay)).isoformat()
    return dict(
        code=code,
        message=message,
        at=now,
        stage=stage,
        exception_type=type(exc).__name__,
        http_status=status,
        attempt=attempt,
        next_retry=retry,
        retryable=transient,
    )
