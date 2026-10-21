# Prescribed Multi-User Pilot

Prescribed is the hosted product at `prescribed.fit`. The open-source repository,
Python package, CLI, and existing private single-owner deployment retain the
WorkoutBridge name for compatibility. Public hosting and DIY deployments share
the same parser and publishing safety checks.

## Accounts

Signup verifies the email address first, then registers a discoverable passkey
with user verification required. Email verification is not an existing-account
login or recovery mechanism. Existing members sign in with a passkey; they can
add a second passkey from Account. Apple/Google SSO is not implemented.

Registration/authentication challenges expire in five minutes and are bound to
the configured HTTPS origin, RP hostname, and ceremony. Session and verification
bearer tokens are hashed in SQLite. Successful authenticated activity renews a
30-day HttpOnly, Secure, SameSite=Strict session. Logout revokes the server-side
session. Email links expire after one hour, are one-use, and carry their token in
a URL fragment rather than the server-visible query string. Verification alone
does not grant access to a workspace.

Passkeys remain tied to the original RP hostname. Changing the domain requires
an account migration plan. There is deliberately no email-only login fallback.
An account with no accessible passkeys requires operator-assisted recovery;
automated recovery is not provided. Encourage an additional passkey before launch.

## Isolation and Credentials

Each user has a separate workspace database, source archive, profile directory,
publishing ledger, operation lock, and Garmin login/MFA conversation. Profile
roots are explicit arguments, not a process-wide environment switch. A provider
account cannot be claimed by two Prescribed users. Manual and scheduled writes
within a workspace use the same lock and durable publishing receipts.

Garmin email/password are used transiently to authenticate, not saved as
connection credentials. Prescribed stores its own registration email, Garmin
account ID, provider session tokens, and the source/workout data needed to sync.
The Garmin email field suggests the Prescribed email but remains editable; only
an untouched suggestion is selected on focus. Password fields start blank and
form credentials are cleared on submission.

In multi-user production mode, provider sessions are encrypted at rest using
Fernet with a separate, mandatory private key file. Decrypted session files live
under `/tmp/prescribed-sessions/USER` inside the container's tmpfs. Completed
authentication and token refreshes are sealed to the persistent volume. Preserve
the key independently of the encrypted archive; losing it requires provider
reauthentication. Source archives, account emails, and workout databases are
private files, not individually encrypted by the session vault. Backups must be
encrypted and access-controlled accordingly.

No calendar feed URL, provider token, password, or workout content appears in the
admin overview. Application/request-body logging is disabled; the Apache example
omits query strings from access logs. Files are private and secrets are mounted
read-only. The application does not use third-party advertising or analytics
trackers. Operator access to the host remains privileged access to user data.

## Scheduling and Plans

The dispatcher wakes every 30 seconds and uses persisted due times, not cron or
one-hour sleeps. It claims at most two athlete jobs, runs them concurrently, and
staggers initial checks. SQLite transactions are short; provider/network work is
outside the central database transaction. A single-host process lock prevents
two dispatchers on the same storage. This is not a multi-host queue.

After an interrupted running job, scheduling stops for review rather than
automatically replaying potentially successful remote writes. History and
provider receipts must be reconciled before resuming scheduling and auto-publish.
Last completion, next due time, counts, and failure status persist across restarts.
Provider failures retain the existing publishing stop latch. Paid access never
bypasses upstream rate limits or duplicate checks.

| Hosted Capability | Free | Supporter |
| --- | --- | --- |
| Default automatic interval | 3 hours | 15 minutes |
| Available intervals | 3, 6, 12, 24 hours | 15/30 minutes, 1/3/6/12/24 hours |
| Destination services | One selected service | Multiple |
| Manual fetch and publish | Included, separate 60-second cooldowns | Same |
| Parsing, review, security | Full functionality | Identical |

Account settings show unavailable faster frequencies as Supporter options. Both
settings and publishing are enforced on the server. On downgrade, retain the
requested interval but clamp the effective interval to the plan minimum. Retain
connections, workouts, and receipts; the user can choose the active Free service.
In-flight provider writes are not forcibly cancelled by a plan change.

No payment processing or automatic sponsor-to-plan mapping is implemented.
Supporter can currently be granted by the administrator. Do not advertise active
checkout or automated billing until it exists. No trial automatically becomes a
paid subscription.

## Gifts and Referrals

