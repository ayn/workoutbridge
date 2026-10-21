"""Exercise the real Stripe SDK against an in-memory transport, never real payments."""

import json
import tempfile
import unittest
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import stripe

from workoutbridge.accounts import Accounts
from workoutbridge.billing import Billing


class StripeTransport(stripe.HTTPClient):
    name = "synthetic"

    def __init__(self):
        super().__init__()
        self.requests = []

    def request(self, method, url, headers, post_data=None):
        path = urlsplit(url).path
        self.requests.append((method, path, headers, parse_qs(post_data or "")))
        if path == "/v1/customers":
            body = {"object": "customer", "id": "cus_synthetic"}
        elif path == "/v1/subscriptions":
            body = {"object": "list", "data": [], "has_more": False}
        elif path == "/v1/checkout/sessions":
            body = {
                "object": "checkout.session",
                "id": "cs_synthetic",
                "url": "https://checkout.stripe.com/c/pay/synthetic",
                "expires_at": 5000,
            }
        else:
            raise AssertionError("Unexpected Stripe operation")
        return json.dumps(body), 200, {"request-id": "req_synthetic"}


class StripeContractTests(unittest.TestCase):
    def test_sdk_serializes_trial_as_integer_and_binds_price_customer_and_idempotency(self):
        with tempfile.TemporaryDirectory() as folder:
            store = Accounts(Path(folder), clock=lambda: 1000)
            user = store.create_user("synthetic@example.invalid")
            store.verify_email(user)
            store.add_credential(user, "key", b"public", 0)
            store.start_trial(user)
            transport = StripeTransport()
            client = stripe.StripeClient("sk_test_SYNTHETIC", http_client=transport)
            billing = Billing(
                store,
                client,
                price="price_synthetic",
                origin="https://bridge.example",
                webhook_secret="whsec_SYNTHETIC",
            )
            billing.checkout(user)
            method, path, headers, body = transport.requests[-1]
            self.assertEqual((method.lower(), path), ("post", "/v1/checkout/sessions"))
            self.assertEqual(body["subscription_data[trial_end]"], [str(1000 + 30 * 86400)])
            self.assertEqual(body["line_items[0][price]"], ["price_synthetic"])
            self.assertEqual(body["customer"], ["cus_synthetic"])
            self.assertEqual(body["payment_method_types[0]"], ["card"])
            self.assertTrue(
                {k.lower(): v for k, v in headers.items()}["idempotency-key"].startswith(
                    "prescribed-checkout-"
                )
            )
