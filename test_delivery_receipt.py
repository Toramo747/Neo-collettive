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
        r["outcome"], r["refusal_code"] = "refused", "it failed"
        fails = " ".join(dr.verify(r, self.k["seller_pub"])["fails"])
        self.assertIn("refusal needs a code", fails)
        self.assertIn("cannot carry a settlement tx", fails)

    def test_body_header_disagreement_is_noted(self):
        r = copy.deepcopy(self.r)
        r["payment_required"]["header_x402_version"] = 1
        self.assertTrue(any("disagree" in n for n in self.v(r)["notes"]))


if __name__ == "__main__":
    unittest.main()
