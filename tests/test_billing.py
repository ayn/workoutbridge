import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from workoutbridge.accounts import Accounts
from workoutbridge.billing import Billing


class BillingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.accounts = Accounts(Path(self.tmp.name), clock=lambda: 1000)
        self.user = self.accounts.create_user("payer@example.invalid")
        self.accounts.verify_email(self.user)
        self.client = MagicMock()
        self.client.v1.customers.create.return_value = {"id": "cus_synthetic"}
        self.client.v1.subscriptions.list.return_value = {"data": [], "has_more": False}
        self.client.v1.checkout.sessions.create.return_value = {
            "id": "cs_synthetic",
            "url": "https://checkout.stripe.com/c/pay/synthetic",
            "expires_at": 2000,
        }
        self.billing = Billing(
            self.accounts,
            self.client,
            price="price_synthetic",
            origin="https://bridge.example",
            webhook_secret="whsec_synthetic",
        )

    def subscription(self, **changes):
        value = {
            "id": "sub_synthetic",
            "customer": "cus_synthetic",
            "status": "active",
            "livemode": False,
            "cancel_at_period_end": False,
            "latest_invoice": {"status": "paid"},
            "items": {
                "data": [{"price": {"id": "price_synthetic"}, "current_period_end": 5000}],
                "has_more": False,
            },
        }
        value.update(changes)
        self.client.v1.subscriptions.list.return_value = {"data": [value], "has_more": False}
        return value

    def test_checkout_is_server_bound_cached_and_does_not_grant_access(self):
        result = self.billing.checkout(self.user)
        self.assertEqual(result, self.billing.checkout(self.user))
        self.client.v1.checkout.sessions.create.assert_called_once()
        params = self.client.v1.checkout.sessions.create.call_args.args[0]
        self.assertEqual(params["customer"], "cus_synthetic")
        self.assertEqual(params["line_items"], [{"price": "price_synthetic", "quantity": 1}])
        self.assertEqual(params["mode"], "subscription")
        self.assertEqual(self.accounts.entitlements(self.user)["plan"], "free")

    def test_displayed_prices_are_validated_against_stripe_before_activation(self):
        self.client.v1.prices.retrieve.return_value = {
            "active": True,
            "livemode": False,
            "currency": "usd",
            "unit_amount": 300,
            "recurring": {"interval": "month", "interval_count": 1},
        }
        self.billing.validate_prices()
        self.client.v1.prices.retrieve.return_value["unit_amount"] = 3000
        with self.assertRaises(ValueError):
            self.billing.validate_prices()

    def test_paid_subscription_grants_supporter_and_cancellation_retains_gifts(self):
        self.billing.checkout(self.user)
        self.subscription(cancel_at_period_end=True)
        self.billing.reconcile(self.user)
        self.assertEqual(self.accounts.entitlements(self.user)["until"], 5000)
        self.accounts.set_admin(self.user, True)
        self.accounts.gift(self.user, self.user, days=1, reason="Independent gift")
        self.subscription(status="canceled")
        self.billing.reconcile(self.user)
        self.assertEqual(self.accounts.entitlements(self.user)["plan"], "supporter")
        self.assertEqual(self.billing.status(self.user)["status"], "canceled")

    def test_unpaid_unknown_prices_and_wrong_mode_never_grant_supporter(self):
        self.billing.checkout(self.user)
        for changes in (
            {"latest_invoice": {"status": "open"}},
            {"livemode": True},
            {"items": {"data": [{"price": {"id": "price_other"}, "current_period_end": 9000}]}},
        ):
            self.subscription(**changes)
            self.billing.reconcile(self.user)
            self.assertEqual(self.accounts.entitlements(self.user)["plan"], "free")

    def test_failed_renewal_retains_only_previously_paid_period(self):
        self.billing.checkout(self.user)
        self.subscription()
        self.billing.reconcile(self.user)
        self.subscription(status="past_due", latest_invoice={"status": "open"})
        self.billing.reconcile(self.user)
        self.assertEqual(self.accounts.entitlements(self.user)["until"], 5000)

    def test_portal_uses_only_callers_customer_and_validates_hosted_url(self):
        self.billing.checkout(self.user)
        self.client.v1.billing_portal.sessions.create.return_value = {
            "url": "https://billing.stripe.com/p/session/synthetic"
        }
        self.assertIn("billing.stripe.com", self.billing.portal(self.user))
        other = self.accounts.create_user("other@example.invalid")
        with self.assertRaises(ValueError):
            self.billing.portal(other)
        self.client.v1.billing_portal.sessions.create.return_value = {"url": "https://evil.example"}
        with self.assertRaises(ValueError):
            self.billing.portal(self.user)

    def test_active_subscription_prevents_duplicate_checkout(self):
        self.billing.checkout(self.user)
        self.subscription()
        with self.assertRaises(ValueError):
            self.billing.checkout(self.user)

    def test_unrecognized_live_subscription_blocks_another_purchase(self):
        self.billing.checkout(self.user)
        self.subscription(
            items={"data": [{"price": {"id": "price_unrecognized"}, "current_period_end": 5000}]}
        )
        with self.assertRaises((ValueError, RuntimeError)):
            self.billing.checkout(self.user)

    def test_change_plan_deep_link_uses_owned_subscription_not_a_second_checkout(self):
        self.billing.checkout(self.user)
        self.subscription()
        self.client.v1.billing_portal.sessions.create.return_value = {
            "url": "https://billing.stripe.com/p/session/synthetic"
        }
        self.billing.portal(self.user, change=True)
        params = self.client.v1.billing_portal.sessions.create.call_args.args[0]
        self.assertEqual(params["customer"], "cus_synthetic")
        self.assertEqual(
            params["flow_data"],
            {
                "type": "subscription_update",
                "subscription_update": {"subscription": "sub_synthetic"},
            },
        )

    def test_portal_configuration_requires_period_end_shorter_interval_and_proration(self):
        config = {
            "active": True,
            "features": {
                "payment_method_update": {"enabled": True},
                "invoice_history": {"enabled": True},
                "subscription_cancel": {"enabled": True, "mode": "at_period_end"},
                "subscription_update": {
                    "enabled": True,
                    "default_allowed_updates": ["price"],
                    "proration_behavior": "always_invoice",
                    "products": [{"product": "prod_synthetic", "prices": ["price_synthetic"]}],
                    "schedule_at_period_end": {"conditions": [{"type": "shortening_interval"}]},
                },
            },
        }
        self.client.v1.billing_portal.configurations.retrieve.return_value = config
        self.billing.validate_portal_configuration("bpc_synthetic")
        config["features"]["subscription_update"]["schedule_at_period_end"]["conditions"] = []
        with self.assertRaises(ValueError):
            self.billing.validate_portal_configuration("bpc_synthetic")

    def test_subscribing_during_cardless_trial_preserves_remaining_trial(self):
        self.accounts.add_credential(self.user, "trial", b"public", 0)
        self.accounts.start_trial(self.user)
        self.billing.checkout(self.user)
        params = self.client.v1.checkout.sessions.create.call_args.args[0]
        self.assertEqual(params["subscription_data"]["trial_end"], 1000 + 30 * 86400)

    def test_checkout_network_failure_reuses_durable_idempotency_key(self):
        self.client.v1.checkout.sessions.create.side_effect = RuntimeError("SECRET")
        with self.assertRaisesRegex(RuntimeError, "Billing temporarily unavailable"):
            self.billing.checkout(self.user)
        first = self.client.v1.checkout.sessions.create.call_args.kwargs
        self.client.v1.checkout.sessions.create.side_effect = None
        self.billing.checkout(self.user)
        self.assertEqual(first, self.client.v1.checkout.sessions.create.call_args.kwargs)

    @staticmethod
    def signed_event(*, event_id="evt_synthetic", timestamp=None, live=False):
        import hashlib
        import hmac
        import time

        event = {
            "id": event_id,
            "type": "customer.subscription.updated",
            "livemode": live,
            "data": {"object": {"customer": "cus_synthetic", "status": "canceled"}},
        }
        payload = json.dumps(event).encode()
        timestamp = timestamp if timestamp is not None else int(time.time())
        signature = hmac.new(
            b"whsec_synthetic", str(timestamp).encode() + b"." + payload, hashlib.sha256
        ).hexdigest()
        header = f"t={timestamp},v1={signature}"
        return payload, header

    def test_webhook_signatures_dedup_and_current_state_not_event_snapshot(self):
        self.billing.checkout(self.user)
        self.subscription()
        payload, header = self.signed_event()
        with self.assertRaises(ValueError):
            self.billing.webhook(payload, "t=1,v1=invalid")
        self.billing.webhook(payload, header)
        self.assertEqual(self.accounts.entitlements(self.user)["plan"], "supporter")
        calls = self.client.v1.subscriptions.list.call_count
        self.billing.webhook(payload, header)
        self.assertEqual(self.client.v1.subscriptions.list.call_count, calls)
        self.client.v1.subscriptions.list.side_effect = RuntimeError("SECRET")
        with self.assertRaisesRegex(RuntimeError, "Billing temporarily unavailable"):
            self.billing.reconcile(self.user)

    def test_tampered_expired_and_wrong_mode_webhooks_never_apply(self):
        self.billing.checkout(self.user)
        payload, signature = self.signed_event()
        for body, header in (
            (payload + b" ", signature),
            self.signed_event(timestamp=1),
            self.signed_event(live=True),
        ):
            with self.subTest(body=body):
                with self.assertRaises(ValueError):
                    self.billing.webhook(body, header)
        with self.accounts.db() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM billing_events").fetchone()[0], 0)
        self.assertEqual(self.accounts.entitlements(self.user)["plan"], "free")

    def test_webhook_provider_failure_is_retriable_without_duplicate_access(self):
        self.billing.checkout(self.user)
        payload, signature = self.signed_event()
        self.client.v1.subscriptions.list.side_effect = RuntimeError("SECRET")
        with self.assertRaises(RuntimeError):
            self.billing.webhook(payload, signature)
        with self.accounts.db() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM billing_events").fetchone()[0], 0)
        self.client.v1.subscriptions.list.side_effect = None
        self.subscription()
        self.billing.webhook(payload, signature)
        self.billing.webhook(payload, signature)
        self.assertEqual(self.accounts.entitlements(self.user)["until"], 5000)

    def test_parallel_and_restarted_checkouts_reuse_one_checkout(self):
        from concurrent.futures import ThreadPoolExecutor

        with ThreadPoolExecutor(max_workers=4) as pool:
            urls = list(pool.map(lambda _: self.billing.checkout(self.user), range(4)))
        self.assertEqual(len(set(urls)), 1)
        restarted = Billing(
            self.accounts,
            self.client,
            price="price_synthetic",
            origin="https://bridge.example",
            webhook_secret="whsec_synthetic",
        )
        self.assertEqual(restarted.checkout(self.user), urls[0])
        self.client.v1.customers.create.assert_called_once()
        self.client.v1.checkout.sessions.create.assert_called_once()

    def test_cancellation_and_expiry_remove_only_paid_access(self):
        self.billing.checkout(self.user)
        self.subscription()
        self.billing.reconcile(self.user)
        self.accounts.clock = lambda: 5001
        self.assertEqual(self.accounts.entitlements(self.user)["plan"], "free")
        self.subscription(status="canceled")
        self.billing.reconcile(self.user)
        self.assertEqual(self.accounts.entitlements(self.user)["plan"], "free")

    def test_multiple_live_subscriptions_require_review_instead_of_another_charge(self):
        self.billing.checkout(self.user)
        sub = self.subscription()
        self.client.v1.subscriptions.list.return_value["data"].append({**sub, "id": "sub_other"})
        with self.assertRaisesRegex(RuntimeError, "review"):
            self.billing.checkout(self.user)
        self.client.v1.checkout.sessions.create.assert_called_once()

    def test_trial_is_not_a_paid_badge_and_unpaid_invoice_does_not_extend_access(self):
        self.billing.checkout(self.user)
        self.subscription(status="trialing", trial_end=4000, latest_invoice={"status": "paid"})
        self.billing.reconcile(self.user)
        self.assertEqual(self.accounts.entitlements(self.user)["badges"], ["trial"])
        self.subscription(status="past_due", latest_invoice={"status": "open"})
        self.billing.reconcile(self.user)
        self.assertEqual(self.accounts.entitlements(self.user)["until"], 4000)


if __name__ == "__main__":
    unittest.main()
