"""26/10 (Andrea): free signed samples on fixed public inputs, and scope blocks that say what a result did not check."""
import asyncio
import hashlib
import unittest

import receipt_log
import receipt_signing
import x402_services as xs


class ScopeTest(unittest.TestCase):
    def test_scope_on_ok_results(self):
        res = asyncio.run(xs.SERVICES["timestamp"]["run"]({"sha256": "a" * 64}, "t"))
        self.assertEqual(res["scope"], xs.SCOPE["timestamp"])
        res = asyncio.run(xs.SERVICES["injection-scan"]["run"]({"text": "Quarterly update: revenue grew 4%."}, "t"))
        self.assertIn("not_checked", res["scope"])

    def test_no_scope_on_failed_results(self):
        async def fail(b, caller):
            return {"ok": False, "error": "x"}
        self.assertNotIn("scope", asyncio.run(xs._with_scope(fail, {"v": "0.1"})({}, "t")))

    def test_scope_shape(self):
        for name, sc in xs.SCOPE.items():
            self.assertEqual(sc["v"], "0.1", name)
            self.assertTrue(sc["checked"] and sc["not_checked"], name)
            for row in sc["not_checked"]:
                self.assertEqual(set(row), {"what", "why"}, name)

    def test_every_sample_input_is_valid(self):
        for name, svc in xs.SERVICES.items():
            self.assertIsNone(svc["validate"](xs.sample_input(name, "https://neo.example")), name)

    def test_discovery_links(self):
        cat = xs.catalog("https://neo.example")["services"]
        self.assertTrue(all(s["sample"].endswith(f"/x402/{s['name']}/sample") for s in cat))
        paths = xs.openapi("https://neo.example")["paths"]
        self.assertTrue(all(p["post"]["x-sample-url"].endswith(k + "/sample") for k, p in paths.items()))
        self.assertEqual(len(paths), len(xs.SERVICES))  # no extra (unpaid) paths that a catalog could misread


class SampleRouteTest(unittest.TestCase):
    def setUp(self):
        import cloud_mcp
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        from starlette.testclient import TestClient
        self.m = cloud_mcp
        self.saved = (cloud_mcp.RECEIPT_SIGNING_KEY, cloud_mcp.AUTOPILOT_STATE.get("receipt_log"))
        cloud_mcp.RECEIPT_SIGNING_KEY = Ed25519PrivateKey.generate()  # throwaway key for the test only
        cloud_mcp.AUTOPILOT_STATE["receipt_log"] = receipt_log.empty()
        cloud_mcp._X402_SAMPLES.clear()
        self.c = TestClient(cloud_mcp.app)

    def tearDown(self):
        self.m.RECEIPT_SIGNING_KEY, self.m.AUTOPILOT_STATE["receipt_log"] = self.saved
        self.m._X402_SAMPLES.clear()

    def test_offline_samples_are_signed_logged_and_cached(self):
        pub = receipt_signing.public_key_info(self.m.RECEIPT_SIGNING_KEY)["public_key_b64"]
        for name in ("timestamp", "injection-scan", "log-witness", "delivery-receipt-verify"):
            r = self.c.get(f"/x402/{name}/sample")
            self.assertEqual(r.status_code, 200, (name, r.text[:300]))
            d = r.json()
            self.assertTrue(receipt_signing.verify_receipt(d, pub), name)
            self.assertEqual(d["sample"]["service"], name)
            seq = d["receipt"]["log"]["seq"]
            e = [x for x in self.m.AUTOPILOT_STATE["receipt_log"]["entries"] if x[0] == seq][0]
            self.assertEqual((e[2], e[4]), ("note", {"type": "sample", "service": name}))
            self.assertEqual(e[3], hashlib.sha256(receipt_signing.canonical_json(d)).hexdigest())
        self.assertTrue(self.c.get("/x402/delivery-receipt-verify/sample").json()["verdict"]["ok"])
        before = self.m.AUTOPILOT_STATE["receipt_log"]["count"]
        self.assertEqual(self.c.get("/x402/timestamp/sample").json()["signature"], d["signature"] if name == "timestamp" else
                         self.m._X402_SAMPLES["timestamp"]["signature"])
        self.assertEqual(self.m.AUTOPILOT_STATE["receipt_log"]["count"], before)  # cached: no new run, no new entry

    def test_failed_sample_is_not_retried_at_once(self):
        svc = self.m.x402_services.SERVICES["timestamp"]
        orig, calls = svc["run"], []

        async def fail(b, caller, *a, **k):
            calls.append(1)
            return {"ok": False, "error": "x"}
        svc["run"] = fail
        self.m._X402_SAMPLE_FAILED.pop("timestamp", None)
        try:
            self.assertEqual(self.c.get("/x402/timestamp/sample").status_code, 503)
            self.assertEqual(self.c.get("/x402/timestamp/sample").status_code, 503)
        finally:
            svc["run"] = orig
            self.m._X402_SAMPLE_FAILED.pop("timestamp", None)
        self.assertEqual(len(calls), 1)  # the second request did not run anything

    def test_sample_needs_no_payment_and_paid_route_still_asks(self):
        import os
        os.environ.update({"X402_PAY_TO": "0x" + "a" * 40, "CDP_API_KEY_ID": "k", "CDP_API_KEY_SECRET": "s"})
        self.assertEqual(self.c.get("/x402/timestamp/sample").status_code, 200)
        self.assertEqual(self.c.post("/x402/timestamp", json={"sha256": "d" * 64}).status_code, 402)


