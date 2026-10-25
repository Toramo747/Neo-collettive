import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "tools"))
import delivery_receipt as dr  # noqa: E402


class DeliveryReceiptTest(unittest.TestCase):
    def setUp(self):
        self.r, self.k = dr.example()

    def v(self, r, body=None, hops=None):
        return dr.verify(r, self.k["seller_pub"], self.k["buyer_body_sha256"] if body is None else body,
                         self.k["hop_pubs"] if hops is None else hops)

    def test_example_names_the_hop_that_changed_bytes(self):
        res = self.v(self.r)
        self.assertTrue(res["ok"], res)
        self.assertEqual(res["changed_by"], "example-relay")
        self.assertTrue(any("before the seller saw settlement" in n for n in res["notes"]))

    def test_tampered_seller_field(self):
        r = copy.deepcopy(self.r)
        r["payment"]["amount"] = "1"
        self.assertIn("seller signature does not verify with the published key", self.v(r)["fails"])

    def test_unattributed_change(self):
        res = self.v(self.r, body=dr.sha(b"something else"))
        self.assertTrue(any("unattributed" in f for f in res["fails"]))

    def test_hop_lying_about_what_it_received(self):
        r = copy.deepcopy(self.r)
        r["hops"][0]["received_sha256"] = "0" * 64
        fails = " ".join(self.v(r)["fails"])
        self.assertIn("signature", fails)
        self.assertIn("received bytes that differ", fails)

    def test_refusal_needs_a_code_and_no_tx(self):
        r = copy.deepcopy(self.r)
        r["outcome"], r["refusal_code"], r["charged"] = "refused", "it failed", "no"
        fails = " ".join(dr.verify(r, self.k["seller_pub"])["fails"])
        self.assertIn("refusal needs a code", fails)
        self.assertIn("cannot carry a settlement tx", fails)
        self.assertIn("charged must be true or false", fails)

    def test_settlement_kind_and_internal_cost(self):
        r = copy.deepcopy(self.r)
        r["settlement"] = {"kind": "internal"}
        fails = " ".join(self.v(r)["fails"])
        self.assertIn("name who carried the cost", fails)
        self.assertIn("only allowed with an onchain", fails)

    def test_transfer_log_against_signed_payee(self):
        p = self.r["payment"]
        ok = {"to": p["pay_to_requested"], "from": p["facilitator_wallet"], "amount": p["amount"]}
        self.assertEqual(dr.check_transfer(self.r, ok), [])
        self.assertEqual(len(dr.check_transfer(self.r, dict(ok, to="0x" + "e" * 40, **{"from": "0x" + "f" * 40}))), 2)

    def test_published_vectors(self):
        import json
        V = json.loads((Path(__file__).resolve().parent / "docs" / "spec" / "x402-delivery-receipt-v0.1-vectors.json").read_text())
        for v in V["vectors"]:
            res = dr.verify(v["receipt"], V["test_key_public_b64"], v.get("buyer_body_sha256"), v.get("hop_pubs"))
            self.assertEqual(res["ok"], v["expect"]["ok"], v["name"])
            if "note_contains" in v["expect"]:
                self.assertTrue(any(v["expect"]["note_contains"] in n for n in res["notes"]), v["name"])
            if "changed_by" in v["expect"]:
                self.assertEqual(res["changed_by"], v["expect"]["changed_by"], v["name"])

    def test_missing_lint_is_a_note_not_silence(self):
        # 25/10, skitter: without x402_lint.py beside the file the EIP-55 check must say it did not run
        import json, tempfile
        V = json.loads((Path(__file__).resolve().parent / "docs" / "spec" / "x402-delivery-receipt-v0.1-vectors.json").read_text())
        v = next(x for x in V["vectors"] if x["name"] == "asset-non-checksum-spelling-is-a-note")
        self.assertEqual(v.get("requires"), "x402_lint.py")  # tells a one-file self-check why the expect is unmet
        real = dr.__file__
        with tempfile.TemporaryDirectory() as d:
            dr.__file__ = str(Path(d) / "delivery_receipt.py")
            try:
                res = dr.verify(v["receipt"], V["test_key_public_b64"], v.get("buyer_body_sha256"), v.get("hop_pubs"))
            finally:
                dr.__file__ = real
        self.assertTrue(res["ok"], res)
        self.assertTrue(any("EIP-55 spelling was not checked" in n for n in res["notes"]), res["notes"])

    def test_non_canonical_keeps_the_bytes_for_every_last_char(self):
        # 25/10, skitter: signatures ending in Q, g or w used to fall back to "A" and change real bits
        import base64
        for last in "AQgw":
            sig = "A" * 85 + last
            bad = dr._non_canonical(sig)
            self.assertNotEqual(bad, sig)
            self.assertEqual(base64.urlsafe_b64decode(bad + "=="), base64.urlsafe_b64decode(sig + "=="), last)

    def test_body_header_disagreement_is_noted(self):
        r = copy.deepcopy(self.r)
        r["payment_required"]["header_x402_version"] = 1
        self.assertTrue(any("disagree" in n for n in self.v(r)["notes"]))


if __name__ == "__main__":
    unittest.main()
