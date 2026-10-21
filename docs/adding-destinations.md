# Adding a Destination

Contributions are welcome. Open an issue describing the service, its documented
API/authorization requirements, and supported workout types before starting a
large integration. Do not assume partner access is available or bypass access
controls. Suunto is planned, not implemented.

## Existing Structure

- `calendar.py`, `feed.py`: source events and ICS input, independent of targets.
- `parser.py`: provider-neutral structured prescriptions; retain unresolved text
  for review rather than silently dropping it.
- `garmin.py`, `coros.py`: provider-specific workout payload conversion.
- `publishing.py`, `coros_publishing.py`: durable publication intents, remote
  verification and account-scoped receipts. COROS demonstrates a second target;
  there is no universal plugin registry yet.
- `coros_client.py`, `coros_auth.py`, `auth.py`, `web_auth.py`: authentication,
  token/session handling and provider clients.
- `profiles.py`, `cli.py`, `web.py`, `web/src/App.tsx`: connection validation and
  CLI/web integration. Update their explicit provider choices where necessary.

Keep provider authentication, payload conversion and publication separate from
the parser and source adapters. Introduce a shared abstraction only when it
actually fits multiple providers; do not add target-specific fields to ICS parsing.

## Required Safety Contract

Use the provider's supported authentication flow and least-privilege scopes.
Store sessions outside Git with restrictive permissions; never log passwords,
tokens or private calendar URLs. Verify the destination account identity.

Read `architecture.md` and implement persistent, account-scoped receipt handling
before enabling writes. Stable source/event identity, approval hashes and remote
read-back must prevent duplicate uploads and calendar entries. Ambiguous matches,
missing receipts, moved events, cancellation, and uncertain writes must stop for
review. Do not blindly retry an upload or overwrite unrelated workouts.

Preserve coach instructions, units, native repeats, explicit recoveries and
targets. Unsupported steps or targets require review, not silent approximation.
Apply only documented, athlete-approved conversion policies.

## Tests and Pull Request

Use red/green TDD: add a focused synthetic test, run it and observe the intended
failure, implement the change, then run the full suite. Include:

- Payloads: repeats, lap-button steps, pace ranges, units and unsupported cases.
- Auth: renewal, expiry, wrong account, cancellation and sanitized failures.
- Publishing: first upload, repeated sync, remote verification, changed/moved
  events, overlap, interrupted writes and concurrent attempts.
- CLI/web contracts, dry-run behavior and connection isolation.

Existing `tests/test_publishing.py` and the COROS tests provide fake-provider
examples. Tests must not call real accounts or include personal workouts.
Run `python -m unittest discover -s tests`; for UI changes also run `npm test`
and `npm run build` in `web/`.

Submit a feature-branch PR documenting the observed red/green commands, API
references, supported features and limitations. Any live validation needs explicit
approval and a dedicated test account; distinguish server acceptance from
verified delivery on a watch or bike computer. Update the README destination
table and add a provider setup guide without real credentials or deployment data.
