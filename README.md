# WorkoutBridge

Turn plain-text running and coaching prescriptions into reviewable structured
workouts for Garmin Connect. Designed for training calendars from Final Surge,
Google Calendar, iCloud Calendar, and other iCalendar (ICS) sources.

**Early development, not a hosted service.** The web app is the intended product;
this repository now has its first local backend workflow: ICS file import,
review plans, Garmin payloads, and a persistent opt-in publisher. The full pipeline
is tested with fake Garmin accounts. A limited live test has also verified
uploading, calendar scheduling, and repeat-publish reuse in a dedicated account;
watch delivery has not been verified.
No web UI, automatic feed polling, or Final Surge write-back yet.
Not affiliated with Garmin, Final Surge, Google, Apple, or any coach.

## Try It

Requires Python 3.11+ for parsing, or Python 3.12+ for the Garmin extra.
The local publisher supports Linux/macOS and uses a single-host file lock.

```sh
python -m venv .venv
. .venv/bin/activate
python -m pip install -e .
printf '%s\n' 'Warm up until lap; Run 10 min easy; Cool down 5 min' | workoutbridge
python -m unittest discover -s tests -v
```

For a reproducible developer setup, use `uv sync --locked --extra garmin`
and `uv run --locked --extra garmin python -m unittest discover -s tests -v`.

To connect Garmin, run from this checkout with Python 3.12+:

```bash
uv sync --locked --extra garmin
uv run --locked --extra garmin workoutbridge auth garmin \
  --session-dir "$HOME/.config/garmin-sessions/workoutbridge-test"
```

Enter your email, hidden password, and MFA code if requested. Use a new session
directory for each account; the command prints the numeric account ID needed
for planning and publishing. Tokens stay outside the checkout. Authentication
does not upload workouts.

Verify the session with a read-only check, replacing `12345` with that account ID
and the date with the day you want to inspect:

```bash
uv run --locked --extra garmin workoutbridge garmin-check \
  --session-dir "$HOME/.config/garmin-sessions/workoutbridge-test" \
  --account-id 12345 --date 2027-01-05
```

