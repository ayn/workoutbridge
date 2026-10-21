# Web API

The web client calls the Python server at `/api/v1`. This is the shared API
boundary for the web app and future clients; the CLI still uses Python directly.

## Private-pilot compatibility

**v1 is provisional until public launch.** Routes, request/response fields, and
behavior may change within v1 during the pilot. Deploy the web client and server
together and refresh open browser tabs after upgrades. No external-client
backward-compatibility guarantee is offered yet.

At public launch, document and stabilize the v1 contract. After that, incompatible
changes should use a new major API version, with a documented migration period.
Additive changes that preserve existing behavior can remain in v1.

Legacy unversioned `/api/...` routes and unsupported versions are rejected with
JSON HTTP 404 responses. They are not redirected, especially for publishing
requests. `/health` remains unversioned for infrastructure health checks.

## Current routes

All paths below are relative to `/api/v1`:

| Method | Path | Purpose |
| --- | --- | --- |
| POST | `/login` | Authenticate the instance owner |
| POST | `/logout` | Revoke the current session |
| GET | `/state` | Sources, connections, syncs, previews, and history |
| GET / POST | `/garmin/login` | Read or start a Garmin sign-in job |
| POST | `/garmin/login/mfa` | Submit a requested verification code |
| POST | `/garmin/login/cancel` | Cancel a sign-in job |
| POST | `/sources` | Add a calendar source |
| POST | `/syncs` | Connect a source to a destination profile |
| POST | `/syncs/{key}/preview` | Refresh the feed without publishing |
| POST | `/syncs/{key}/pause` | Pause or resume a sync |
| POST | `/syncs/{key}/automatic` | Confirm automatic publishing; enabling runs immediately |
| POST | `/syncs/{key}/publish` | Publish selected items from the confirmed preview |

The current private pilot uses an HttpOnly owner-session cookie, exact Origin
checks for writes, and Host validation. Versioning does not introduce public
access or mobile authentication. See [private deployment](private-web.md) for
session and security requirements. Provider credentials and publishing logic
remain on the server.

## Integration tests

`tests/test_web.py` sends real HTTP-shaped requests through FastAPI's TestClient,
middleware, routes, and temporary SQLite storage. Calendar network access and
Garmin are replaced with fakes: tests must not publish to real accounts.

Coverage includes version boundaries, authentication and Origin checks, rolling
session persistence/revocation, private sources, preview-to-publish workflows,
account confirmation, duplicate prevention, pauses, and failure stop flags.
Frontend tests verify that the client calls v1 routes. CI runs both suites before
deployment; live smoke checks verify health and authenticated reads only.

```bash
uv run --locked --extra garmin --extra web python -m unittest discover -s tests
npm --prefix web test
```
