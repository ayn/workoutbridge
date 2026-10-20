# Architecture and Roadmap

## Boundaries

Source adapters -> preserved prescription -> deterministic parser -> reviewed
workout model -> destination adapter -> reconciliation record.

Keep source access independent of destinations. An ICS feed is not an editing
API and may omit important description details.

## Incremental Milestones

- [x] Public MIT repository, synthetic fixtures, tests, local draft CLI.
- [ ] ICS import: UID, RECURRENCE-ID, time zones, cancellations, bounded recurrence
  expansion, updates, and missing descriptions. Start with local file import.
- [ ] Native repeat groups, explicit recoveries, pace conversion, and note labels.
- [ ] Review UI with original text beside structured steps.
- [ ] Garmin adapter using python-garminconnect, version pinned when integrated.
  Prove authentication, refresh, read-back, upload, and scheduling in isolation.
- [ ] Persistent per-account/source-event destination mapping. Serialize writes
  per account and reconcile uncertain request outcomes before retrying.
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

### Duplicate-Prevention Contract (Not Yet Implemented)

The current CLI only emits drafts. There is no publisher or duplicate-prevention
implementation yet. The following are release gates, not existing guarantees:

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
