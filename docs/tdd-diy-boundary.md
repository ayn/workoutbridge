# DIY Boundary Red/Green Record

The public distribution is a single-owner DIY application and CLI. Managed
accounts, billing, referrals, administration and production deployment belong
to a separate privately maintained service. No license history is rewritten.

Observed failures before changes:

- `uv run --extra web python -m unittest discover -s tests -p test_diy_boundary.py`
  failed because the managed deployment folder, workflow and runbook existed.
- `uv run --extra web python -m unittest discover -s tests -p test_web_extensions.py`
  failed because explicit profile roots and embedding authentication callbacks
  were not supported.
- The suggested-email frontend regression failed because the supplied address
  was not populated. Generic embedding props preserve the DIY default UI.
- The isolated startup regression failed because its smoke script did not exist;
  the separate minimal CI job assertion also failed before that job was added.

Both focused suites pass after implementation. The public core has generic
opt-in hooks for an embedding application and explicit profile roots, not a
hosted account database or billing implementation. Owner/password authentication
remains the default. Provider checks and duplicate prevention are shared.

The existing DIY Tailscale/Caddy deployment is retained. Managed deployment
tooling and its tests were moved out, not replaced with private host details.
The deployment workflow itself is not exercised by unit tests; no live
deployment was performed as part of this boundary change.

The isolated smoke exercises the real ASGI application lifecycle, owner login,
authenticated state, logout and shutdown with synthetic local storage. Its
process clears configuration and blocks hosted-only imports even when installed.
It makes no provider requests. This is not a Docker or real-device test.
