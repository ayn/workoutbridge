# DigitalOcean Staging

DigitalOcean is the selected initial host for the future public service. The
current deployment is an empty, private staging instance, not a public service.
The existing private Pi deployment remains the active instance. No profiles,
tokens, feeds, publishing receipts, or scheduled syncs are migrated automatically.

## Isolation

- Dedicated unprivileged `workoutbridge` user, with no sudo access.
- Rootless Docker 29.9.2, installed using Docker's official rootless installer;
  user systemd service with linger enabled. No rootful daemon is required.
- Docker Compose v5.6.1, installed after checking the release SHA256 checksum.
- Container binds only `127.0.0.1:1879`, with no Apache virtual host or public DNS
  route. Existing WordPress, Apache, and MySQL configuration is unchanged.
- One worker; 256 MiB memory, 0.5 CPU, 96 processes, read-only root filesystem,
  32 MiB temporary filesystem, dropped capabilities, and bounded 5 MiB x 3 logs.
- Builds run on GitHub-hosted runners, not the memory-constrained droplet.
  Check host memory before adding traffic or services; resizing needs approval.

The staging origin is `http://localhost:1879`. An administrator can use an SSH
tunnel to that port. Existing safeguards prohibit connecting new provider accounts
over an insecure origin. Do not weaken those checks for staging.

## Files

Root-owned deployment assets:

```text
/opt/workoutbridge-deploy/do_deploy.py
/opt/workoutbridge-deploy/compose.do.yaml
```

Private files owned by the service user:

```text
~/.config/workoutbridge-deploy/deploy.json
~/.config/workoutbridge-deploy/runtime.env
~/.config/workoutbridge-deploy/current.json
~/.config/workoutbridge-deploy/previous.json
~/.local/share/workoutbridge/
```

Directories are mode 700; configuration, password, and receipt files are mode 600.
The data directory is mounted at `/data` and contains the access password and any
future databases or sessions. It must survive container replacement. Back it up
encrypted and separately from images before retaining valuable state; offsite
backup and restore testing are prerequisites for public launch.

## Delivery

`.github/workflows/deploy-do.yml` runs only after successful main-branch Tests
from a push to this repository, and only when `DO_DEPLOY_ENABLED=true`.
GitHub builds an amd64 image, attaches source/revision labels, and publishes it
to GHCR. The existing private Pi runner then deploys the immutable image digest
through the `private-do` GitHub environment. The Pi deployment workflow remains
independent and unchanged.

The runner's mode-600 `~/.config/workoutbridge-do-target.json` contains `host`,
`user`, `key`, and `known_hosts` paths. Its dedicated deployment key stays on the
runner. The target authorized key uses `restrict` and a forced Python deployment
command: no interactive shell, forwarding, or arbitrary remote command. SSH pins
the independently trusted host key. Never commit these host-specific files.

Registry credentials are the job's short-lived package-read token, passed through
encrypted SSH stdin, not arguments or logs. The helper deletes temporary registry
configuration after use. It validates the digest and OCI source/revision labels,
serializes deployments, waits for container health, and records the healthy
revision. Superseded main revisions are skipped before deployment.

## Operations

As the service user, set the rootless daemon socket before using Docker:

```bash
export DOCKER_HOST="unix:///run/user/$(id -u)/docker.sock"
export PATH="$HOME/bin:$PATH"
docker ps
docker stats --no-stream
docker logs --tail 100 workoutbridge-web-1
cat ~/.config/workoutbridge-deploy/current.json
curl --fail http://localhost:1879/health
```

Use `systemctl --user status docker` to inspect the runtime. Administrator access
is separate from the restricted deployment key. Keep logs private and bounded.
Inspect actual container memory/CPU limits after deployment, not just YAML.

Before an update that changes storage, take a consistent backup of private state.
To recover from a failed deployment, inspect container health and the current and
previous receipts. An unsuccessful Compose replacement may leave an unhealthy
new container even though `current.json` still names the last healthy image.
No automatic rollback or database restore occurs. Use the known-good receipt's
`image` as `WORKOUTBRIDGE_IMAGE`, then run the same Compose file and env file with
`up -d --no-build --pull never --wait`. Confirm schema compatibility first; do not
restore old publishing receipts blindly because that could permit duplicates.
The old image must still be cached, or be pulled with temporary registry access.

Changes to the root-owned helper or Compose file require an administrator to
install the reviewed files separately; the restricted deployment key cannot
overwrite its own deployment program. Normal application changes deploy by PR,
green Tests, and merge to main. Never publish a real feed or session for a test.

## Public Launch Gate

Choose the public hostname before registering production passkeys. Add a separate
Apache TLS reverse-proxy virtual host only after public deployment is approved;
retain localhost binding and do not modify the WordPress virtual host. Cloudflare
may proxy the hostname, but origin TLS, trusted proxies, and exact application
origin still need configuration and testing.

Multi-user support is not implemented by this deployment. Before public access:

- Passkey-first accounts and ownership isolation for sources, sessions, receipts,
  previews, background jobs, and destination connections, with integration tests.
- Verified email and a transactional provider, without email magic-link/code login
  as an implicit fallback. Sign in with Apple is deferred.
- A deliberate account recovery policy, secret encryption, rate limits, signup
  abuse controls, session revocation, and secure cookie/proxy configuration.
- Health, failed-job, stale-sync, memory, and disk alerts; encrypted offsite backup
  and a tested restoration procedure. No external test notifications by default.
- Capacity review of the shared droplet and a migration plan that preserves
  publishing receipts and prevents concurrent publishing from Pi and DO.

Do not expose the existing single-owner app publicly as a shortcut to these gates.
