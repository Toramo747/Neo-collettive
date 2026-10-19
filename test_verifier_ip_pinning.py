import unittest.mock
import asyncio
import os
import unittest

import httpx

import mcp_endpoint_verifier as v


class PinningTests(unittest.TestCase):
    def test_request_goes_to_validated_ip_with_real_hostname_for_tls(self):
        seen = {}

        def handler(request: httpx.Request):
            seen["host_in_url"] = request.url.host
            seen["host_header"] = request.headers.get("host")
            seen["sni"] = request.extensions.get("sni_hostname")
            return httpx.Response(200, json={"ok": True})

        async def fake_validate(url):
            return {"url": url, "host": "example.org", "resolved_ips": ["93.184.215.14"]}

        orig = v.validate_public_https
        v.validate_public_https = fake_validate
        try:
            async def run():
                async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
                    return await v._bounded_request(c, "GET", "https://example.org/mcp")
            r = asyncio.run(run())
        finally:
            v.validate_public_https = orig
        self.assertEqual(r["status"], 200)
        self.assertEqual(seen["host_in_url"], "93.184.215.14")
        self.assertEqual(seen["host_header"], "example.org")
        self.assertEqual(seen["sni"], "example.org")

    def test_bounded_request_retains_trace_headers_but_not_cookies(self):
        def handler(request):
            return httpx.Response(200, json={"result": {}}, headers={
                "traceparent": "00-" + "a" * 32 + "-" + "b" * 16 + "-01",
                "traceresponse": "echoed-trace", "set-cookie": "private=secret"})

        async def fake_validate(url):
            return {"host": "example.org", "resolved_ips": ["93.184.215.14"]}

        async def run():
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
                return await v._bounded_request(client, "POST", "https://example.org/mcp", json_body={})

        from unittest.mock import patch
        with patch.object(v, "validate_public_https", fake_validate):
            result = asyncio.run(run())
        self.assertEqual(result["headers"]["traceresponse"], "echoed-trace")
        self.assertIn("a" * 32, result["headers"]["traceparent"])
        self.assertNotIn("set-cookie", result["headers"])

    def test_ipv6_and_blocked_ip(self):
        url, headers, ext = v.pin_to_resolved_ip("https://h.example/x", {"host": "h.example", "resolved_ips": ["2606:4700::1111"]}, {})
        self.assertTrue(url.startswith("https://[2606:4700::1111]/"))
        with self.assertRaises(v.VerificationError):
            v.pin_to_resolved_ip("https://h.example/x", {"host": "h.example", "resolved_ips": ["127.0.0.1"]}, {})

    @unittest.skipUnless(os.getenv("GITHUB_ACTIONS") == "true", "live TLS check runs only on GitHub runners")
    def test_live_pinned_tls_request(self):
        async def run():
            async with httpx.AsyncClient(timeout=20, trust_env=False) as c:
                return await v._bounded_request(c, "GET", "https://api.github.com/zen")
        r = asyncio.run(run())
        self.assertEqual(r["status"], 200)



class HardeningTests(unittest.TestCase):
    def test_translation_and_embedded_private_ipv6_are_blocked(self):
        for ip in ("64:ff9b::7f00:1", "64:ff9b::a9fe:a9fe", "::127.0.0.1", "::ffff:10.0.0.1",
                   "2002:7f00:1::", "64:ff9b:1::1", "169.254.169.254", "100.64.0.1"):
            self.assertTrue(v._blocked_ip(ip), ip)
        for ip in ("1.1.1.1", "2606:4700:4700::1111"):
            self.assertFalse(v._blocked_ip(ip), ip)

    def test_blocked_address_is_not_echoed(self):
        async def run():
            return await v.resolve_public_ips("10.1.2.3")
        with self.assertRaises(v.VerificationError) as ctx:
            asyncio.run(run())
        self.assertNotIn("10.1.2.3", str(ctx.exception))

    def test_tool_output_never_lists_other_callers_domains(self):
        v._record_usage("someone-elses-server.example", True, [])
        counts = v.public_usage_counts()
        self.assertNotIn("domains", counts)
        self.assertNotIn("someone-elses-server", str(counts))

    def test_domain_metrics_are_capped(self):
        for i in range(600):
            v._record_usage(f"d{i}.example", False, [])
        self.assertLessEqual(len(v._METRICS["domains"]), 501)


class IPv4FirstTests(unittest.IsolatedAsyncioTestCase):
    async def test_dual_stack_host_pins_ipv4(self):
        import socket
        import mcp_endpoint_verifier as ev
        rows = [(socket.AF_INET6, socket.SOCK_STREAM, 6, "", ("2a09:8280:1::d:1234", 443, 0, 0)),
                (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("66.241.124.10", 443))]
        with unittest.mock.patch.object(ev.socket, "getaddrinfo", return_value=rows):
            ips = await ev.resolve_public_ips("hive-agents.fly.dev")
        self.assertEqual(ips[0], "66.241.124.10")
        self.assertEqual(len(ips), 2)


if __name__ == "__main__":
    unittest.main()
