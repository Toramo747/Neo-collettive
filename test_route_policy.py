from __future__ import annotations

import base64
import json
import re
import unittest

from route_policy import (
    ADMIN,
    OPS,
    PUBLIC,
    PUBLIC_PROJECTION,
    ROUTE_POLICY,
    RoutePolicyConfig,
    RoutePolicyMiddleware,
    classify_path,
)
from self_traffic_auth import make_self_traffic_proof, verify_self_traffic_proof


class _OkApp:
    async def __call__(self, scope, receive, send):
        body=b'{"ok":true}'
        await send({"type":"http.response.start","status":200,"headers":[(b"content-type",b"application/json")]})
        await send({"type":"http.response.body","body":body})


async def _call(app, path, method="GET", headers=None):
    header_rows=[]
    for key,value in (headers or {}).items():
        header_rows.append((str(key).lower().encode("latin1"),str(value).encode("latin1")))
    scope={
        "type":"http",
        "http_version":"1.1",
        "method":method,
        "scheme":"https",
        "path":path,
        "raw_path":path.encode(),
        "query_string":b"",
        "headers":header_rows,
        "client":("198.51.100.7",12345),
        "server":("testserver",443),
    }
    sent=[]
    done=False
    async def receive():
        nonlocal done
        if done:
            return {"type":"http.disconnect"}
        done=True
        return {"type":"http.request","body":b"","more_body":False}
    async def send(message):
        sent.append(message)
    await app(scope,receive,send)
    status=next(x["status"] for x in sent if x["type"]=="http.response.start")
    body=b"".join(x.get("body",b"") for x in sent if x["type"]=="http.response.body")
    headers_out=dict(next(x.get("headers",[]) for x in sent if x["type"]=="http.response.start"))
    return status,body,headers_out


class RoutePolicyCoverageTests(unittest.TestCase):
    def test_every_registered_route_is_explicitly_classified(self):
        source=open("cloud_mcp.py",encoding="utf-8").read()
        paths=set(re.findall(r'Route\("([^"]+)"',source))
        self.assertIn('Mount("/", app=mcp_app)',source)
        paths.add("/mcp")
        missing=sorted(path for path in paths if path not in ROUTE_POLICY)
        self.assertEqual(missing,[])

    def test_default_is_admin(self):
        self.assertEqual(classify_path("/unclassified-new-route"),ADMIN)

    def test_required_projection_routes_are_projection_class(self):
        expected={
            "/inbox","/agent-chats","/api/agent-chats",
            "/api/inbound/agents","/api/intelligence","/intelligence",
        }
        self.assertTrue(expected)
        self.assertEqual({path for path in expected if ROUTE_POLICY[path]==PUBLIC_PROJECTION},expected)


class RoutePolicyAuthTests(unittest.IsolatedAsyncioTestCase):
    def middleware(self, admin="test-admin", hmac_secret="test-hmac"):
        return RoutePolicyMiddleware(
            _OkApp(),
            RoutePolicyConfig(
                admin_token=lambda:admin,
                hmac_secret=lambda:hmac_secret,
                verify_hmac=verify_self_traffic_proof,
                projections_public=False,
            ),
        )

    async def test_admin_anonymous_401_empty_body(self):
        status,body,headers=await _call(self.middleware(),"/api/autopilot/status")
        self.assertEqual(status,401)
        self.assertEqual(body,b"")
        self.assertIn(b"www-authenticate",headers)

    async def test_admin_missing_env_is_503(self):
        status,body,_=await _call(self.middleware(admin=""),"/api/autopilot/status")
        self.assertEqual(status,503)
        self.assertEqual(body,b"")

    async def test_admin_bearer_and_basic_are_accepted(self):
        app=self.middleware()
        status,_,_=await _call(app,"/api/autopilot/status",headers={"authorization":"Bearer test-admin"})
        self.assertEqual(status,200)
        basic=base64.b64encode(b"admin:test-admin").decode("ascii")
        status,_,_=await _call(app,"/api/autopilot/status",headers={"authorization":"Basic "+basic})
        self.assertEqual(status,200)

    async def test_hmac_only_works_on_ops(self):
        proof=make_self_traffic_proof("test-hmac","/api/memory/status")
        status,_,_=await _call(
            self.middleware(),"/api/memory/status",
            headers={"x-mycelix-self-traffic-proof":proof},
        )
        self.assertEqual(status,200)
        admin_proof=make_self_traffic_proof("test-hmac","/api/autopilot/status")
        status,_,_=await _call(
            self.middleware(),"/api/autopilot/status",
            headers={"x-mycelix-self-traffic-proof":admin_proof},
        )
        self.assertEqual(status,401)

    async def test_model_shadow_cluster_upload_is_hmac_ops(self):
        self.assertEqual(classify_path("/api/model-shadow/challenge-clusters"),OPS)
        proof=make_self_traffic_proof("test-hmac","/api/model-shadow/challenge-clusters")
        status,_,_=await _call(
            self.middleware(),
            "/api/model-shadow/challenge-clusters",
            method="POST",
            headers={"x-mycelix-self-traffic-proof":proof},
        )
        self.assertEqual(status,200)

    async def test_admin_also_works_on_ops(self):
        status,_,_=await _call(
            self.middleware(),"/api/memory/status",
            headers={"authorization":"Bearer test-admin"},
        )
        self.assertEqual(status,200)

    async def test_public_is_anonymous(self):
        for path in ("/","/health","/livez","/readyz","/.well-known/agent-card.json","/api/checkpoint-status"):
            with self.subTest(path=path):
                status,_,_=await _call(self.middleware(),path)
                self.assertEqual(status,200)

    async def test_projection_is_admin_until_pr2(self):
        status,_,_=await _call(self.middleware(),"/api/agent-chats")
        self.assertEqual(status,401)

    async def test_failed_auth_rate_limit(self):
        app=self.middleware()
        statuses=[]
        for _ in range(11):
            status,_,_=await _call(app,"/api/autopilot/status")
            statuses.append(status)
        self.assertEqual(statuses[:10],[401]*10)
        self.assertEqual(statuses[10],429)


if __name__=="__main__":
    unittest.main()
