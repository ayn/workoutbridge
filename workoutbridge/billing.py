"""Stripe-hosted subscriptions. Card details never enter the application."""

import os
import threading
from urllib.parse import urlsplit
from uuid import uuid4

import stripe

from .mail import read_private_secret


def billing_factory(origin):
    if os.environ.get("STRIPE_ENABLED") != "true":
        return None
    key = read_private_secret(os.environ["STRIPE_SECRET_KEY_FILE"]).decode().strip()
    secret = read_private_secret(os.environ["STRIPE_WEBHOOK_SECRET_FILE"]).decode().strip()
    live = os.environ.get("STRIPE_LIVE_MODE") == "true"
    if not key.startswith(("sk_live_", "rk_live_") if live else ("sk_test_", "rk_test_")):
        raise ValueError("Stripe key does not match configured mode")
    prices = [os.environ["STRIPE_MONTHLY_PRICE_ID"], os.environ["STRIPE_YEARLY_PRICE_ID"]]
    if not secret.startswith("whsec_") or not all(p.startswith("price_") for p in prices):
        raise ValueError("Invalid Stripe configuration")
    client = stripe.StripeClient(
        key, http_client=stripe.RequestsClient(timeout=15), max_network_retries=1
    )

    def factory(accounts):
        billing = Billing(
            accounts,
            client,
            price=prices[0],
            yearly_price=prices[1],
            origin=origin,
            webhook_secret=secret,
            live=live,
        )
        billing.validate_prices()
        billing.validate_portal_configuration(os.environ["STRIPE_PORTAL_CONFIGURATION_ID"])
        return billing

    return factory


