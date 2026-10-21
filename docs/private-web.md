# Private web deployment

This is a **single-owner, private pilot**, not a public multi-user service.
The TypeScript UI and Python API use the same parser, Garmin adapter, approval
tokens, and durable publishing receipts as the CLI. COROS is not implemented.
Multiple saved Garmin profiles can be connected to a source through separate
sync rules. Each profile must retain its own original publishing database.

## Access and state

Use rootless Docker Compose. The application publishes only host loopback
`127.0.0.1:1879` for local diagnostics. A dedicated Tailscale sidecar shares
Caddy's network namespace; Caddy terminates HTTPS with Cloudflare DNS-01.
No Caddy ports are published on the host. Do not enable Funnel or public port
forwarding. Point your private DNS hostname to the sidecar's Tailscale IP.
Set `WORKOUTBRIDGE_DOMAIN` to that hostname and `WORKOUTBRIDGE_ORIGIN` to its
exact HTTPS origin. The DNS challenge token needs access to that domain's zone.
On first startup, authorize the new sidecar interactively using
`docker compose --env-file "$HOME/.config/workoutbridge-deploy.env" exec tailscale tailscale up --accept-dns=false`.
Keep the resulting login URL private. The sidecar allows 30 minutes for initial
authorization; the default one-minute boot timeout restarts it and invalidates
pending links. Authentication state persists under
`tailscale/` in the private directory. Do not share another node's state.

Store the following **outside the checkout** in a private directory mounted as
`/data` (owner-only directories, files 0600):

- `access-password`: a randomly generated password of at least 32 characters.
- `config/profiles/`: private CLI connection profiles.
- `config/sessions/`: Garmin sessions; paths in profiles must be container paths.
- `config/state/`: account-scoped publishing receipts.
- `web/web.sqlite`: sources, sync rules, current review plans, publish history.
- `web/archive/`: content-addressed private ICS snapshots.

Put `WORKOUTBRIDGE_PRIVATE_DIR`, `WORKOUTBRIDGE_ORIGIN`,
`WORKOUTBRIDGE_DOMAIN`, and `CF_API_TOKEN` in
`~/.config/workoutbridge-deploy.env`, chmod 600. The app uses an HttpOnly,
SameSite=Strict cookie with a 12-hour session; HTTPS enables Secure cookies.
Sessions expire on container restart. Login attempts are rate-limited. Write
requests require the exact Origin; Host is checked to resist DNS rebinding.
No passwords or private feeds belong in Git, build contexts, or Actions logs.

## Garmin authentication

In Connections, select **Connect Garmin**, enter a profile name, email and
password, then enter the verification code only if Garmin requests it. Use
**Sign in again** on an existing connection to renew it without replacing its
publishing receipts. Creating a connection does not change any sync destination.

Web authentication requires HTTPS and the existing owner session and Origin
checks. Passwords and MFA codes are used in memory, not stored in the database
or logs. Only session tokens and the verified account profile are persisted.
One login can run at a time, with three attempts per 15 minutes and five minutes
to finish. Cancellation/expiry rejects the result and removes the fresh session;
an in-flight provider network request may take longer to return. A restart clears
the pending conversation. The form supports Garmin's email/SMS verification code,
not an OAuth grant or a bypass of Garmin security checks.

CLI authentication remains available in an interactive terminal:

```sh
cd /opt/workoutbridge
docker compose --env-file "$HOME/.config/workoutbridge-deploy.env" run --rm web \
  workoutbridge auth garmin --profile personal
```

Refresh the Connections view afterward. Reauthentication of an existing profile
preserves its publishing database and rejects a different destination account.
When migrating an existing CLI profile, transfer its session **and original
publishing database**, changing only their filesystem paths in the profile.
Use SQLite backup for a consistent snapshot and stop the old publisher first.
Do not run publishers on two hosts with copied databases: locks are host-local.
Do not delete receipts to resolve a duplicate or uncertain outcome.

## Review workflow

1. Sign in with the private instance access password.
2. Add a Final Surge or Google Calendar HTTPS feed under Sources. URLs are
   stored privately and are not returned in state responses. Other feed hosts
   are deliberately unsupported during this pilot; redirects are refused.
3. Connect the source to the desired saved Garmin profile under Syncs.
4. Refresh its preview. Review the next 15 calendar days, source text, steps,
   recovery, notes, and destination account. Unsupported workouts cannot be selected.
   A warm-up-only description beneath an interval/tempo/fartlek title is also
   blocked rather than silently dropping its main set.
5. Select workouts and confirm publication. The backend requires the exact
   current preview, verifies the connected account, and reads back Garmin writes.