class SampleCountAndSuggestTest(unittest.TestCase):
    def setUp(self):
        import cloud_mcp
        from starlette.testclient import TestClient
        self.m = cloud_mcp
        self.saved = {k: cloud_mcp.AUTOPILOT_STATE.get(k) for k in ("x402_samples_served", "x402_suggestions", "x402_suggestions_total")}
        self.saved_tok = cloud_mcp.NEO_ADMIN_TOKEN
        for k in self.saved:
            cloud_mcp.AUTOPILOT_STATE.pop(k, None)
        cloud_mcp._SUGGEST_DAY.update(day="", n=0)
        cloud_mcp.NEO_ADMIN_TOKEN = "t" * 32
        self.c = TestClient(cloud_mcp.app)

    def tearDown(self):
        for k, v in self.saved.items():
            self.m.AUTOPILOT_STATE[k] = v
        self.m.NEO_ADMIN_TOKEN = self.saved_tok

    def test_samples_are_counted_in_aggregate(self):
        self.c.get("/x402/timestamp/sample")
        self.c.get("/x402/timestamp/sample")
        self.assertEqual(self.m.AUTOPILOT_STATE["x402_samples_served"]["timestamp"], 2)
        self.assertEqual(self.c.get("/x402").json()["samples_served_since_launch"]["timestamp"], 2)
        self.assertIn("x402_samples_served", self.m._state_payload())

    def test_suggest_is_private_capped_and_deduplicated(self):
        r = self.c.post("/x402/suggest", json={"want": "a check that MCP tool schemas did not change", "from": "agent-x"})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertTrue(self.c.post("/x402/suggest", json={"want": "a check that MCP tool schemas did not change"}).json()["duplicate"])
        self.assertEqual(self.c.post("/x402/suggest", json={"want": "hi"}).status_code, 400)
        self.assertEqual(self.c.get("/x402").json()["suggestions_received"], 1)
        self.assertNotIn("tool schemas", self.c.get("/x402").text)  # the text itself is never public
        self.assertIn(self.c.get("/api/x402/suggestions").status_code, (401, 403))
        rows = self.c.get("/api/x402/suggestions", headers={"Authorization": "Bearer " + "t" * 32}).json()["suggestions"]
        self.assertEqual((rows[0]["from"], rows[0]["injection_level"]), ("agent-x", "none"))
        self.assertIn("x402_suggestions", self.m._state_payload())

    def test_daily_cap(self):
        orig = self.m.SUGGESTIONS_PER_DAY
        self.m.SUGGESTIONS_PER_DAY = 2
        self.m._SUGGEST_DAY.update(day="", n=0)
        try:
            codes = [self.c.post("/x402/suggest", json={"want": f"suggestion number {i} please"}).status_code for i in range(3)]
        finally:
            self.m.SUGGESTIONS_PER_DAY = orig
        self.assertEqual(codes, [200, 200, 429])


if __name__ == "__main__":
    unittest.main()
