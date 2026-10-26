"""26/10 (Andrea): signed credit receipts for agents that found real defects. Admin only to emit, public to read,
fingerprint in the receipt log, kept across restarts, never duplicated."""
import hashlib
import unittest

import receipt_log
import receipt_signing

CREDIT = {"credited_to": "skitter", "found_on": "2026-10-25",
          "found": "verify() stayed silent when x402_lint.py was missing.",
          "fixed": "verify() now says the EIP-55 spelling was not checked.",
          "evidence": ["msg_e35538a4-5ee1-4d10-ae44-bad574f1173c"],
          "fix_refs": {"commit": "c5db7ea", "swhid": "swh:1:cnt:b91ca2d24c2de5f812b909c78868f7df95909b8b"}}


class CreditTest(unittest.TestCase):
    def setUp(self):
        import cloud_mcp
        from starlette.testclient import TestClient
        self.m = cloud_mcp
        self.saved = (cloud_mcp.NEO_ADMIN_TOKEN, cloud_mcp.AUTOPILOT_STATE.get("credits"),
                      cloud_mcp.AUTOPILOT_STATE.get("receipt_log"), cloud_mcp._save_local_state, cloud_mcp.RECEIPT_SIGNING_KEY)
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        cloud_mcp.RECEIPT_SIGNING_KEY = Ed25519PrivateKey.generate()  # a throwaway key for the test only
        cloud_mcp.NEO_ADMIN_TOKEN = "t" * 32
        cloud_mcp.AUTOPILOT_STATE["credits"] = []
        cloud_mcp.AUTOPILOT_STATE["receipt_log"] = receipt_log.empty()
        cloud_mcp._save_local_state = lambda *a, **k: None
        self.c = TestClient(cloud_mcp.app)
        self.admin = {"Authorization": "Bearer " + "t" * 32}

    def tearDown(self):
        m = self.m
        (m.NEO_ADMIN_TOKEN, m.AUTOPILOT_STATE["credits"], m.AUTOPILOT_STATE["receipt_log"], m._save_local_state,
         m.RECEIPT_SIGNING_KEY) = self.saved

    def test_admin_only(self):
        self.assertIn(self.c.post("/api/receipts/log/credit", json=CREDIT).status_code, (401, 403))

    def test_emit_sign_log_and_read(self):
        r = self.c.post("/api/receipts/log/credit", json=CREDIT, headers=self.admin)
        self.assertEqual(r.status_code, 200, r.text)
        signed = r.json()["credit"]
        pub = receipt_signing.public_key_info(self.m.RECEIPT_SIGNING_KEY)["public_key_b64"]
        self.assertTrue(receipt_signing.verify_receipt(signed, pub))
        self.assertEqual((signed["type"], signed["credited_to"], signed["receipt"]["tool"]), ("neo-credit", "skitter", "credit"))
        seq = signed["receipt"]["log"]["seq"]
        entry = [e for e in self.m.AUTOPILOT_STATE["receipt_log"]["entries"] if e[0] == seq][0]
        self.assertEqual(entry[2], "note")
        self.assertEqual(entry[3], hashlib.sha256(receipt_signing.canonical_json(signed)).hexdigest())
        self.assertEqual(entry[4], {"type": "credit", "credited_to": "skitter"})
        pub_view = self.c.get("/receipts/credits?agent=skitter").json()
        self.assertEqual(pub_view["count"], 1)
        self.assertEqual(pub_view["credits"][0], signed)
        self.assertEqual(self.c.get("/receipts/credits?agent=someone-else").json()["count"], 0)
        again = self.c.post("/api/receipts/log/credit", json=CREDIT, headers=self.admin).json()
        self.assertTrue(again["duplicate"])
        self.assertEqual(self.m.AUTOPILOT_STATE["receipt_log"]["count"], 1)  # no second entry
        self.assertIn("credits", self.m._state_payload())  # survives restarts via checkpoint

    def test_bad_input_refused(self):
        for bad in ({**CREDIT, "credited_to": "a b"}, {**CREDIT, "evidence": []}, {**CREDIT, "found_on": "25/10"}):
            r = self.c.post("/api/receipts/log/credit", json=bad, headers=self.admin)
            self.assertEqual(r.status_code, 400, bad)
        self.assertEqual(self.m.AUTOPILOT_STATE["receipt_log"]["count"], 0)


if __name__ == "__main__":
    unittest.main()
