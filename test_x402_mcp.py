import asyncio
import os
import unittest
from unittest.mock import patch


class X402McpToolsTest(unittest.TestCase):
    def test_paid_timestamp_over_mcp(self):
        env = {"X402_PAY_TO": "0x77346045c9C30ca2516359812221Ed6afcfc55a7", "CDP_API_KEY_ID": "k",
               "CDP_API_KEY_SECRET": "x" * 10}
        with patch.dict(os.environ, env):
            import cloud_mcp
            import x402_paywall
            from mcp import Client

            calls = []

            async def fake_fac(cfg, action, version, payload, req, post=None):
                calls.append(action)
                return {"isValid": True, "payer": "0xabc"} if action == "verify" else {"success": True, "transaction": "0x" + "1" * 64, "network": "eip155:8453"}

            async def main():
                with patch.object(x402_paywall, "facilitator", fake_fac):
                    async with Client(cloud_mcp.mcp) as c:
                        names = [t.name for t in (await c.list_tools()).tools]
                        self.assertIn("paid_timestamp", names)
                        self.assertIn("verify_quote", names)  # the free tool is still there
                        r1 = await c.call_tool("paid_timestamp", {"sha256": "a" * 64})
                        self.assertTrue(r1.is_error)
                        acc = r1.structured_content["accepts"][0]
                        self.assertEqual((acc["amount"], r1.structured_content["x402Version"]), ("10000", 2))
                        self.assertEqual(calls, [])
                        pay = {"x402Version": 2, "accepted": acc, "payload": {"signature": "0x1", "authorization": {}}}
                        r2 = await c.call_tool("paid_timestamp", {"sha256": "a" * 64}, meta={"x402/payment": pay})
                        self.assertFalse(r2.is_error)
                        self.assertEqual(r2.structured_content["sha256"], "a" * 64)
                        self.assertEqual(r2.meta["x402/payment-response"]["transaction"], "0x" + "1" * 64)
                        self.assertEqual(calls, ["verify", "settle"])
                        bad = await c.call_tool("paid_timestamp", {"sha256": "nope"})  # unpaid: requirements first
                        self.assertTrue(bad.is_error)
                        self.assertIn("accepts", bad.structured_content)
                        bad = await c.call_tool("paid_timestamp", {"sha256": "nope"}, meta={"x402/payment": pay})
                        self.assertTrue(bad.is_error)
                        self.assertFalse(bad.structured_content["charged"])
                        self.assertEqual(calls, ["verify", "settle"])  # bad input with payment: never verified
            asyncio.run(main())


if __name__ == "__main__":
    unittest.main()
