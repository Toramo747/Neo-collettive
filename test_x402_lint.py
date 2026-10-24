import base64
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "tools"))
import x402_lint as x  # noqa: E402

PAYTO = "0x77346045c9C30ca2516359812221Ed6afcfc55a7"
ACC = {"scheme": "exact", "network": "eip155:8453", "amount": "10000", "asset": x.USDC["eip155:8453"], "payTo": PAYTO,
       "maxTimeoutSeconds": 60}


def hdr(d):
    return {"PAYMENT-REQUIRED": base64.b64encode(json.dumps(d).encode()).decode()}


class X402LintTest(unittest.TestCase):
    def codes(self, *a, **k):
        return {f["code"] for f in x.lint(*a, **k)}

    def test_keccak_known_vector(self):
        self.assertEqual(x.keccak256(b"").hex(), "c5d2460186f7233c927e7db2dcc703c0e500b653ca82273b7bfad8045d85a470")

    def test_clean_v2(self):
        doc = {"x402Version": 2, "accepts": [ACC]}
        self.assertEqual(x.lint(402, json.dumps(doc), hdr(doc), "https://s.example/a"), [])

    def test_version_and_field_mismatch(self):
        body = {"x402Version": 1, "accepts": [dict(ACC, network="base", maxAmountRequired="10000", amount=None)]}
        head = {"x402Version": 2, "accepts": [dict(ACC, amount="20000")]}
        c = self.codes(402, json.dumps(body), hdr(head), "https://s.example/a")
        self.assertIn("version_mismatch", c)
        self.assertIn("amount_mismatch", c)
        self.assertNotIn("network_mismatch", c)  # v1 "base" == eip155:8453

    def test_relic_forge_checksum(self):
        doc = {"x402Version": 2, "accepts": [dict(ACC, asset="0x833589fCD6eDb6E08f4c7C32D4F71b54bdA02913")]}
        self.assertIn("asset_bad_checksum", self.codes(402, json.dumps(doc), {}, "https://s.example/a"))

    def test_post_in_words_get_in_schema(self):
        doc = {"x402Version": 2, "accepts": [ACC], "description": "Paid POST: up to 25 matches",
               "extensions": {"bazaar": {"info": {"input": {"method": "GET"}}}}}
        self.assertIn("description_method_conflict", self.codes(402, json.dumps(doc), {}, "https://s.example/a"))

    def test_not_402_and_empty(self):
        self.assertEqual(self.codes(200, "{}", {}, "https://s.example/a"), {"not_402"})
        self.assertIn("no_requirements", self.codes(402, "", {}, "https://s.example/a"))


if __name__ == "__main__":
    unittest.main()
