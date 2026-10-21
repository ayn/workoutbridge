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

GitHub Sponsors and a donation channel are intended funding options.
Enable public funding links only once the owner's receiving accounts are ready.
Paid hosted access must not depend on a GitHub account or sponsorship. Evaluate
a dedicated hosted checkout (initial shortlist: Polar and Lemon Squeezy, with
Stripe Payment Links as another option). Prefer a merchant-of-record service
when it reduces sales-tax/VAT administration. Verify seller-country eligibility,
payout arrangements, approval requirements and total fees before choosing one.
No billing provider has been selected or activated.

For direct subscriptions, create checkout server-side for the authenticated
Prescribed user, bind the customer to its internal ID, and grant access only
after verified, idempotent webhook processing and authoritative reconciliation.
Never treat a browser checkout-success redirect as proof of payment. Keep paid,
sponsorship, gifted and referral entitlements independent; cancellation should
remove only the relevant entitlement after its effective access period.

Automatic sponsor upgrades are not implemented yet. Until they are, an
administrator can verify sponsorship in GitHub and issue an audited, expiring
Supporter grant. Never grant access based only on a claimed GitHub username,
matching email, screenshot, or return from a checkout URL.

### Planned Sponsor Activation

1. An authenticated Prescribed user links GitHub through an OAuth authorization
   flow. Bind its state to that user and store the verified, stable GitHub user
   ID, not an email match. This links benefits; it does not replace passkey login.
2. Check the linked identity's sponsorship of the configured recipient on the
   server. Map explicitly configured qualifying tiers to Supporter access.
   Check existing sponsorships immediately, including those predating signup.
3. Receive GitHub Sponsors webhooks, verify their HMAC signature before parsing,
   and durably deduplicate deliveries. Verify the recipient and sponsor identity;
   ignore unrelated sponsorships. Reconcile with authoritative API state rather
   than trusting webhook ordering.
4. Reconcile periodically and offer a rate-limited "Check sponsorship" action.
   Failures must be visible and must not immediately revoke existing access.
5. Pending cancellation retains benefits through the paid period. End the
   sponsorship grant only when cancellation takes effect. Gift and referral
   grants remain independent, so ending one source does not erase another.
6. Account and admin views show access source, status, last verification and
   expiry. Record entitlement changes in the audit log without payment details.

Recurring sponsorship eligibility, qualifying tiers, and any fixed-duration
benefit for one-time donations must be published before activation. One-time
donations must not silently grant permanent access. Keep other funding providers
behind the same entitlement boundary rather than special-casing scheduler limits.

GitHub documents [sponsored-account webhooks](https://docs.github.com/en/sponsors/integrating-with-github-sponsors/configuring-webhooks-for-events-in-your-sponsored-account)
and [sponsorship event semantics](https://docs.github.com/en/webhooks/webhook-events-and-payloads#sponsorship).
Production automation also needs GitHub application credentials, a private
webhook secret, least-privilege sponsorship API access, and red/green tests for
identity linking, signatures, retries, duplicate/out-of-order events, tier changes,
cancellation, provider outages, and coexistence with gifts/referrals.

## Before Launch

[Klimat](https://klimat.app/) is a useful product reference: automatic training-log
enrichment, a limited free allowance, and a simple annual paid tier (advertised
at $15/year when reviewed on 2026-10-21). This is a positioning reference, not a
Prescribed price commitment; measure our own costs before choosing pricing.

- Measure per-account polling, container runtime, storage, and support costs.
- Validate provider terms and the feasibility of hosted Garmin authentication.
- Select a payment/donation provider and complete GitHub Sponsors enrollment.
- Define fair-use limits, spend caps, billing behavior, and cancellation/export.
- Publish privacy, retention, and service terms.
- Keep self-hosted configuration independent from hosted billing.
