# Hosted Service Model

WorkoutBridge's code is MIT-licensed and self-hostable. The planned hosted
service should offer a useful free tier, funded by voluntary donations,
GitHub Sponsors, and optional paid capacity. No billing or donations are
currently configured.

## Web First

The hosted product is a responsive web application, not a hosted CLI.
Its core workflow is connect a feed, review generated steps, then publish.
Design mobile and desktop review together. An installable web experience can
follow; a native iOS companion is a later option for notifications and quick
approvals, not a prerequisite for launch.

Scheduled polling and publishing belong on the backend, independent of whether
the user's browser or future mobile app is open.

## Principles

- Keep core parsing, review, and publishing available in the open-source project.
- Charge for hosted resources and convenience, not correctness or safety.
- Apply the same authentication safeguards, duplicate prevention, privacy,
  and export/deletion controls to every tier.
- Show polling intervals, quotas, last successful sync, and next scheduled check.
- Never silently drop a workout when a quota is reached.
- Do not sell athlete data or use advertising trackers.

## Possible Hosted Limits

Exact numbers and prices are intentionally undecided until costs are measured.

| Capability | Free | Optional paid capacity |
| --- | --- | --- |
| Scheduled feed polling | Less frequent | More frequent within provider limits |
| Connected feeds | Small allowance | Higher allowance |
| Publishing jobs | Useful monthly allowance | Higher allowance |
| Manual refresh | Rate limited | Higher allowance, still rate limited |
| Review, security, export | Included | Same safeguards |

Poll only relevant upcoming dates, cache feeds using HTTP validators where
supported, and avoid logging in to Garmin for unchanged prescriptions.
Paid plans must not bypass upstream rate limits. Back off on failures and
surface reauthentication requirements rather than retrying indefinitely.

## Sponsorship and Donations

GitHub Sponsors and a donation channel are intended funding options.
Enable public funding links only once the owner's receiving accounts are ready.
Sponsorship is voluntary; it does not automatically confer hosted entitlements.
If sponsor benefits are introduced, document their eligibility explicitly.

## Before Launch

- Measure per-account polling, container runtime, storage, and support costs.
- Validate provider terms and the feasibility of hosted Garmin authentication.
- Select a payment/donation provider and complete GitHub Sponsors enrollment.
- Define fair-use limits, spend caps, billing behavior, and cancellation/export.
- Publish privacy, retention, and service terms.
- Keep self-hosted configuration independent from hosted billing.
