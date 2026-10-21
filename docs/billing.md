# Hosted Billing

Prescribed uses Stripe-hosted Checkout, Billing and the customer portal. The app
does not collect card numbers. GitHub Sponsors is optional project support and
does not activate hosted benefits. DIY deployments do not need Stripe.

## Plans and Trial

- USD $3/month or $25/year, renewing until cancelled.
- New verified hosted identities get 30 days of Supporter after passkey setup.
  No payment details, Stripe customer, or checkout is needed to start the trial.
- Without explicitly subscribing, trial expiry returns the user to Free. Keep
  workouts, provider connections and receipts; clamp the schedule, not the data.
- Subscribing during the trial preserves its remaining time. Stripe requires a
  future trial end; checkout started in the last two days receives at least two
  days plus five minutes before billing. Stripe displays the exact first charge.
- A failed renewal does not create a fresh paid period. Previously granted
  access remains until its recorded expiry; the portal allows payment updates.
- Ending paid access never revokes independent gifts or referral rewards.

## Activation

Billing is off by default. First finish Stripe seller/payout onboarding, review
tax obligations and service terms, and test in a Stripe sandbox. Ordinary Stripe
Checkout/Billing is not automatically a merchant-of-record arrangement.

Create two active recurring USD prices: 300 cents every month and 2500 cents
every year, each with interval count one. The application validates these
against Stripe at startup and refuses mismatched amount/currency/mode/interval.
The UI never supplies an arbitrary price, customer, user ID or return URL.

Store API and webhook signing secrets in private mode-600 files, not Git or
environment values. Use the optional `deploy/compose.stripe.yaml` override after
the multi-user override. Add private environment configuration:

```text
STRIPE_ENABLED=true
STRIPE_LIVE_MODE=false
STRIPE_SECRET_KEY_SOURCE=/private/stripe-secret-key
STRIPE_WEBHOOK_SECRET_SOURCE=/private/stripe-webhook-secret
STRIPE_MONTHLY_PRICE_ID=price_SYNTHETIC_MONTHLY
STRIPE_YEARLY_PRICE_ID=price_SYNTHETIC_YEARLY
STRIPE_PORTAL_CONFIGURATION_ID=bpc_SYNTHETIC
```

Direct process deployments use `STRIPE_SECRET_KEY_FILE` and
`STRIPE_WEBHOOK_SECRET_FILE` instead of the Compose source paths. Production keys
and prices must be from the same Stripe account and environment. Do not reuse
test customer data in live mode: the app rejects stored mode mismatches. Use a
separate data volume for sandbox testing, not a live database reset.

Configure a **snapshot** webhook destination at
`https://YOUR_HOSTNAME/api/v1/billing/webhook` for:

- `checkout.session.completed` and `checkout.session.async_payment_succeeded`
- `customer.subscription.created`, `.updated`, and `.deleted`
- `invoice.paid` and `invoice.payment_failed`

Use the API version pinned by the installed Stripe SDK (16.0.0 currently) when
configuring snapshot payloads; the adapter reads current subscription items and
their period ends. Raw bytes and the Stripe signature are verified, including
timestamp tolerance. Successful deliveries are durably deduplicated. Failed
provider reconciliation returns 503 so Stripe can retry. Out-of-order events
trigger a fresh provider lookup, not replay of an old entitlement snapshot.

Checkout requests use durable idempotency keys and reuse open checkout URLs.
Existing active, trialing, or delinquent subscriptions route to management, not
a second purchase. Billing reconciliation runs independently every five minutes
for up to 20 due customers per dispatcher tick; Account also offers a rate-limited
status check. Network failures do not overwrite prior access. Inspect the last
checked time for prolonged outages; the original expiry is not extended forever.

## Stripe Dashboard Settings

### Referral Release Gate

The agreed reward is one free calendar month: skip a monthly renewal or delay
annual renewal by a month, stacking up to three qualifying referrals. A user
who paid for one month and earned two months must retain Supporter until the
end of the third month even after cancelling; cancellation stops future charges,
not earned access. Show cancellation and the access-through date together.

**The Stripe-side adjustment is not implemented/verified yet.** Current code
preserves 30-day access grants, queues subscription adjustments durably, and
shows them pending in Account/admin tracking. It must not be advertised as a
completed billing reward or enabled for live subscriptions. Implement and test
calendar-month arithmetic, durable provider idempotency, cancellation after
stacked rewards, and pending annual/monthly plan-change interactions before
activation. Do not substitute a cash credit or refund for this policy.

### Required Settings

- Enable cards and Apple Pay for eligible customers. Stripe-hosted Checkout
  controls wallet eligibility; not every browser/device/region displays it.
- Activate the customer portal: payment-method updates, invoices, cancellation
  at period end, and switching only between the two approved prices on the same
  Supporter product. Set price-only updates, `proration_behavior=always_invoice`,
  and `schedule_at_period_end.conditions=[{type: shortening_interval}]`.
  Monthly to yearly switches immediately and credits unused monthly time.
  Yearly to monthly is scheduled for the end of the paid year. The dedicated
  configuration is validated at startup and attached to each portal session.
  Account's Change plan opens an owned-subscription update flow, not checkout.
- Configure receipts, upcoming renewal/trial-ending reminders, expiring-card and
  failed-payment emails, Smart Retries and the final failed-payment action.
  These are Dashboard settings, **not configured automatically by this code**.
- Review tax registration/calculation and any Stripe Tax setup separately.
- Do not enable live mode until sandbox checkout, renewal, failed renewal,
  cancellation, portal updates and webhook retries have been exercised. Unit
  fakes do not verify live Apple Pay or real payment recovery.

References: [hosted subscriptions](https://docs.stripe.com/billing/subscriptions/build-subscriptions),
[customer portal](https://docs.stripe.com/customer-management),
[webhook delivery](https://docs.stripe.com/webhooks),
[Smart Retries](https://docs.stripe.com/billing/revenue-recovery/smart-retries).
