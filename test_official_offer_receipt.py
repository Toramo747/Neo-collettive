"""27/10: neo emits official x402 Offer and Receipt artifacts (JWS EdDSA, did:web key) and they verify with the
independent verifier in tools/x402_offer_receipt.py, using only the public did.json."""
import base64
import json
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "tools"))
import x402_offer_receipt as orr  # noqa: E402
import receipt_signing  # noqa: E402
import x402_paywall as xp  # noqa: E402

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey  # noqa: E402

HOST = "neo-collettive.onrender.com"


class UnitTest(unittest.TestCase):
    def setUp(self):
        self.key = Ed25519PrivateKey.generate()

    def test_offer_and_receipt_verify_against_did_document(self):
        doc = receipt_signing.did_document(self.key, HOST)
        self.assertEqual(doc["id"], "did:web:" + HOST)
        req = xp.requirements(0.01, "0x" + "a" * 40)
        offer = receipt_signing.official_offer(self.key, HOST, f"https://{HOST}/x402/timestamp", req)
        self.assertEqual(offer["format"], "jws")
        self.assertNotIn("payload", offer)  # spec 3.1.1
        v = orr.verify(offer, "offer", did_document=doc, accepts=req)
        self.assertTrue(v["ok"], v)
        self.assertEqual(v["authorization"]["status"], "established")
        self.assertEqual(orr.did_web_url(json.loads(orr._b64u(offer["signature"].split(".")[0]))["kid"]),
                         f"https://{HOST}/.well-known/did.json")
        rec = receipt_signing.official_receipt(self.key, HOST, f"https://{HOST}/x402/timestamp", "eip155:8453",
                                               "0x" + "b" * 40, "0x" + "c" * 64, issued_at=1700000000)
        v = orr.verify(rec, "receipt", did_document=doc, transaction="0x" + "c" * 64)
        self.assertTrue(v["ok"], v)
        self.assertEqual(v["authorization"]["status"], "established")
        other = receipt_signing.did_document(Ed25519PrivateKey.generate(), HOST)
        self.assertFalse(orr.verify(rec, "receipt", did_document=other)["ok"])

    def test_422_body_mismatch_is_detected(self):
        req = xp.requirements(0.01, "0x" + "a" * 40)
        offer = receipt_signing.official_offer(self.key, HOST, f"https://{HOST}/x402/timestamp", req)
        v = orr.verify(offer, "offer", did_document=receipt_signing.did_document(self.key, HOST), accepts={**req, "amount": "20000"})
        self.assertFalse(v["ok"])


class RouteTest(unittest.TestCase):
    def test_402_carries_offer_and_paid_response_carries_receipt(self):
        os.environ.update({"X402_PAY_TO": "0x" + "a" * 40, "CDP_API_KEY_ID": "k", "CDP_API_KEY_SECRET": "s"})
        import cloud_mcp
        from starlette.testclient import TestClient
        key = Ed25519PrivateKey.generate()
        saved = (cloud_mcp.RECEIPT_SIGNING_KEY, dict(xp.OFFER_SIGNER))
        cloud_mcp.RECEIPT_SIGNING_KEY = key
        xp.OFFER_SIGNER.update(key=key, host=HOST)
        calls = []

        async def fake(cfg, action, version, payload, req, post=None):
            calls.append(action)
            return {"isValid": True, "payer": "0x" + "b" * 40} if action == "verify" else \
                {"success": True, "transaction": "0x" + "c" * 64, "network": "eip155:8453", "payer": "0x" + "b" * 40}
        orig = xp.facilitator
        xp.facilitator = fake
        try:
            c = TestClient(cloud_mcp.app, base_url=f"https://{HOST}")
            doc = c.get("/.well-known/did.json").json()
            self.assertEqual(doc["id"], "did:web:" + HOST)
            r0 = c.post("/x402/timestamp", json={"sha256": "d" * 64})
            self.assertEqual(r0.status_code, 402)
            pr = json.loads(base64.b64decode(r0.headers["PAYMENT-REQUIRED"]))
            offer = pr["extensions"]["offer-receipt"]["info"]["offers"][0]
            v = orr.verify(offer, "offer", did_document=doc, accepts=pr["accepts"][0])
            self.assertTrue(v["ok"] and v["authorization"]["status"] == "established", v)
            self.assertEqual(v["payload"]["resourceUrl"], f"https://{HOST}/x402/timestamp")
            self.assertIn("bazaar", pr["extensions"])  # the Bazaar block is untouched
            pay = base64.b64encode(json.dumps({"x402Version": 2, "accepted": pr["accepts"][0],
                                               "payload": {"signature": "0x1", "authorization": {}}}).encode()).decode()
            r = c.post("/x402/timestamp", json={"sha256": "d" * 64}, headers={"PAYMENT-SIGNATURE": pay})
            self.assertEqual(r.status_code, 200, r.text)
            settle = json.loads(base64.b64decode(r.headers["PAYMENT-RESPONSE"]))
            rec = settle["extensions"]["offer-receipt"]["info"]["receipt"]
            v = orr.verify(rec, "receipt", did_document=doc, transaction="0x" + "c" * 64)
            self.assertTrue(v["ok"] and v["authorization"]["status"] == "established", v)
            self.assertEqual(v["payload"]["payer"], "0x" + "b" * 40)
            self.assertEqual(r.json()["payment"]["extensions"]["offer-receipt"]["info"]["receipt"], rec)
            self.assertTrue(receipt_signing.verify_receipt(r.json(), receipt_signing.public_key_info(key)["public_key_b64"]))
        finally:
            xp.facilitator = orig
            cloud_mcp.RECEIPT_SIGNING_KEY = saved[0]
            xp.OFFER_SIGNER.update(saved[1])


if __name__ == "__main__":
    unittest.main()
