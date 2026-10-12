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


if __name__ == "__main__":
    unittest.main()
