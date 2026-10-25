"""25/10: the HTTP paid route end to end (facilitator faked): result only after settlement, and a signing failure
after settlement still delivers the result."""
import base64
import json
import os
import unittest


class RouteTest(unittest.TestCase):
    def test_paid_route(self):
        os.environ.update({"X402_PAY_TO": "0x" + "a" * 40, "CDP_API_KEY_ID": "k", "CDP_API_KEY_SECRET": "s"})
        import cloud_mcp
        import x402_paywall as xp
        from starlette.testclient import TestClient
        calls = []

        async def fake(cfg, action, version, payload, req, post=None):
            calls.append(action)
            return {"isValid": True, "payer": "0x" + "b" * 40} if action == "verify" else \
                {"success": True, "transaction": "0x" + "c" * 64, "network": "eip155:8453"}
        orig = xp.facilitator
        xp.facilitator = fake
        try:
            c = TestClient(cloud_mcp.app)
            r0 = c.post("/x402/timestamp", json={"sha256": "d" * 64})
            self.assertEqual(r0.status_code, 402)
            acc = json.loads(base64.b64decode(r0.headers["PAYMENT-REQUIRED"]))["accepts"][0]
            pay = base64.b64encode(json.dumps({"x402Version": 2, "accepted": acc, "payload": {"signature": "0x1", "authorization": {}}}).encode()).decode()
            r = c.post("/x402/timestamp", json={"sha256": "d" * 64}, headers={"PAYMENT-SIGNATURE": pay})
            self.assertEqual((r.status_code, calls), (200, ["verify", "settle"]))
            self.assertTrue(r.json()["payment"]["success"])
            key = cloud_mcp.RECEIPT_SIGNING_KEY
            cloud_mcp.RECEIPT_SIGNING_KEY = object()  # signing will fail after settlement
            try:
                r = c.post("/x402/timestamp", json={"sha256": "e" * 64}, headers={"PAYMENT-SIGNATURE": pay})
            finally:
                cloud_mcp.RECEIPT_SIGNING_KEY = key
            self.assertEqual(r.status_code, 200)
            self.assertIn("receipt_note", r.json())
            self.assertEqual(r.json()["sha256"], "e" * 64)
        finally:
            xp.facilitator = orig


if __name__ == "__main__":
    unittest.main()
