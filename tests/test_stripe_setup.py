import importlib.util
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("stripe_setup", ROOT / "deploy/stripe_setup.py")
setup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(setup)


class FakeStripe:
    def __init__(self):
        self.product = None
        self.prices = {}
        self.writes = []

    def request(self, method, path, fields=None, *, idempotency=None):
        fields = fields or {}
        if method == "GET" and path.startswith("/v1/products/"):
            if self.product is None:
                raise setup.StripeError(404)
            return self.product
        if method == "POST" and path == "/v1/products":
            self.writes.append((path, idempotency))
            self.product = {**fields, "livemode": False, "active": True}
            return self.product
        if method == "GET" and path == "/v1/prices":
            found = self.prices.get(fields["lookup_keys[]"])
            return {"data": [found] if found else [], "has_more": False}
        if method == "POST" and path == "/v1/prices":
            self.writes.append((path, idempotency))
            result = {
                **fields,
                "id": "price_" + fields["lookup_key"],
                "livemode": False,
                "active": True,
                "type": "recurring",
                "billing_scheme": "per_unit",
                "recurring": {"interval": fields["recurring[interval]"], "interval_count": 1},
            }
            self.prices[fields["lookup_key"]] = result
            return result
        raise AssertionError("Unexpected Stripe operation")


class StripeSetupTests(unittest.TestCase):
    def test_creates_one_product_two_exact_prices_and_reuses_on_rerun(self):
        api = FakeStripe()
        result = setup.ensure_catalog(api)
        self.assertEqual(result, setup.ensure_catalog(api))
        self.assertEqual(len(api.writes), 3)
        self.assertTrue(all(key for _, key in api.writes))
        self.assertEqual({p["unit_amount"] for p in api.prices.values()}, {300, 2500})
        self.assertEqual(
            {p["recurring"]["interval"] for p in api.prices.values()}, {"month", "year"}
        )
        self.assertEqual(len({p["product"] for p in api.prices.values()}), 1)

    def test_mismatched_existing_price_fails_without_creating_replacement(self):
        api = FakeStripe()
        setup.ensure_catalog(api)
        next(iter(api.prices.values()))["unit_amount"] = 30000
        before = len(api.writes)
        with self.assertRaises(ValueError):
            setup.ensure_catalog(api)
        self.assertEqual(len(api.writes), before)

    def test_private_test_keys_only_and_no_secret_in_errors(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "key"
            path.write_text("sk_live_SYNTHETIC")
            path.chmod(0o600)
            with self.assertRaises(ValueError) as caught:
                setup.SandboxAPI(path)
            self.assertNotIn("sk_live_SYNTHETIC", str(caught.exception))
            path.write_text("rk_test_SYNTHETIC")
            setup.SandboxAPI(path)
            path.chmod(0o644)
            with self.assertRaises(ValueError):
                setup.SandboxAPI(path)

    def test_live_catalog_response_is_rejected(self):
        api = FakeStripe()
        setup.ensure_catalog(api)
        api.product["livemode"] = True
        with self.assertRaises(ValueError):
            setup.ensure_catalog(api)
