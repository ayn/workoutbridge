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

Pilot intervals, destination limits, manual gifts, and activation-based referral
rewards are specified in the [multi-user guide](multiuser.md). Prices and payment
processing remain undecided; no automatic billing is configured.

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

Hosted paid access uses Stripe Checkout and Billing, not GitHub Sponsors.
Supporter costs USD $3/month or $25/year. New verified accounts get a 30-day
cardless trial; without an explicit subscription they return to Free with no
charge. [Stripe configuration and activation](billing.md) is required before
checkout is available. Payments are disabled by default.

GitHub Sponsors may remain an optional donation channel for people supporting
the open-source/self-hosted project. Sponsorship confers no hosted entitlement,
does not require GitHub account linking, and is not a billing dependency.
Administrator gifts and activated referral rewards remain separate from Stripe
access and survive cancellation of a paid subscription.

## Before Launch

[Klimat](https://klimat.app/) is a useful product reference: automatic training-log
enrichment, a limited free allowance, and a simple annual paid tier (advertised
at $15/year when reviewed on 2026-10-21). This is a positioning reference, not a
Prescribed price commitment; measure our own costs before choosing pricing.

- Measure per-account polling, container runtime, storage, and support costs.
- Validate provider terms and the feasibility of hosted Garmin authentication.
- Configure Stripe, verify checkout/renewals in its test environment, and review
  seller eligibility, payout setup, taxes and customer communications.
- Define fair-use limits, spend caps, billing behavior, and cancellation/export.
- Publish privacy, retention, and service terms.
- Keep self-hosted configuration independent from hosted billing.
