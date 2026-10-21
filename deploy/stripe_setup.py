#!/usr/bin/env python3
"""Provision only the agreed sandbox catalog; never create customers or payments."""

import argparse
import json
import os
import stat
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

PRODUCT = "prod_prescribed_supporter_v1"


class StripeError(RuntimeError):
    def __init__(self, status):
        self.status = status
        super().__init__(f"Stripe sandbox request failed (HTTP {status})")


class SandboxAPI:
    def __init__(self, secret_file):
        fd = os.open(secret_file, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(fd) as handle:
            info = os.fstat(handle.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077:
                raise ValueError("Stripe test key file must be private")
            key = handle.read(4097).strip()
        if len(key) > 4096 or not key.startswith(("sk_test_", "rk_test_")):
            raise ValueError("Refusing non-sandbox Stripe credentials")
        self._key = key

    def request(self, method, path, fields=None, *, idempotency=None):
        if method not in {"GET", "POST"} or not (
            path == "/v1/prices" or path == "/v1/products" or path == "/v1/products/" + PRODUCT
        ):
            raise ValueError("Unsupported sandbox setup operation")
        encoded = urlencode(fields or {}, doseq=True)
        url = "https://api.stripe.com" + path
        data = encoded.encode() if method == "POST" else None
        if method == "GET" and encoded:
            url += "?" + encoded
        headers = {"Authorization": "Bearer " + self._key}
        if idempotency:
            headers["Idempotency-Key"] = idempotency
        try:
            with urlopen(
                Request(url, data=data, headers=headers, method=method), timeout=20
            ) as response:
                return json.load(response)
        except HTTPError as error:
            raise StripeError(error.code) from None
        except (OSError, ValueError):
            raise RuntimeError("Stripe sandbox request could not be completed") from None


def ensure_catalog(api):
    try:
        product = api.request("GET", "/v1/products/" + PRODUCT)
    except StripeError as error:
        if error.status != 404:
            raise
        product = api.request(
            "POST",
            "/v1/products",
            {
                "id": PRODUCT,
                "name": "Prescribed Supporter",
                "description": "More frequent workout syncing and multiple destination services.",
                "metadata[application]": "prescribed",
                "metadata[catalog_version]": "1",
            },
            idempotency="prescribed-sandbox-product-v1",
        )
    if (
        product.get("livemode") is not False
        or not product.get("active")
        or product.get("id") != PRODUCT
        or product.get("name") != "Prescribed Supporter"
    ):
        raise ValueError("Existing Stripe product does not match the sandbox catalog")
    result = {"mode": "sandbox", "product": product["id"]}
    for plan, interval, amount in (("monthly", "month", 300), ("yearly", "year", 2500)):
        lookup = "prescribed_supporter_" + plan + "_v1"
        existing = api.request("GET", "/v1/prices", {"lookup_keys[]": lookup, "limit": 2})
        if existing.get("has_more") or len(existing["data"]) > 1:
            raise ValueError("Ambiguous sandbox price lookup")
        price = (
            existing["data"][0]
            if existing["data"]
            else api.request(
                "POST",
                "/v1/prices",
                {
                    "product": PRODUCT,
                    "currency": "usd",
                    "unit_amount": amount,
                    "recurring[interval]": interval,
                    "recurring[interval_count]": 1,
                    "lookup_key": lookup,
                },
                idempotency="prescribed-sandbox-price-" + lookup,
            )
        )
        recurring = price.get("recurring") or {}
        if (
            price.get("livemode") is not False
            or not price.get("active")
            or price.get("currency") != "usd"
            or price.get("unit_amount") != amount
            or price.get("product") != PRODUCT
            or price.get("type") != "recurring"
            or price.get("billing_scheme") != "per_unit"
            or recurring.get("interval") != interval
            or recurring.get("interval_count") != 1
        ):
            raise ValueError("Existing Stripe price does not match the agreed sandbox plan")
        result[plan + "_price"] = price["id"]
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--secret-file", required=True)
    args = parser.parse_args()
    print(json.dumps(ensure_catalog(SandboxAPI(args.secret_file)), sort_keys=True))


if __name__ == "__main__":
    main()
