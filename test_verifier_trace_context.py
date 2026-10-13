import asyncio
import json
import unittest
from unittest import mock

import mcp_endpoint_verifier as v


def run(strict=False, echo=False):
    sent = []

    async def fake_validate(url):
        return {"host": "example.org", "resolved_ips": ["93.184.216.34"]}

    async def fake_request(client, method, url, json_body=None, headers=None, **kw):
        sent.append(json_body)
        m = (json_body or {}).get("method")
        if m == "initialize":
            return {"status": 200, "headers": {}, "url": url, "latency_ms": 5,
                    "body": json.dumps({"result": {"protocolVersion": "2025-11-25", "serverInfo": {"name": "x"}}})}
        if m == "tools/list":
            meta = ((json_body.get("params") or {}).get("_meta") or {})
            if strict and meta:
                return {"status": 400, "headers": {}, "url": url, "latency_ms": 5, "body": "{\"error\":{}}"}
            hdrs = {"traceresponse": meta.get("traceparent", "")} if echo and meta else {}
            return {"status": 200, "headers": hdrs, "url": url, "latency_ms": 5,
                    "body": json.dumps({"result": {"tools": [{"name": "t", "inputSchema": {"type": "object"}}]}})}
        if method == "GET":
            return {"status": 404, "headers": {}, "body": ""}
        return {"status": 202, "headers": {}, "body": ""}

    v.reset_runtime_state_for_tests()
    with mock.patch.object(v, "validate_public_https", fake_validate), mock.patch.object(v, "_bounded_request", fake_request):
        out = asyncio.run(v.verify_endpoint(url="https://example.org/mcp", caller="t", enforce_rate_limit=False))
    return out, sent


class TraceContextTests(unittest.TestCase):
    def test_traceparent_is_w3c_shaped_and_informational(self):
        out, sent = run(echo=True)
        tp = next(b for b in sent if b and b.get("method") == "tools/list")["params"]["_meta"]["traceparent"]
        parts = tp.split("-")
        self.assertEqual([len(p) for p in parts], [2, 32, 16, 2])
        self.assertTrue(out["ok"])
        self.assertTrue(out["checks"]["trace_context"]["accepted_in_meta"])
        self.assertTrue(out["checks"]["trace_context"]["trace_header_returned"])
        self.assertTrue(out["summary"]["trace_context_accepted"])

    def test_strict_server_is_retried_without_meta_and_verdict_unchanged(self):
        out, sent = run(strict=True)
        lists = [b for b in sent if b and b.get("method") == "tools/list"]
        self.assertEqual(len(lists), 2)
        self.assertEqual(lists[1]["params"], {})
        self.assertTrue(out["ok"])
        self.assertFalse(out["checks"]["trace_context"]["accepted_in_meta"])
        self.assertNotIn("trace", " ".join(out["errors"]))


if __name__ == "__main__":
    unittest.main()