Hourly refresh preserves feed snapshots and updates previews. **Automatic
publishing is off by default.** In Syncs, enable Publish hourly and confirm the
specific destination profile/account to opt in. New sync setup offers this
confirmation with a manual-publishing alternative; connecting an account alone
does not enable publishing. Enabling automatic publishing immediately refreshes
and publishes eligible workouts for that sync only, including already imported
workouts, using the existing duplicate-prevention receipts. The confirmation
stays busy until this initial pass finishes. Check History and sync errors for
the outcome; enabling does not guarantee every workout was published. Paused
syncs remain paused. Existing automatic settings are not changed on upgrade.
Each hourly pass uses a fresh
feed and publishes only fully parsed items within the next 15 calendar days;
unresolved and cancelled items stay in review. Existing receipts prevent duplicate
uploads/schedules, and changed prescriptions go through the same update checks as
manual publishing. No deletions are propagated.

Before any automatic write, a durable stop flag is saved. Failed/uncertain writes,
process interruption, or changed account identity stop unattended publishing until
you reconcile History and Garmin and explicitly acknowledge re-enabling it.
Manual publication failures also stop enabled automatic publishing. Expired Garmin
authentication requires sign-in again and an explicit resume; credentials are never
retried automatically. Empty feeds do not contact Garmin. A failed feed fetch
never publishes a stale preview, but is retried on the next hourly poll.

The worker runs every 3600 seconds while the single-worker service is running;
its first check is one hour after startup. Manual Refresh feed only previews,
even for automatic syncs. Pausing a sync stops scheduled refresh and publishing.
Unlinked sources are not polled. Failed refreshes retain the previous
preview and surface an error; previews expire after 24 hours. Refreshing changes
the approval hash, so an old browser view cannot accidentally approve new content.
Final Surge removes past entries; hourly polling reduces but cannot eliminate
loss during outages or entries posted and removed between polls.

On uncertain publication, history reports Review required and keeps receipts.
Do not blindly retry or reset state; use the existing CLI reconciliation guidance.
Manual browser requests may time out during a slow remote operation; a timeout
does not mean nothing was published. Refresh history before any retry.

## Deployment and recovery

Tests run on GitHub-hosted runners for pushes and PRs. `Deploy private instance`
runs only after a successful **push** build on `main` in the same repository,
using the repository-scoped `workoutbridge-deploy` ARM64 runner and the
`private-pi` environment. Restrict that environment to `main`, require approval
for all external contributor workflows, and never approve untrusted code for
the self-hosted runner. These guards are **not a sandbox**: trusted deployment
code can access the runner user's files and rootless Docker engine. A dedicated
isolated runner/host is required before expanding contributor trust.

The workflow serializes deployments, skips superseded revisions, refuses a dirty
checkout, builds the exact tested SHA, and waits for container health. It never
restarts the Docker daemon or unrelated stacks. It does not automatically roll
back a failed deployment: inspect the container and redeploy the previous tested
revision, keeping the same data directory. No production data is uploaded as a
workflow artifact. Images use locked Python/npm dependencies; base image tags
are refreshed on rebuild and are not digest-pinned in this pilot.

```sh
cd /opt/workoutbridge
docker compose --env-file "$HOME/.config/workoutbridge-deploy.env" ps
docker compose --env-file "$HOME/.config/workoutbridge-deploy.env" logs --tail 50 web
```

The container is read-only apart from `/data` and temporary storage, with bounded
logs, 512 MiB memory, one CPU, no extra capabilities, and restart-unless-stopped.
Health checks verify the HTTP endpoint and SQLite, not Garmin session freshness.
Detailed upstream errors and request access logs are suppressed to protect secrets.
The UI shows feed errors, preview timestamps, and publish results. No external
notification or external backup is configured by this deployment.

Back up all of `/data` encrypted, using a stopped container or consistent SQLite
backups, and test restore before relying on it. Archives are intentionally retained
without automatic pruning; monitor disk use. Do not expose archives publicly.

## Local verification

```sh
uv sync --locked --extra garmin --extra web
uv run --locked --extra garmin --extra web python -m unittest discover -s tests
uv run --locked --extra web ruff check workoutbridge tests
uv run --locked --extra web ruff format --check workoutbridge tests
cd web
npm ci
npm test
npm run build
```

Set the three server environment variables plus `WORKOUTBRIDGE_CONFIG_DIR`, then
run `uvicorn workoutbridge.web:application --factory --host 0.0.0.0 --port 8080
--workers 1 --no-access-log` from the repo. Use only synthetic profiles for local
HTTP previews. Production must use HTTPS and exactly one worker because session
state and polling coordination are process-local.

## Before public hosting

Add user identities and ownership checks, encrypted per-user connection secrets,
isolated background jobs, reliable queues, quotas, audit logging, backups,
monitoring, and security review. Keep WordPress and WorkoutBridge separate if
using a shared VPS. Review Garmin access terms and provider capabilities before
offering the service to others. This pilot is not authorization to expose it.
