# WorkoutBridge

The private web pilot provides calendar sources, saved Garmin and COROS connections,
web sign-in, structured-workout previews, and manual or opt-in hourly publishing. See the
[private deployment runbook](docs/private-web.md). It is not a public multi-user
service. Scheduled refresh archives feeds; automatic publishing must be enabled
and confirmed separately for each destination account.

Turn plain-text running and coaching prescriptions into reviewable structured
workouts for Garmin Connect and COROS. Designed for training calendars from Final Surge,
Google Calendar, iCloud Calendar, and other iCalendar (ICS) sources.

**Early development, not a hosted service.** The web app is the intended product;
this repository now has its first local backend workflow: ICS file import,
review plans, Garmin payloads, and a persistent opt-in publisher. The full pipeline
is tested with fake Garmin accounts. A limited live test has also verified
uploading, calendar scheduling, and repeat-publish reuse in a dedicated account;
watch delivery has not been verified.
The single-owner web pilot includes hourly feed polling. Final Surge write-back is blocked pending
an officially available API and permission to use it.
Not affiliated with Garmin, Final Surge, Google, Apple, or any coach.

**COROS pilot:** browser OAuth, native running repeats, lap steps, pace targets,
direct calendar creation, verified read-back, and repeat-publish reuse are supported.
See [COROS setup and limitations](docs/coros.md). A synthetic workout was verified
in a dedicated test account; watch delivery has not been verified. Edits, moved
events, and untracked workouts on the same day require manual reconciliation.

## Deployment Options

The web app uses the [versioned `/api/v1` API](docs/web-api.md). Its contract is
provisional during the private pilot and will stabilize at public launch.

- **Self-host today:** follow the [single-owner web deployment runbook](docs/private-web.md)
  for setup, persistent storage, authentication, scheduling, and updates. Keep the
  pilot private; it is not yet a public multi-user service.
- **Hosted service (planned):** a managed option is intended for people who do not
  want to run their own instance. Public availability, service URL, and paid or
  freemium limits are not yet announced. This section will link to the default
  hosted service and its pricing when available.