An administrator can gift access for 1–3650 days, grant permanent access, or
revoke an individual grant. Temporary grants extend existing temporary access.
Administrator views and grant/revoke operations are audited with actor, target,
reason, and time. Admin privileges are never granted from client request fields.

Invitation acceptance alone earns nothing. Both inviter and invitee receive
30 days after the invitee has verified email, a passkey, a calendar source, a
connected destination, and a server-observed verified workout publication.
The grant is atomic and once per invitee, including concurrent callbacks.
Same-account self-invites are rejected; provider account ownership prevents
reusing the same destination across accounts. The pilot caps rewards at three
activated referrals per inviter. This is basic abuse resistance, not proof that
multiple email/provider accounts belong to different humans. Administrators can
review and revoke grants. Further anti-abuse and configurable caps precede a
larger public referral campaign.

## Administration

Set `WORKOUTBRIDGE_ADMIN_EMAIL` privately to the operator's verified email before
first registration. The matching identity receives admin access only after
verified email and successful passkey registration. An address in a signup body
alone grants nothing. Do not change this setting casually after launch.

Admin shows users, verified status, effective plan, destination count, source/sync
counts, automatic/blocked counts, access grants, and audit history. Counts are
aggregate operational analytics, not workout analysis or content browsing. The
current overview is bounded to 1,000 users/grants and 100 audit entries; audit rows
remain in the database. Paginated administration is needed before exceeding that
pilot size. Disabling users and passkey recovery currently require operator work.

## Container Configuration

Use `deploy/compose.multiuser.yaml` as an override to either the existing DIY
`compose.yaml` (Caddy plus Tailscale sidecar) or `deploy/compose.do.yaml` (rootless
DO service behind Apache). Existing single-owner installs are unchanged unless
the override is explicitly selected. Multi-user data starts under
`/data/multiuser`, separate from the prior `/data/web` and `/data/config`.

Private environment settings:

```text
WORKOUTBRIDGE_ORIGIN=https://your-exact-hostname.example
WORKOUTBRIDGE_HOSTED_PLANS=false
CLOUDFLARE_ACCOUNT_ID=your-account-id
CLOUDFLARE_EMAIL_TOKEN_SOURCE=/private/cloudflare-email-token
WORKOUTBRIDGE_VAULT_KEY_SOURCE=/private/provider-encryption-key
WORKOUTBRIDGE_ADMIN_EMAIL=operator@example.invalid
```

The override enables multi-user mode and mounts the two secrets. Generate the
encryption key using `cryptography.fernet.Fernet.generate_key()` in a private file.
Secret files must be mode 600 inside mode-700 directories, readable by the mapped
container user. Never put them in an image, Git, command-line argument, or log.
Use an Email Sending-only Cloudflare token and IP restrictions where available.
Verify the sending domain and monitor delivery failures; sending has no automatic
retry. The sender is `notifications@` the application origin hostname and replies
go to `support@` that hostname, so onboard the actual sender domain.

DIY multi-user mode sets `WORKOUTBRIDGE_HOSTED_PLANS=false`: no commercial
destination gate, 15-minute default/minimum, all supported frequency choices.
It still enforces tenant isolation and exclusive destination ownership. Keep the
Tailscale sidecar and trusted HTTPS origin; passkeys need that stable hostname.
The initial email adapter uses Cloudflare's REST API; custom deployments can
supply another sender through the `create_hosted_app(send_email=...)` interface.

For hosted DO, set `WORKOUTBRIDGE_HOSTED_PLANS=true`, install the reviewed Apache
vhost only after the origin certificate exists, and use Cloudflare Full (strict).
Keep the container port loopback-only. See [DO staging](digitalocean.md).

## Release and Operations

Before migration, back up the persistent volume and key separately, verify a
restore, and preserve all publishing ledgers. Do not copy active Pi profiles or
enable the same real account on two installations. The first DO deployment uses
empty multi-user state; the Pi continues existing personal syncs until an explicit
cutover. Stop in-flight jobs before planned shutdown. On startup, inspect any
`review_required` schedule and reconcile uncertain publications.

The hosted site is an early pilot, not a general-availability release. Real-device
passkey behavior, provider login, email delivery, restore drills, privacy/retention
and account-deletion procedures, capacity limits, and provider terms still need
operational review before broad promotion. The initial shared droplet has limited
RAM; monitor it rather than promising unlimited capacity or resizing automatically.
