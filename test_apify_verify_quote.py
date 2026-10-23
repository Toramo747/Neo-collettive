import base64
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "apify" / "verify-quote"))
from src.main import check_items, mcp_result  # noqa: E402
from receipt_signing import sign_receipt  # noqa: E402
from cryptography.hazmat.primitives import serialization  # noqa: E402
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey  # noqa: E402

KEY = Ed25519PrivateKey.generate()
PUB = base64.b64encode(KEY.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)).decode()


class ApifyActorTest(unittest.TestCase):
    def test_signed_outcome_is_charged(self):
        call = lambda u, q: sign_receipt({"ok": True, "outcome": "verbatim", "url": u}, KEY, log={"seq": 4, "prev": "0" * 64})
        r = check_items([{"url": "https://a.org", "quote": "one two three"}], call, PUB)[0]
        self.assertTrue(r["signature_verified"] and r["charge"])
        self.assertEqual(r["log_seq"], 4)

    def test_unsigned_or_tampered_is_not_charged(self):
        def call(u, q):
            d = sign_receipt({"ok": True, "outcome": "verbatim", "url": u}, KEY)
            d["outcome"] = "not_found"
            return d
        r = check_items([{"url": "https://a.org", "quote": "one two three"}], call, PUB)[0]
        self.assertFalse(r["signature_verified"] or r["charge"])

    def test_bad_input_and_errors_are_not_charged(self):
        def boom(u, q):
            raise TimeoutError()
        rows = check_items([{"url": "http://a.org", "quote": "one two three"}, {"url": "https://a.org", "quote": "x"},
                            {"url": "https://a.org", "quote": "one two three"}], boom, PUB)
        self.assertEqual([r["charge"] for r in rows], [False, False, False])

    def test_cap_and_sse_parse(self):
        call = lambda u, q: {"ok": False, "error": "rate_limited"}
        self.assertEqual(len(check_items([{"url": "https://a.org", "quote": "a b c"}] * 80, call, PUB)), 50)
        self.assertEqual(mcp_result('event: message\ndata: {"result":{"structuredContent":{"outcome":"verbatim"}}}\n')["outcome"], "verbatim")


if __name__ == "__main__":
    unittest.main()