- **Local CLI:** use the [CLI guide](#cli) without running the web interface.

This public repository contains the single-owner DIY app and CLI. Managed
Prescribed accounts, billing, referrals, administration, and production hosting
are developed separately; they are not required to run this project. Existing
DIY deployments retain the Tailscale sidecar and their own configuration.

## Quick Start

Deploy the single-owner web app with Docker Compose, then connect your calendar
and destination in the browser. No Stripe, transactional email provider, or
hosted-service account is required. Prefer a terminal-only workflow? See [CLI](#cli).

### 1. Prepare Your Server

For the **included custom-domain recipe**, you need Docker Engine with Compose,
a Tailscale account, a private HTTPS hostname, and a Cloudflare-managed DNS zone
for Caddy DNS-01. Cloudflare is not an application requirement: an existing HTTPS
reverse proxy can be used instead with the exact configured Host/Origin preserved.
Tailscale Serve can provide `.ts.net` HTTPS without a custom domain, but a ready-to-use
Serve recipe has not yet been integration-tested here. This Compose deployment
is intended for Linux and should remain accessible only on your LAN/tailnet.

```bash
git clone https://github.com/ayn/workoutbridge.git
cd workoutbridge
umask 077
mkdir -p "$HOME/.config" "$HOME/.local/share/workoutbridge"
chmod 700 "$HOME/.local/share/workoutbridge"
openssl rand -hex 32 > "$HOME/.local/share/workoutbridge/access-password"
chmod 600 "$HOME/.local/share/workoutbridge/access-password"
```

For a **new installation**, put these values in
`$HOME/.config/workoutbridge-deploy.env` and chmod the file to 600. Replace all
placeholders; use an absolute path for the data directory, not a literal `$HOME`.
Never commit this file or your real calendar feed URL.

```dotenv
WORKOUTBRIDGE_PRIVATE_DIR=/absolute/path/outside/checkout/workoutbridge
WORKOUTBRIDGE_DOMAIN=workoutbridge.example.com
WORKOUTBRIDGE_ORIGIN=https://workoutbridge.example.com
CF_API_TOKEN=REPLACE_WITH_ZONE_SCOPED_DNS_TOKEN
```

Set `WORKOUTBRIDGE_PRIVATE_DIR` to the directory created above, containing
`access-password`. See the [deployment runbook](docs/private-web.md) for DNS-token
permissions, persistent state, backups, limits and recovery. **Existing installs:**
keep your original profiles, sessions, password and publishing databases; do not
regenerate credentials or run a second publisher against the same account.

### 2. Start the App and Authorize Tailscale

```bash
docker compose --env-file "$HOME/.config/workoutbridge-deploy.env" up -d --build
docker compose --env-file "$HOME/.config/workoutbridge-deploy.env" exec tailscale \
  tailscale up --accept-dns=false
```

Follow the private authorization link. Point your private DNS hostname to the
sidecar's Tailscale address and open the configured HTTPS origin from a tailnet
device. Do not publish the app through Funnel or port forwarding. Sign in using
the generated `access-password` file from your private data directory.

**Optional: split-horizon DNS with AdGuard Home.** A private DNS rewrite makes
your custom hostname resolve to the sidecar's Tailscale address for your devices,
while Cloudflare's authoritative zone is used for the DNS-01 certificate challenge.
No public application endpoint is required. The example deployment uses the
[AdGuard Home + Unbound + Tailscale stack](https://github.com/ayn/adguard-unbound-tailscale),
but any suitable private DNS resolver works. Configure clients to use that
resolver, make A/AAAA answers consistent with the sidecar addresses you use, and
ensure those clients can reach the sidecar over Tailscale. DNS alone does not
provide network access. Keep your real records, addresses and tokens out of Git.

The included stack uses rootless Docker and `/dev/net/tun`; confirm your server
supports that setup before deploying. First build/certificate issuance and
sidecar authorization can take several minutes. Check status with:

```bash
docker compose --env-file "$HOME/.config/workoutbridge-deploy.env" ps
docker compose --env-file "$HOME/.config/workoutbridge-deploy.env" logs --tail 50 web
```

### 3. Connect and Review in the Browser

1. In **Connections**, connect Garmin (including MFA if requested) or authorize
   COROS. Session data stays in your private mounted storage.
2. In **Sources**, add your authorized Final Surge or Google Calendar feed and
   timezone. The web pilot currently supports those feed hosts; local CLI import
   supports other ICS inputs separately.
3. In **Syncs**, connect that source to the destination profile and refresh the
   preview. Review the original assignment, converted steps and destination.
4. Publish selected workouts manually, or explicitly enable and confirm hourly
   publishing. Enabling it publishes eligible workouts immediately; connecting
   an account alone does not enable writes. Check History for verified results.

Keep the same data directory and publishing receipts across updates. A failed
or uncertain write stops automatic publishing until you reconcile history;
never delete the database to force a retry. See the [full runbook](docs/private-web.md)
for authentication renewal, updates and recovery.

## CLI

The CLI is optional for a self-hosted web deployment. Use it for local imports,
review files, dry runs and terminal-driven publishing without running a web server.

Requires [uv](https://docs.astral.sh/uv/getting-started/installation/), Python
3.12+, and Linux/macOS. Run these commands from the repository checkout.

### 1. Log In to Garmin

```bash
uv sync --locked --extra garmin
umask 077
DATA="$HOME/.local/share/workoutbridge"
mkdir -p "$DATA"
uv run --locked --extra garmin workoutbridge auth garmin \
  --profile personal
```

Enter your email, hidden password, and MFA code if requested. The `personal`
profile saves your verified account ID, private session location, and publishing
database path. Use its name on subsequent commands; no account ID needs copying.
Skip login while the session remains valid. Authentication does not upload workouts.

### 2. Import Your iCal Feed

Replace the fake URL, timezone, and dates below. `--end` is exclusive.
For a Final Surge feed, also add `--calendar-format finalsurge`.

```bash
uv run --locked --extra garmin workoutbridge plan \
  'https://calendar.google.com/calendar/ical/EXAMPLE_NOT_A_REAL_CALENDAR%40group.calendar.google.com/public/basic.ics' \
  --source training-calendar --timezone Asia/Taipei \
  --start 2027-01-01 --end 2027-01-15 --profile personal \
  > "$DATA/review.json"
```

Keep real feed URLs private; command arguments can appear in shell history and
process listings. A local `.ics` path works instead of a URL. Keep the same
`--source` label for future imports of this calendar.

### 3. Review and Publish

Inspect `review.json`, including the original instructions and structured steps.
Unresolved or cancelled events block publishing; select supported runs with
`--uid` or resolve their instructions before continuing.

First validate without contacting Garmin:

```bash
uv run --locked --extra garmin workoutbridge publish "$DATA/review.json" \
  --profile personal --dry-run
```

After reviewing, replace `REVIEW_HASH` with the hash printed by the dry run:

```bash
uv run --locked --extra garmin workoutbridge publish "$DATA/review.json" \
  --profile personal --apply --approve REVIEW_HASH
```

This uploads structured workouts and schedules them on Garmin Connect. For
later syncs, repeat import, review, and publish using the **same profile and state database**;
unchanged events are verified without creating duplicates. This is a manual
sync, not a background schedule.

See [publishing modes](#publishing-modes) for `--yolo`,
[Calendar to Garmin](#calendar-to-garmin) for feed options, and
[Garmin Login](#garmin-login) for session renewal.

### Try the Parser

Parsing alone requires Python 3.11+ and no Garmin login:

```bash
printf '%s\n' 'Warm up until lap; Run 10 min easy; Cool down 5 min' \
  | uv run --locked workoutbridge
```

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

### Calendar to Garmin

Keep input files, review output, sessions, and receipts outside the checkout.
Pass a local ICS file or an authorized HTTPS calendar feed URL directly to `plan`.
Remote reads have a 30-second socket timeout and a 2 MB size limit. Redirects,
non-HTTPS URLs, and URLs with embedded username/password credentials are rejected.
Use the final HTTPS feed URL if your provider redirects.

For example, use a Google Calendar feed directly. This URL is deliberately
fake; replace it with your authorized calendar's iCal URL. Treat real feed URLs
as private and keep them out of Git and shared logs. URL arguments may be visible
in shell history or process listings; use a downloaded local file when that is
unacceptable. WorkoutBridge does not include the input URL in its review plan
or error messages. Keep `--source` a stable non-secret label, never the feed URL.

```bash
umask 077
mkdir -p "$HOME/.local/share/workoutbridge"
uv run --locked --extra garmin workoutbridge plan \
  'https://calendar.google.com/calendar/ical/EXAMPLE_NOT_A_REAL_CALENDAR%40group.calendar.google.com/public/basic.ics' \
  --source training-calendar --timezone Asia/Taipei \
  --start 2027-01-01 --end 2027-02-01 --account-id 12345 \
  > "$HOME/.local/share/workoutbridge/review.json"
```

Local files work with the same command:

```sh
umask 077
workoutbridge plan /private/path/training.ics \
  --source training-calendar --timezone Asia/Taipei \
  --start 2027-01-01 --end 2027-02-01 --account-id 12345 \
  > /private/path/review.json
```

#### Final Surge Calendar Feed

Use your authorized Final Surge calendar subscription URL as the same `plan`
argument. No Final Surge API credentials or login are required for a feed URL
that already grants calendar access:

```bash
uv run --locked --extra garmin workoutbridge plan \
  'https://log.finalsurge.com/delivery/ical/EXAMPLE123456789' \
  --calendar-format finalsurge \
  --source finalsurge-calendar --timezone Asia/Taipei \
  --start 2027-01-01 --end 2027-02-01 --account-id 12345 \
  > /private/path/finalsurge-review.json
```

The URL above uses Final Surge's feed format but has a fake token. Replace it
with your own subscription URL; never put the real URL in a committed file.
Then inspect the review and use the same Garmin `publish`
workflow below. This reads the feed and writes to Garmin only; it does not add
structured steps back to Final Surge or sync through its other destinations.
Feed descriptions can be incomplete and history can roll off: compare the
full coach assignment before publishing, and do not infer missing instructions.
Automatic polling is not implemented yet.

`--calendar-format finalsurge` recognizes `Run:` titles when the description
contains only `Workout: Run` and numeric `Planned: ... mi/km` metadata. It preserves
the original title and description, including planned mileage, in the review
and destination notes. Planned mileage is not substituted for the run distance.
Substantive description text takes precedence; unrecognized instructions remain
unresolved rather than being discarded.

Supported title examples include `Run: 12 miles moderate`,
`Run: 5 miles + 3x200m smooth + 2x100m`, and
`Run: 5 miles + 3x(30s hard; 45s moderate)`.
Repeats become native groups, effort words remain labels, and timed easy/moderate
recovery remains running. A Run-until-Lap transition separates an initial run
from these interval groups. No warm-up, cooldown, or numeric pace is invented.

For repeats with implied but unspecified recovery, the provider-independent policy
defaults to lap-ended rest between reps (not after the last rep), and records
this choice in workout notes. This applies to Google Calendar, Final Surge,
and other ICS sources, in either the title or the substantive description.
For example, `4 x 1' hill hard` becomes four one-minute hard hill reps with
lap-ended recovery between them. Explicit recovery instructions take precedence.
Use `--interval-recovery review` to disable the fallback and require review. Timed
fartlek groups include their prescribed recovery after every repetition.

Unspecified strides such as `4 strides` use four native repeats of Run until
Lap (note: `stride`) followed by recovery until Lap, including recovery after
the final stride. This uses the same `--interval-recovery review` opt-out.
When title and description rep counts differ, the substantive description wins;
the original text remains in the notes. Missing or unsupported instructions
still require review.
Non-running/race titles and unsupported formats require separate review.

Final Surge removes past runs from the feed. A future recurring importer must
fetch at least daily, preserve prescriptions and revisions privately, and never
interpret disappearing events as deletion requests. More frequent polling can
catch same-day assignments. Neither scheduled polling nor a prescription archive
is configured by this command; retain private review files in the meantime.

Replace the example paths, dates, timezone, and profile ID with your own.
`--end` is exclusive; windows are limited to 93 days. Use `--uid` (repeatable)
to select individual events. Unsupported/cancelled events stay visible for review
and block batch publishing. Descriptions take precedence over titles as the
prescription; both are retained, and the review includes original text and steps.

#### Explicit Conversion Preferences

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

#### Garmin Login

The recommended login command saves a named connection:

```bash
uv run --locked --extra garmin workoutbridge auth garmin --profile personal
uv run --locked --extra garmin workoutbridge garmin-check \
  --profile personal --date 2027-01-05
```

Profiles support `auth`, `plan`, `publish`, and `garmin-check`. Choose different
names for different accounts, such as `personal` and `test`. Names may contain
letters, digits, hyphens, and underscores. There is no implicit default profile.
For plan/check/publish, use either `--profile` or the explicit connection flags,
not both. The stored account ID is still checked against the authenticated
account before remote access, and review plans remain account-bound.

By default, profiles live at `~/.config/workoutbridge/profiles/NAME.json`,
sessions under `~/.config/workoutbridge/sessions/`, and publishing databases under
`~/.config/workoutbridge/state/`. Profile directories are mode 0700 and files
0600. They contain destination/account IDs and paths, never passwords or feed URLs.
To choose persistent private storage, set an absolute `WORKOUTBRIDGE_CONFIG_DIR`
before **every** command. In a disposable container, put this directory on a
private persistent volume; never commit it to Git. Changing this location does
not migrate existing profiles or receipts.

To renew, run `auth garmin --profile personal` again. It creates a fresh session,
requires the same account, and preserves the existing publishing database.
Failed authentication or an account mismatch leaves the previous profile intact.
Do not delete the profile or receipts to renew a session.

**Existing explicit-flag users:** those commands remain supported unchanged.
When adopting a profile for an account already used to publish, supply the
existing database during its first login to retain duplicate-protection history:

```bash
uv run --locked --extra garmin workoutbridge auth garmin \
  --profile personal --state-db /private/path/existing-workoutbridge.sqlite
```

This performs fresh authentication; it does not import an existing session.
An optional `--session-dir` selects a new private session location. Subsequent
logins cannot switch an existing profile to a different database.

#### Explicit Paths Without a Profile

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

### CLI Workflow

#### Publishing Modes

The `publish` command accepts mutually exclusive mode flags:

- `--dry-run`: validate the plan locally, without Garmin authentication, remote
  calls, or creating the state database. This is also the default.
- `--apply --approve HASH`: publish with the exact reviewed plan hash.
- `--yolo`: publish without requiring hash confirmation. This can create or
  update workouts and schedule them immediately.

All modes retain plan integrity and account validation. YOLO uses the same
durable duplicate protection and reconciliation checks as reviewed publishing;
it does not bypass unresolved prescriptions, cancellations, or conflicts.
Keep using the same private state database across runs. Use `--profile NAME`
to load connection settings, or supply `--account-id`, `--session-dir`, and
`--state-db` explicitly.

#### Check Garmin Before Publishing

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

Final Surge write-back is blocked pending an official API. As of October 20,
2026, Final Surge support confirmed that athletes/coaches cannot access an open
API yet and that unauthorized access to current APIs is being restricted.
Their tentative availability target is early 2027, subject to announcement,
not a committed integration date. Do not use private endpoints or bypass these
restrictions. Authorized calendar feed import remains a separate read-only path;
it does not grant permission or ability to edit Final Surge workouts.

## Safety and Privacy

- Do not invent training, recovery durations, pace targets, or cooldowns.
  Supported interval shorthand with implied recovery defaults to lap-ended
  recovery, with an explicit require-review opt-out.
- Rep completion times are not pace; conversion must use interval distance.
- Preserve timed easy running as running, not stationary rest.
- Never interpret disappearance from a rolling feed as a deletion request.
- Never commit real calendar files, athlete data, feed URLs, or credentials.
- Examples and tests use synthetic prescriptions only.
- No analytics. Parsing, tests, and publishing dry runs never access accounts.
  Planning from a URL fetches that authorized feed but never contacts Garmin;
  planning from a local file makes no network requests.
- `garmin-check` contacts Garmin for read-only verification; `publish --apply`
  and `publish --yolo` contact Garmin for explicitly requested publishing.
- `auth garmin` contacts Garmin to authenticate and save a local session only.

See [architecture and roadmap](docs/architecture.md),
[contributing](CONTRIBUTING.md), and [security](SECURITY.md).

## Development

For a reproducible developer setup and the test suite, run from the checkout
with Python 3.12+:

```bash
uv sync --locked --extra garmin --extra web
uv run --locked --extra garmin --extra web python -m unittest discover -s tests -v
```

See [contributing](CONTRIBUTING.md) for the required red/green TDD workflow.

## Hosting and Funding

The planned managed service is [Prescribed](https://prescribed.fit). It is
developed separately from this MIT-licensed, single-owner self-hosted project.
The hosted service is not yet publicly available. DIY deployments do not need
billing, email-provider credentials, subscription configuration, or managed
hosting infrastructure. GitHub sponsorship is optional support for the public
project, not a way to buy hosted access.

## Acknowledgments

WorkoutBridge's Garmin integration is built on
[python-garminconnect](https://github.com/cyberjunky/python-garminconnect).
It provides the authentication, session handling, and Garmin Connect API access
we rely on to publish and schedule structured workouts. Thank you to
[cyberjunky](https://github.com/cyberjunky) and the project's contributors for
maintaining this essential library.

WorkoutBridge is an independent project, not affiliated with or endorsed by
Garmin or the python-garminconnect maintainers.

## License

MIT. See [LICENSE](LICENSE).