class Billing:
    def __init__(
        self, accounts, client, *, price, origin, webhook_secret, yearly_price=None, live=False
    ):
        self.accounts, self.client = accounts, client
        self.prices = {"monthly": price, **({"yearly": yearly_price} if yearly_price else {})}
        self.origin, self.secret, self.live = origin, webhook_secret, live
        # Single-host deployment: serialize checkouts and reconciliation, never hold SQLite
        # transactions across provider requests. Durable idempotency survives process restarts.
        self.lock = threading.RLock()
        self.portal_configuration = None

    def validate_portal_configuration(self, configuration):
        value = self._call(self.client.v1.billing_portal.configurations.retrieve, configuration)
        features = value.get("features", {})
        update = features.get("subscription_update", {})
        products = update.get("products", [])
        conditions = update.get("schedule_at_period_end", {}).get("conditions", [])
        cancel = features.get("subscription_cancel", {})
        if (
            not value.get("active")
            or not update.get("enabled")
            or set(update.get("default_allowed_updates", [])) != {"price"}
            or update.get("proration_behavior") != "always_invoice"
            or {c.get("type") for c in conditions} != {"shortening_interval"}
            or len(products) != 1
            or set(products[0].get("prices", [])) != set(self.prices.values())
            or not features.get("payment_method_update", {}).get("enabled")
            or not features.get("invoice_history", {}).get("enabled")
            or not cancel.get("enabled")
            or cancel.get("mode") != "at_period_end"
        ):
            raise ValueError("Stripe portal does not match the configured plan-change policy")
        self.portal_configuration = configuration

    def validate_prices(self):
        for plan, price in self.prices.items():
            value = self._call(self.client.v1.prices.retrieve, price)
            recurring = value.get("recurring") or {}
            if (
                not value.get("active")
                or bool(value.get("livemode")) != self.live
                or value.get("currency") != "usd"
                or value.get("unit_amount") != (300 if plan == "monthly" else 2500)
                or recurring.get("interval") != ("month" if plan == "monthly" else "year")
                or recurring.get("interval_count") != 1
            ):
                raise ValueError("Stripe price does not match advertised Supporter plan")

    def _call(self, action, *args, **kwargs):
        try:
            result = action(*args, **kwargs)
            return result.to_dict() if isinstance(result, stripe.StripeObject) else result
        except Exception:  # noqa: BLE001 - provider failures must never expose billing secrets.
            raise RuntimeError("Billing temporarily unavailable") from None

    def status(self, user):
        with self.accounts.db() as db:
            row = db.execute("SELECT * FROM billing WHERE user=?", (user,)).fetchone()
        if row and bool(row["livemode"]) != self.live:
            raise ValueError("Billing environment changed; administrator review required")
        return dict(row) if row else None

    @staticmethod
    def _url(value, host):
        url = value.get("url", "")
        parsed = urlsplit(url)
        if parsed.scheme != "https" or parsed.netloc != host:
            raise ValueError("Invalid billing redirect")
        return url

    def checkout(self, user, plan="monthly"):
        if plan not in self.prices:
            raise ValueError("Unsupported billing plan")
        with self.lock:
            row = self.status(user)
            if not row:
                value = self.accounts.user(user)
                customer = self._call(
                    self.client.v1.customers.create,
                    {"email": value["email"], "metadata": {"prescribed_user": user}},
                    options={"idempotency_key": "prescribed-customer-" + user},
                )
                with self.accounts.db() as db:
                    db.execute(
                        "INSERT INTO billing(user,customer,livemode) VALUES (?,?,?)",
                        (user, customer["id"], self.live),
                    )
            current = self.reconcile(user)
            if current["status"] in {
                "active",
                "trialing",
                "past_due",
                "unpaid",
                "incomplete",
                "paused",
                "review_required",
            }:
                raise ValueError("Manage your existing subscription in billing settings")
            row = self.status(user)
            now = self.accounts.clock()
            if row["checkout_url"] and row["checkout_expires"] > now:
                if row["checkout_plan"] != plan:
                    raise ValueError(
                        "An existing checkout is pending; finish it or wait for expiry"
                    )
                return self._url({"url": row["checkout_url"]}, "checkout.stripe.com")
            if not row["checkout_key"] or row["checkout_expires"] <= now:
                key = uuid4().hex
                # Preserve the request key before making a potentially ambiguous network call.
                with self.accounts.db() as db:
                    trial = db.execute(
                        "SELECT until FROM grants WHERE user=? AND kind='trial' AND revoked=0 AND until>?",
                        (user, now),
                    ).fetchone()
                    trial_end = int(max(trial[0], now + 48 * 3600 + 300)) if trial else None
                    db.execute(
                        "UPDATE billing SET checkout_key=?,checkout_plan=?,checkout_url=NULL,checkout_expires=?,checkout_trial_end=? WHERE user=?",
                        (key, plan, now + 3600, trial_end, user),
                    )
                row = self.status(user)
            if row["checkout_plan"] != plan:
                raise ValueError("A checkout request is pending")
            trial_data = (
                {"subscription_data": {"trial_end": int(row["checkout_trial_end"])}}
                if row["checkout_trial_end"]
                else {}
            )
            result = self._call(
                self.client.v1.checkout.sessions.create,
                {
                    "mode": "subscription",
                    "customer": row["customer"],
                    "line_items": [{"price": self.prices[plan], "quantity": 1}],
                    "client_reference_id": user,
                    "payment_method_types": ["card"],
                    "success_url": self.origin + "/?billing=returned",
                    "cancel_url": self.origin + "/?billing=cancelled",
                    "expires_at": int(row["checkout_expires"]),
                    **trial_data,
                },
                options={"idempotency_key": "prescribed-checkout-" + row["checkout_key"]},
            )
            url = self._url(result, "checkout.stripe.com")
            with self.accounts.db() as db:
                db.execute(
                    "UPDATE billing SET checkout_url=?,checkout_expires=? WHERE user=?",
                    (url, result["expires_at"], user),
                )
            return url

    def portal(self, user, *, change=False):
        row = self.reconcile(user) if change else self.status(user)
        if not row:
            raise ValueError("No billing account")
        params = {"customer": row["customer"], "return_url": self.origin + "/"}
        if self.portal_configuration:
            params["configuration"] = self.portal_configuration
        if change:
            if not row["subscription"] or row["status"] not in {"active", "trialing"}:
                raise ValueError("No changeable subscription; use billing management")
            params["flow_data"] = {
                "type": "subscription_update",
                "subscription_update": {"subscription": row["subscription"]},
            }
        return self._url(
            self._call(
                self.client.v1.billing_portal.sessions.create,
                params,
            ),
            "billing.stripe.com",
        )

    def reconcile(self, user):
        with self.lock:
            row = self.status(user)
            if not row:
                return None
            result = self._call(
                self.client.v1.subscriptions.list,
                {
                    "customer": row["customer"],
                    "status": "all",
                    "limit": 100,
                    "expand": ["data.latest_invoice"],
                },
            )
            if result.get("has_more"):
                raise RuntimeError("Billing requires administrator review")
            matching = []
            for sub in result["data"]:
                items = sub.get("items", {})
                data = items.get("data", [])
                if (
                    bool(sub.get("livemode")) == self.live
                    and sub.get("customer") == row["customer"]
                    and not items.get("has_more")
                    and len(data) == 1
                    and data[0].get("price", {}).get("id") in self.prices.values()
                ):
                    matching.append(sub)
            # More than one live subscription is a billing anomaly, never a reason to charge again.
            live = [s for s in matching if s["status"] not in {"canceled", "incomplete_expired"}]
            if len(live) > 1:
                raise RuntimeError("Billing requires administrator review")
            sub = live[0] if live else (matching[0] if matching else None)
            status = sub["status"] if sub else "none"
            if not sub and any(
                s["status"] not in {"canceled", "incomplete_expired"} for s in result["data"]
            ):
                status = "review_required"
            until = row["paid_until"]
            if (
                sub
                and status == "active"
                and (sub.get("latest_invoice") or {}).get("status") == "paid"
            ):
                until = sub["items"]["data"][0]["current_period_end"]
            elif sub and status == "trialing":
                until = sub.get("trial_end") or 0
            elif status in {
                "canceled",
                "none",
                "incomplete_expired",
                "unpaid",
                "paused",
                "review_required",
            }:
                until = 0
            pending = bool(sub and sub.get("cancel_at_period_end"))
            plan = next(
                (
                    name
                    for name, price in self.prices.items()
                    if sub and sub["items"]["data"][0]["price"]["id"] == price
                ),
                None,
            )
            with self.accounts.db() as db:
                db.execute(
                    "UPDATE billing SET status=?,paid_until=?,cancel_pending=?,checked=?,subscription=?,plan=? WHERE user=?",
                    (
                        status,
                        until,
                        pending,
                        self.accounts.clock(),
                        sub["id"] if sub else None,
                        plan,
                        user,
                    ),
                )
                if status != row["status"] or until != row["paid_until"]:
                    db.execute(
                        "INSERT INTO audit(actor,target,action,reason,at) VALUES (?,?,?,?,?)",
                        ("stripe", user, "billing_update", status, self.accounts.clock()),
                    )
            return self.status(user)

    def reconcile_due(self):
        with self.accounts.db() as db:
            users = [
                r[0]
                for r in db.execute(
                    "SELECT user FROM billing WHERE checked<? ORDER BY checked LIMIT 20",
                    (self.accounts.clock() - 300,),
                )
            ]
        for user in users:
            try:
                self.reconcile(user)
            except (RuntimeError, ValueError):
                # No destructive updates on outages; retain previous expiry and retry next tick.
                continue

    def webhook(self, payload, signature):
        try:
            event = stripe.Webhook.construct_event(payload, signature, self.secret).to_dict()
        except (ValueError, stripe.SignatureVerificationError):
            raise ValueError("Invalid billing webhook") from None
        if bool(event.get("livemode")) != self.live:
            raise ValueError("Wrong billing environment")
        with self.lock:
            with self.accounts.db() as db:
                if db.execute("SELECT 1 FROM billing_events WHERE id=?", (event["id"],)).fetchone():
                    return
                customer = event["data"]["object"].get("customer")
                row = db.execute(
                    "SELECT user FROM billing WHERE customer=?", (customer,)
                ).fetchone()
            if row:
                # Events can arrive out of order; fetch current provider state instead.
                self.reconcile(row[0])
            with self.accounts.db() as db:
                db.execute(
                    "INSERT OR IGNORE INTO billing_events VALUES (?,?)",
                    (event["id"], self.accounts.clock()),
                )
