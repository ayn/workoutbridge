# COROS Pilot

WorkoutBridge uses the [official COROS MCP gateway](https://github.com/coroslab/COROS-MCP)
and its browser OAuth flow. No language model or AI API is involved in parsing or
publishing. The separately approved partner REST API is not used. The implementation
does not depend on, or redistribute, COROS's example login helper.

## Connect

In the private web app, open **Connections → Connect COROS**. Choose the account's
region, open the authorization link, sign in on COROS, and return to **Finish
connection**. Create a sync rule from the desired source to this saved profile.
Review its preview, then publish manually or explicitly enable hourly publishing.
The same source can have separate Garmin and COROS sync rules.

CLI authentication also works without a local browser callback server:

```sh
uv sync --locked --extra coros
umask 077
SESSION="$HOME/.config/garmin-sessions/coros-test"
uv run --locked --extra coros workoutbridge auth coros \
  --profile coros-test --session-dir "$SESSION" --region us
```

Open the returned `login_url` privately, authorize, then finish with the same path:

```sh
uv run --locked --extra coros workoutbridge auth coros \
  --profile coros-test --session-dir "$SESSION" --finish
```

`pending` means browser authorization is still outstanding. Use `eu` or `cn`
instead of `us` when appropriate. Start with a new session directory on each new
attempt or reauthentication; keep the same profile to retain its original ledger.
The profile rejects a different account or provider. Sign-in expires after ten
minutes. No passwords belong in arguments, configuration files, or Git.

Use the normal `plan` and `publish` commands with `--profile coros-test` and
`--extra coros` instead of `--extra garmin`. Dry-run stays local. Both `--apply
--approve REVIEW_HASH` and `--yolo` retain validation and duplicate checks.

## Supported Conversion

- Running workouts, warm-up/run/recovery/cooldown, distance, time, and lap button.
- Native repeat groups, 1-20 repetitions. Nested groups and warm-up/cooldown inside
  groups require review. Final stationary recovery can be omitted by expanding
  the final repetition; timed easy running remains a run step.
- Explicit pace ranges become whole seconds/km, COROS's native unit. Distances
  become whole meters and durations whole seconds, rounded to nearest integer
  (halves upward). Unsupported pace ranges require review; no pace targets are
  invented from effort words. The web preview displays min/mi.
- Original instructions, effort labels, and rep completion-time notes remain in
  the course description. COROS's MCP schema does not expose per-step note fields.
- Workout titles must fit COROS's 100-character limit. Long titles require review;
  they are never silently truncated. Calendar writes support today through +90
  days in the account timezone; the web app previews the next 15 days.

## Receipts and Recovery

`createScheduledWorkout` creates a calendar entry directly, avoiding separate
library copies. The adapter reads its stored `Course JSON` back using
`queryScheduledWorkoutDetails` and verifies all requested fields. Numeric IDs
remain strings. Repeating an unchanged publication verifies and reuses its receipt.

A durable intent is committed before creation, under the existing account ledger
lock. Network errors, unknown responses, and read-back mismatches stop publishing.
Do not delete the database or repeat creation after a timeout. An explicit
operator reconciliation can use `CorosPublisher.reconcile(...)` with the original
approved values and the observed `idInPlan`; it only reads COROS, verifies the
whole course, and repairs the matching pending local receipt. It never creates.
No automatic matching by title or guessing of remote IDs is performed.

This first version deliberately requires review for changed/moved events and for
new events on a day that already has an untracked schedule. It does not update,
move, or delete existing calendar entries. Resolve changes in COROS and reconcile
receipts before re-enabling an automatic sync. Unknown human-readable response
formats also stop for review instead of guessing. Support for tracked updates and
broader calendar enumeration is follow-up work.

Session files are 0600 in 0700 directories, outside the checkout. OAuth refresh
tokens persist privately; token renewal is serialized and account identity is
verified through the authenticated OIDC `/userinfo` endpoint before publishing.
Use one publisher host with the original database. Back up sessions, profiles,
and receipts encrypted together; never publish them or private feed snapshots.

## Verification

Offline tests use synthetic data and mocked HTTP only. On 2026-10-21, a live
dedicated test account accepted a synthetic workout scheduled for 2026-10-22:
lap warm-up, 2 x (200 m in 60-64 seconds, 2 minutes easy running), lap cooldown.
Read-back matched native repeats, target units, notes, and pace ranges. The first
encoded-text response left an uncertain receipt; read-only verification and explicit
reconciliation recovered it, and a repeated publication reused the same entry.
This verifies the calendar, not delivery to a physical watch. The synthetic entry
can be removed manually in the COROS app.

References: [COROS tool guide](https://github.com/coroslab/COROS-MCP/blob/main/docs/en/tools.md),
[build documentation](https://support.coros.com/hc/en-us/articles/53181619102996-Build-on-COROS-MCP).
