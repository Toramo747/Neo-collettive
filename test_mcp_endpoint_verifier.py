# SPDX-License-Identifier: BUSL-1.1
import unittest
from unittest.mock import AsyncMock, patch

import mcp_endpoint_verifier as v


class FakeResponse:
    def __init__(self, status=200, headers=None, chunks=None):
        self.status_code=status
        self.headers=headers or {}
        self._chunks=chunks or [b"{}"]

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def aiter_bytes(self):
        for chunk in self._chunks:
            yield chunk


class FakeClient:
    def __init__(self, responses):
        self.responses=list(responses)
        self.calls=[]

    def stream(self, method, url, **kwargs):
        self.calls.append({"method":method,"url":url,**kwargs})
        if not self.responses:
            raise AssertionError("no fake response left")
        return self.responses.pop(0)


class VerifierSecurityTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        v.reset_runtime_state_for_tests()

    def test_private_and_metadata_ranges_blocked(self):
        for ip in [
            "127.0.0.1",
            "10.0.0.1",
            "172.16.0.1",
            "192.168.1.1",
            "169.254.169.254",
            "100.64.0.1",
            "100.100.100.200",
            "::1",
            "fc00::1",
            "fe80::1",
            "0.0.0.0",
        ]:
            self.assertTrue(v._blocked_ip(ip), ip)
        self.assertFalse(v._blocked_ip("1.1.1.1"))
        self.assertFalse(v._blocked_ip("2606:4700:4700::1111"))

    async def test_only_https_and_no_userinfo_or_nonstandard_port(self):
        for url,code in [
            ("http://example.com/mcp","https_required"),
            ("https://user:pass@example.com/mcp","userinfo_forbidden"),
            ("https://example.com:8443/mcp","nonstandard_port_forbidden"),
            ("https://127.0.0.1/mcp","blocked_ip"),
            ("https://169.254.169.254/latest/meta-data","blocked_ip"),
            ("https://[fc00::1]/mcp","blocked_ip"),
        ]:
            with self.subTest(url=url):
                with self.assertRaises(v.VerificationError) as cm:
                    await v.validate_public_https(url)
                self.assertEqual(cm.exception.code,code)

    async def test_dns_resolution_to_private_ip_is_blocked(self):
        fake=[(2,1,6,"",("10.1.2.3",443))]
        with patch("mcp_endpoint_verifier.socket.getaddrinfo",return_value=fake):
            with self.assertRaises(v.VerificationError) as cm:
                await v.validate_public_https("https://public-looking.example/mcp")
        self.assertEqual(cm.exception.code,"blocked_resolved_ip")

    async def test_redirect_target_is_revalidated_and_private_redirect_blocked(self):
        client=FakeClient([
            FakeResponse(status=302,headers={"location":"https://127.0.0.1/internal"},chunks=[]),
        ])
        async def validate(url):
            if "127.0.0.1" in url:
                raise v.VerificationError("blocked_ip","127.0.0.1")
            return {"url":url,"host":"example.com","resolved_ips":["93.184.216.34"]}
        with patch("mcp_endpoint_verifier.validate_public_https",side_effect=validate):
            with self.assertRaises(v.VerificationError) as cm:
                await v._bounded_request(client,"GET","https://example.com/start")
        self.assertEqual(cm.exception.code,"blocked_ip")

    async def test_max_three_redirects(self):
        client=FakeClient([
            FakeResponse(status=302,headers={"location":f"/hop{i}"},chunks=[])
            for i in range(5)
        ])
        async def validate(url):
            return {"url":url,"host":"example.com","resolved_ips":["93.184.216.34"]}
        with patch("mcp_endpoint_verifier.validate_public_https",side_effect=validate):
            with self.assertRaises(v.VerificationError) as cm:
                await v._bounded_request(client,"GET","https://example.com/start",max_redirects=3)
        self.assertEqual(cm.exception.code,"too_many_redirects")

    async def test_response_size_limit(self):
        client=FakeClient([FakeResponse(status=200,chunks=[b"x"*(v.MAX_RESPONSE_BYTES+1)])])
        async def validate(url):
            return {"url":url,"host":"example.com","resolved_ips":["93.184.216.34"]}
        with patch("mcp_endpoint_verifier.validate_public_https",side_effect=validate):
            with self.assertRaises(v.VerificationError) as cm:
                await v._bounded_request(client,"GET","https://example.com/mcp")
        self.assertEqual(cm.exception.code,"response_too_large")

    async def test_auth_and_cookie_headers_are_never_forwarded(self):
        client=FakeClient([FakeResponse(status=200,chunks=[b"{}"])])
        async def validate(url):
            return {"url":url,"host":"example.com","resolved_ips":["93.184.216.34"]}
        with patch("mcp_endpoint_verifier.validate_public_https",side_effect=validate):
            await v._bounded_request(
                client,"POST","https://example.com/mcp",
                json_body={"x":1},
                headers={
                    "Authorization":"Bearer SECRET",
                    "Cookie":"session=SECRET",
                    "Mcp-Session-Id":"safe-session",
                    "MCP-Protocol-Version":"2025-11-25",
                },
            )
        headers=client.calls[0]["headers"]
        self.assertNotIn("Authorization",headers)
        self.assertNotIn("Cookie",headers)
        self.assertEqual(headers["Mcp-Session-Id"],"safe-session")

    def test_per_caller_and_global_rate_limits(self):
        with patch.object(v,"PER_CALLER_LIMIT",2), patch.object(v,"GLOBAL_LIMIT",3):
            v.consume_rate_limit("a")
            v.consume_rate_limit("a")
            with self.assertRaises(v.VerificationError) as cm:
                v.consume_rate_limit("a")
            self.assertEqual(cm.exception.code,"rate_limited_caller")
            v.consume_rate_limit("b")
            with self.assertRaises(v.VerificationError) as cm:
                v.consume_rate_limit("c")
            self.assertEqual(cm.exception.code,"rate_limited_global")

    def test_metrics_are_aggregate_only(self):
        v._record_usage("example.com",True,[])
        data=v.usage_metrics_snapshot()
        self.assertEqual(data["calls"],1)
        self.assertIn("example.com",data["domains"])
        serialized=str(data).lower()
        self.assertNotIn("caller",serialized.replace("anonymous aggregate metrics only; no caller ip or personal identifier stored",""))
        self.assertFalse(data["payment_signal"])

    def test_internal_usage_is_excluded_from_external_metrics(self):
        v._record_usage("scan.example", True, [], usage_scope="internal_registry_health")
        external=v.usage_metrics_snapshot()
        internal=v.internal_usage_metrics_snapshot()
        self.assertEqual(external["calls"],0)
        self.assertEqual(internal["calls"],1)
        self.assertEqual(internal["scope"],"internal_registry_health")

    async def test_request_pacer_serializes_same_host(self):
        pacer=v.RequestPacer(max_concurrency=4,per_host=1,min_host_interval=0)
        active=0
        peak=0
        async def one():
            nonlocal active,peak
            async with pacer.slot("same.example"):
                active+=1
                peak=max(peak,active)
                await __import__("asyncio").sleep(0.01)
                active-=1
        await __import__("asyncio").gather(*(one() for _ in range(4)))
        self.assertEqual(peak,1)

    def test_schema_sanity(self):
        self.assertTrue(v._schema_sane({"type":"object","properties":{},"required":[]}))
        self.assertFalse(v._schema_sane({"type":"string"}))
        self.assertFalse(v._schema_sane({"type":"object","properties":[]}))
        self.assertFalse(v._schema_sane({"type":"object","required":"x"}))


if __name__=="__main__":
    unittest.main()
