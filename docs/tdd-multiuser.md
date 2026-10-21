# Multi-User Red/Green Record

Focused commands use `uv run --extra web --extra coros python -m unittest
discover -s tests -p TEST_FILE` and frontend `npm test -- --run src/FILE.test.tsx`.
All fixtures are synthetic and email callbacks in tests do not send real messages.

Observed red phases before implementation:

- `test_accounts.py`: missing `workoutbridge.accounts`; then missing DIY-plan,
  repeatable enrollment-read, and explicit session-renewal behavior.
- `test_tenant_profiles.py`: `authenticate_profile` rejected `config_root`.
- `test_hosted.py`: missing hosted module; then absent scheduler state, frequency
  route returning 404 rather than 403, missing grants in the admin response,
  missing admin-view audit, and unsupported configured bootstrap-admin email.
- `test_scheduler.py`: missing scheduler module; later missing `configure`.
- `test_mail.py`: missing mail module.
- `test_vault.py`: missing vault module; `test_web_auth.py` then rejected `vault`.
- `test_deployment.py`: missing multi-user Compose/Apache files; factory accepted
  multi-user mode without a vault key instead of rejecting it.
- `test_do_deploy.py`: local Compose override was ignored (one `-f` instead of two).
- `Hosted.test.tsx`: missing Hosted component, then missing Bootstrap export;
  frequency option was absent before the selector was added.
  Browser verification then found same-tab verification links were ignored;
  a hash-change regression failed before adding the verification-link listener.
- `App.test.tsx`: suggested Garmin email was empty, then focus did not select it.
  The regression checks that edited input is not subsequently auto-selected.

Each focused case was rerun green after its implementation. The full suite also
exposed a scheduler test assuming a particular random user sorted first; it now
checks an actually claimed failed job, since staggering deliberately changes
claim order. Existing single-owner web/auth tests remain part of the full suite.

Release verification includes Python tests, Ruff, frontend tests/build, browser
passkey checks, and live deployment health. Report those results separately;
mocked WebAuthn verification is not a real-device compatibility test.

## Billing and Reward Follow-Up

Observed failures before fixes:

- `test_billing.py`: missing billing module, missing portal plan-change flow and
  configuration validator, missing trial preservation, and unrecognized existing
  subscriptions allowing another checkout.
- `test_billing_contract.py`: the real Stripe SDK encoded a SQLite trial timestamp
  as a decimal (`2593000.0`); integer normalization fixes the wire contract.
- `test_accounts.py`: missing cardless trial, badge classification and referral
  tracker; paid rewards incorrectly reported applied before a Stripe adjustment.
- `test_hosted.py`: registration remained Free and billing injection/routes were
  absent before implementation.
- `Hosted.test.tsx`: absent billing controls, plan-change action, badges, referral
  progress and admin adjustment queue. Same-tab signup also returned to signup
  rather than passkey sign-in after logout.
- `test_deployment.py`: missing optional Stripe secret-file override.

Additional coverage exercises real signature verification, tampering, expired
signatures, environment mismatch, retry after provider failure, replay,
concurrent and restarted checkout, cancellation, expiry, multiple subscriptions,
trial badges and unpaid invoices. These use fakes, never real payment accounts.

**Not yet verified:** Stripe sandbox/test-clock lifecycle, real Apple Pay,
provider-side renewal deferrals for paid referrals, and public production
deployment. Paid referral adjustments are queued and shown as pending, not
silently marked applied. Keep billing disabled until these release gates pass.
