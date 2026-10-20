# Private web deployment

This is a **single-owner, private pilot**, not a public multi-user service.
The TypeScript UI and Python API use the same parser, Garmin adapter, approval
tokens, and durable publishing receipts as the CLI. COROS is not implemented.
Multiple saved Garmin profiles can be connected to a source through separate
sync rules. Each profile must retain its own original publishing database.

## Access and state

Use rootless Docker Compose. The application publishes only host loopback
`127.0.0.1:1879`. Put Tailscale Serve HTTPS in front of it, using an unused HTTPS
port. Do not enable Funnel, public port forwarding, or a public reverse proxy.
Set `WORKOUTBRIDGE_ORIGIN` to the exact HTTPS origin, including its port.

Store the following **outside the checkout** in a private directory mounted as
`/data` (owner-only directories, files 0600):

- `access-password`: a randomly generated password of at least 32 characters.
- `config/profiles/`: private CLI connection profiles.
- `config/sessions/`: Garmin sessions; paths in profiles must be container paths.
- `config/state/`: account-scoped publishing receipts.
- `web/web.sqlite`: sources, sync rules, current review plans, publish history.
- `web/archive/`: content-addressed private ICS snapshots.

Put `WORKOUTBRIDGE_PRIVATE_DIR` and `WORKOUTBRIDGE_ORIGIN` in
`~/.config/workoutbridge-deploy.env`, chmod 600. The app uses an HttpOnly,
SameSite=Strict cookie with a 12-hour session; HTTPS enables Secure cookies.
Sessions expire on container restart. Login attempts are rate-limited. Write
requests require the exact Origin; Host is checked to resist DNS rebinding.
No passwords or private feeds belong in Git, build contexts, or Actions logs.

## Garmin authentication

Login occurs in an interactive terminal, not a web credential form:

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
5. Select workouts and confirm publication. The backend requires the exact
   current preview, verifies the connected account, and reads back Garmin writes.

Hourly refresh preserves feed snapshots and updates previews. **There is no
automatic publishing.** Pausing a sync stops its scheduled refresh and prevents
publishing. Unlinked sources are not polled. Failed refreshes retain the previous
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