See [Calendar to Garmin](#calendar-to-garmin) for creating a review plan and
publishing, or [Garmin Login](#garmin-login) for session renewal.

The parsing example outputs JSON with the original prescription, normalized steps, unresolved
clauses, and `requires_review: true`. Exit status 2 means unresolved input.
Exit status 0 means parsing succeeded, **not** permission to publish.

The deliberately narrow grammar accepts semicolon-separated Warm up, Run, Rest,
and Cool down steps with explicit duration/distance or "until lap", plus effort
labels. It also accepts explicit interval prescriptions such as:

```text
Warm up until lap; 4 x 200 m in 62-64 sec with 2 min walk/jog recovery; Cool down 5 min
```

This produces a native repeat group, speed targets equivalent to the rep times,
rep-time notes, and recovery between repetitions (not after the last rep).
`3 x 400 m in 2:04-2:08 with 3 min easy recovery` is also supported.
Easy recovery remains a Run step. No recovery or cooldown is inferred.
Other natural-language formats remain unresolved; no LLM API is required.

## Calendar to Garmin

Keep input files, review output, sessions, and receipts outside the checkout.
Use a local file exported/downloaded from an authorized calendar; this version
does not fetch remote feed URLs.

```sh
umask 077
workoutbridge plan /private/path/training.ics \
  --source training-calendar --timezone Asia/Taipei \
  --start 2027-01-01 --end 2027-02-01 --account-id 12345 \
  > /private/path/review.json
```

Replace the example paths, dates, timezone, and profile ID with your own.
`--end` is exclusive; windows are limited to 93 days. Use `--uid` (repeatable)
to select individual events. Unsupported/cancelled events stay visible for review
and block batch publishing. Descriptions take precedence over titles as the
prescription; both are retained, and the review includes original text and steps.

### Explicit Conversion Preferences

For simple easy-run prescriptions, opt in during planning:

```sh
workoutbridge plan /private/path/training.ics \
  --source training-calendar --timezone Asia/Taipei \
  --start 2027-01-01 --end 2027-02-01 --account-id 12345 \
  --easy-run-range higher --hill-recovery lap \
  > /private/path/review.json
```

- `--easy-run-range higher` selects the upper distance in a range such as
  `5-7 miles easy`. It also adds warm-up and cooldown ending on Lap Button
  Press to these simple runs. This is an explicit combined review policy,
  not the default parser behavior.
- Exact distances and `easy/mod` are supported. The original prescription and
  selected settings are kept in Garmin workout notes; no numeric pace is invented.
- Optional additions such as `plus 3 x 15 second hills` become native repeat
  groups. They require `--hill-recovery lap`, which adds lap-ended recovery
  between repetitions, not after the last repetition.
- This policy only accepts complete simple prescriptions. Explicit warm-up,
  cooldown, recovery, or other complex instructions are not overwritten; they
  continue through the normal parser and may require manual review.
- Rest days and conditional instructions remain unresolved and block a batch.
  Select reviewed run events with `--uid`; nothing is silently published or
  dropped by these flags.

Preferences are included in the review hash. Regenerate older review files if
validation rejects them after an upgrade, keeping the same source label and
publishing database for duplicate protection.

On Python 3.12+, install `python -m pip install -e '.[garmin]'`.
Use an isolated `python-garminconnect` session directory and its numeric
profile ID. Create the session with the interactive login command below.
Do not use a different athlete's session. An expired session requires renewal
through the native authentication command below, into a new directory.

### Garmin Login

No Dotfit installation is needed. In an interactive terminal, with Python 3.12+
and the Garmin extra, run from the WorkoutBridge checkout:

```bash
uv run --locked --extra garmin workoutbridge auth garmin \
  --session-dir "$HOME/.config/garmin-sessions/workoutbridge-test"
```

Enter the test account's email, hidden password, and hidden MFA code if requested.
The command prints the numeric `account_id` to use in plans and publishing.
It creates a directory with mode 0700 and saves session tokens with mode 0600.
Use that exact directory as `--session-dir`; there is no extra nested directory.
Credentials are not accepted as CLI flags. No workouts are uploaded or scheduled.

Check the saved session without changing workouts (replace `12345` with the
printed account ID and select the calendar date to check):

```bash
uv run --locked --extra garmin workoutbridge garmin-check \
  --session-dir "$HOME/.config/garmin-sessions/workoutbridge-test" \
  --account-id 12345 --date 2027-01-05
```

The directory must not already exist, to prevent accidentally reusing another
athlete's session. To renew authentication, choose a new private directory and
confirm that the returned account ID matches the old account. Keep the same
publishing state database; changing authentication must not reset duplicate
protection. A failed/cancelled attempt may leave its private directory behind;
use another new path for a later attempt and inspect old directories before
removing them. Do not repeatedly retry rate-limited logins.

Keep sessions outside the checkout and never share tokens, passwords, or MFA
codes. Authentication depends on Garmin's unofficial login flow and can fail
when Garmin changes it or rate limits requests.

```sh
workoutbridge publish /private/path/review.json \
  --account-id 12345 --session-dir /private/path/garmin-session \
  --state-db /private/path/workoutbridge.sqlite
```

That is a **dry run** and does not authenticate. After inspecting the complete
review plan, add `--apply --approve HASH`, replacing HASH with its `review_hash`.
The hash binds approval to the account and exact reviewed content, not a generic
"yes". It is a confirmation mechanism, not cryptographic authentication.
Each successful event prints a verified destination workout ID and date.

## Duplicate Protection

- SQLite receipts bind an event UID/recurrence instance and stable source label
  to a Garmin account, workout ID, and scheduled date.
- Identical imports verify existing state without another create/schedule.
- Approved prescription edits update the existing workout ID.
- Process-held locking serializes publishers using the same local database.
- Remote-write intent is committed before upload/update/schedule.
- Lost responses are reconciled using remote identity markers and calendar
  read-back. Uncertain outcomes stop for review, rather than blindly retrying.
- Moved/cancelled events and suspected cross-feed overlap require reconciliation.
- Overlap checks include pending local intents, not only completed uploads.

**Do not delete the state database or change source labels to force a retry.**
Back it up alongside sessions, with private permissions. If a run stops, rerun
the same reviewed plan with the same database; if it remains blocked, inspect
Garmin and the receipt before making changes. No automatic deletion or rollback.
Batch publishing is per-event, not all-or-nothing.

This is not a universal exactly-once guarantee: Garmin is an unofficial
integration, unrelated tools can create duplicates, and this lock does not
coordinate separate hosts/databases. A hosted service needs distributed claims.

## Intended Workflow

### Publishing Modes

The `publish` command accepts mutually exclusive mode flags:

- `--dry-run`: validate the plan locally, without Garmin authentication, remote
  calls, or creating the state database. This is also the default.
- `--apply --approve HASH`: publish with the exact reviewed plan hash.
- `--yolo`: publish without requiring hash confirmation. This can create or
  update workouts and schedule them immediately.

All modes retain plan integrity and account validation. YOLO uses the same
durable duplicate protection and reconciliation checks as reviewed publishing;
it does not bypass unresolved prescriptions, cancellations, or conflicts.
Keep using the same private state database across runs. Existing required
`--account-id`, `--session-dir`, and `--state-db` arguments remain unchanged.

### Check Garmin Before Publishing

Using an existing private session and the independently verified numeric profile
ID, run this read-only check (Python 3.12+ with the `garmin` extra):

```bash
uv run --locked --extra garmin workoutbridge garmin-check \
  --session-dir /private/garmin-session \
  --account-id 12345 --date 2027-01-05
```

It verifies account identity, enumerates workouts, and reads the selected day's
calendar. Output includes only the account ID, date, and counts, not workout
titles or personal profile details. Failure returns exit code 2 without exposing
third-party error details. Authentication may refresh the local session.
This does not upload, edit, schedule, delete, or verify watch delivery. It also
does not prove that Garmin will permit a subsequent write. Avoid repeated checks
when Garmin is rate-limiting requests.

1. Read an authorized calendar feed or manually supplied prescription.
2. Preserve the full title, description, date, and source identity.
3. Convert supported wording into a provider-neutral workout draft.
4. Show ambiguities and require athlete review.
5. Publish structured steps and schedule through a Garmin adapter.
6. Record destination IDs so retries and updates do not create duplicates.

Final Surge write-back is a separate future adapter, contingent on verified
access. Reading its calendar feed does not imply permission or ability to edit
its workouts.

## Safety and Privacy

- Do not invent training, recovery, pace targets, or cooldowns.
- Rep completion times are not pace; conversion must use interval distance.
- Preserve timed easy running as running, not stationary rest.
- Never interpret disappearance from a rolling feed as a deletion request.
- Never commit real calendar files, athlete data, feed URLs, or credentials.
- Examples and tests use synthetic prescriptions only.
- No analytics. Parsing, plans, tests, and dry runs never access accounts.
- `garmin-check` contacts Garmin for read-only verification; `publish --apply`
  and `publish --yolo` contact Garmin for explicitly requested publishing.
- `auth garmin` contacts Garmin to authenticate and save a local session only.

See [architecture and roadmap](docs/architecture.md),
[contributing](CONTRIBUTING.md), and [security](SECURITY.md).

## Hosting and Funding

The planned hosted service will have a useful free tier, voluntary donations
and GitHub Sponsors, and optional paid capacity such as more frequent polling.
The code remains MIT-licensed and self-hostable. Prices and limits are not set,
and no hosted service or payment collection is live yet. Sponsorship setup is
pending; no funding link is active.
See the [hosted service model](docs/hosting-model.md).

## License

MIT. See [LICENSE](LICENSE).
