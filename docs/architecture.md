# Architecture and Roadmap

## Boundaries

Source adapters -> preserved prescription -> deterministic parser -> reviewed
workout model -> destination adapter -> reconciliation record.

Keep source access independent of destinations. An ICS feed is not an editing
API and may omit important description details.

## Incremental Milestones

- [x] Public MIT repository, synthetic fixtures, tests, local draft CLI.
- [x] Local ICS import: UID, RECURRENCE-ID, time zones, cancellations, and bounded
  recurrence expansion using icalendar/recurring-ical-events.
- [x] Narrow explicit interval grammar, native repeat groups, explicit recoveries,
  rep-time to speed conversion, and note labels.
- [x] Local JSON review plan with content-bound approval and dry-run default.
- [ ] Review UI with original text beside structured steps.
- [x] Garmin adapter using python-garminconnect 0.3.19, tested with fake clients.
- [ ] Live verification of authentication/refresh, read-back, upload, and scheduling.
- [x] Single-host persistent per-account/source-event destination mapping,
  serialized writes, and fail-closed handling of uncertain request outcomes.
- [ ] Hosted distributed claims, encrypted session management, and remote polling.
- [ ] Hosted beta with authentication, quotas, observability, and deletion/export.
- [ ] Final Surge write-back only after investigating supported partner access.

## Proposed Cloudflare Hosting

Workers Static Assets for UI, Workers API, D1 records, Cron/Queues for ingestion,
and Containers for a conventional Python Garmin worker. This is a proposal,
not deployed infrastructure. Containers require paid usage; impose budgets.

Garmin cloud login may be rate limited or blocked. Verify it before committing
to a hosted product. The unofficial client is not an official OAuth integration.
Provide a local/self-hosted option if cloud authentication is unreliable.

Encrypt account sessions and secret feed URLs at application level, with keys
outside the database. Do not retain account passwords by default. Container-local
files must not be the durable session store. Redact request URLs and auth payloads
from logs. Plan reauthentication and revocation per user.

Remote feed fetching requires SSRF protection: block private/link-local targets,
validate redirects and DNS results, limit size and duration, and accept only
supported URL schemes. Keep fetching out of the initial local-only CLI.

## Publishing Acceptance Criteria

No live writes before explicit review. Preserve original assignment metadata.
Read back uploaded steps and scheduled date. Handle transient failures,
expired sessions, duplicate jobs, moved events, and time zones. Test with fakes
first; never run public CI against real athlete accounts.

### Duplicate-Prevention Contract

Implemented and tested for the local single-host publisher below. This is not
a promise of universal exactly-once behavior or a hosted production release.
Ambiguous outcomes, moved events, and cancellations are blocked for manual review.

- Persist source identity scoped to user, destination account, source connection,
  event UID, and recurrence instance. Titles alone are never identity.
- Keep a normalized content hash separately from identity. Repeated unchanged
  polls are no-ops; changed prescriptions update the recorded destination workout.
- Persist workout ID and calendar schedule identity separately. A scheduled
  workout can be reused, but the same event must not create another calendar entry.
- Enforce database uniqueness and atomic job claims. Concurrent refreshes and
  queued retries must not race into multiple writes.
- Persist publishing intent before remote writes. If upload times out after
  Garmin may have accepted it, reconcile before retrying. If the outcome cannot
  be established, block for review rather than blindly uploading again.
- Treat rescheduling, cancellation, and deletion as explicit reviewed operations.
  Do not delete destination entries because an event disappears from a feed.
- Detect possible overlap across feeds or pre-existing destination workouts and
  ask for reconciliation. Do not silently merge workouts by title/date.
- Do not promise exactly-once delivery when an upstream API lacks an idempotency
  contract. Prefer an unresolved job over a potentially duplicated workout.

Required red/green tests cover repeated polls, changed descriptions, moved events,
recurrence exceptions, account isolation, concurrent claims, process restarts,
upload-success/response-loss, schedule-success/response-loss, and ambiguous
pre-existing destination entries. A fake provider must count create and schedule
calls so tests assert no extra writes, not merely matching final JSON.

## Sources Checked

- [icalendar parsing API](https://icalendar.readthedocs.io/en/stable/)
- [recurring-ical-events examples](https://recurring-ical-events.readthedocs.io/en/latest/user-guide/examples.html)
- [python-garminconnect](https://github.com/cyberjunky/python-garminconnect):
  inspected installed 0.3.19 workout, training, and authentication methods.

The adapter uses library upload/update/schedule methods and the authenticated
numeric `profile_id`. It does not reproduce private endpoint URLs or collect
passwords. Third-party request errors are suppressed in CLI output to avoid
leaking session details.
