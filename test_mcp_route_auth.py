from __future__ import annotations

import json
import unittest
from copy import deepcopy

import cloud_mcp
from self_traffic_auth import make_self_traffic_proof


class _OkMcpApp:
    async def __call__(self, scope, receive, send):
        # consume replayed request once
        await receive()
        body=b'{"jsonrpc":"2.0","id":"ok","result":{"ok":true}}'
        await send({"type":"http.response.start","status":200,"headers":[(b"content-type",b"application/json")]})
        await send({"type":"http.response.body","body":body})


async def _call(wrapper, payload, headers=None):
    raw=json.dumps(payload,separators=(",",":")).encode("utf-8")
    scope={
        "type":"http","http_version":"1.1","method":"POST","scheme":"https",
        "path":"/mcp","raw_path":b"/mcp","query_string":b"",
        "headers":[
            (str(k).lower().encode("latin1"),str(v).encode("latin1"))
            for k,v in (headers or {}).items()
        ],
        "client":("198.51.100.20",4444),"server":("testserver",443),
    }
    sent=[]
    delivered=False
    async def receive():
        nonlocal delivered
        if delivered:
            return {"type":"http.disconnect"}
        delivered=True
        return {"type":"http.request","body":raw,"more_body":False}
    async def send(message):
        sent.append(message)
    await wrapper(scope,receive,send)
    status=next(x["status"] for x in sent if x["type"]=="http.response.start")
    body=b"".join(x.get("body",b"") for x in sent if x["type"]=="http.response.body")
    return status,json.loads(body.decode("utf-8")) if body else {}


class McpAuthorizationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.old_events=deepcopy(cloud_mcp.AUTOPILOT_STATE.get("inbound_traffic_events") or [])
        self.old_summary=deepcopy(cloud_mcp.AUTOPILOT_STATE.get("inbound_traffic_summary") or {})
        self.old_admin=cloud_mcp.NEO_ADMIN_TOKEN
        self.old_hmac=cloud_mcp.HEARTBEAT_TOKEN
        self.old_save=cloud_mcp._save_local_state
        cloud_mcp.NEO_ADMIN_TOKEN="synthetic-admin"
        cloud_mcp.HEARTBEAT_TOKEN="synthetic-hmac"
        cloud_mcp._save_local_state=lambda: None
        cloud_mcp._MCP_PUBLIC_READONLY_CALLS_BY_ORIGIN.clear()
        cloud_mcp._MCP_PUBLIC_READONLY_GLOBAL_CALLS.clear()
        self.wrapper=cloud_mcp._InboundTrafficASGI(_OkMcpApp())

    def tearDown(self):
        cloud_mcp.AUTOPILOT_STATE["inbound_traffic_events"]=self.old_events
        cloud_mcp.AUTOPILOT_STATE["inbound_traffic_summary"]=self.old_summary
        cloud_mcp.NEO_ADMIN_TOKEN=self.old_admin
        cloud_mcp.HEARTBEAT_TOKEN=self.old_hmac
        cloud_mcp._save_local_state=self.old_save
        cloud_mcp._MCP_PUBLIC_READONLY_CALLS_BY_ORIGIN.clear()
        cloud_mcp._MCP_PUBLIC_READONLY_GLOBAL_CALLS.clear()

    async def test_initialize_and_tools_list_are_public(self):
        for method in ("initialize","tools/list"):
            with self.subTest(method=method):
                status,_=await _call(self.wrapper,{"jsonrpc":"2.0","id":1,"method":method,"params":{}})
                self.assertEqual(status,200)

    async def test_neo_web_search_anonymous_is_denied(self):
        status,data=await _call(
            self.wrapper,
            {"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"neo_web_search","arguments":{"query":"synthetic"}}},
        )
        self.assertEqual(status,403)
        self.assertEqual((data.get("error") or {}).get("code"),-32003)

    async def test_network_tool_admin_or_hmac_is_allowed(self):
        payload={"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"neo_web_search","arguments":{"query":"synthetic"}}}
        status,_=await _call(self.wrapper,payload,headers={"authorization":"Bearer synthetic-admin"})
        self.assertEqual(status,200)

        proof=make_self_traffic_proof("synthetic-hmac","/mcp")
        status,_=await _call(self.wrapper,payload,headers={"x-mycelix-self-traffic-proof":proof})
        self.assertEqual(status,200)

    async def test_public_readonly_tool_is_public_and_rate_limited(self):
        payload={"jsonrpc":"2.0","id":4,"method":"tools/call","params":{"name":"neo_director_results","arguments":{}}}
        for _ in range(30):
            status,_=await _call(self.wrapper,payload)
            self.assertEqual(status,200)
        status,data=await _call(self.wrapper,payload)
        self.assertEqual(status,429)
        self.assertEqual((data.get("error") or {}).get("code"),-32029)

    def test_tool_access_table_is_explicit(self):
        self.assertEqual(cloud_mcp.MCP_TOOL_ACCESS["neo_director_results"],"public_readonly")
        self.assertEqual(cloud_mcp.MCP_TOOL_ACCESS["neo_web_search"],"gated_network")
        self.assertEqual(cloud_mcp.MCP_TOOL_ACCESS["oxibay_doctor"],"gated_network")
        for name,access in cloud_mcp.MCP_TOOL_ACCESS.items():
            self.assertIn(access,{"public_readonly","gated_network","gated_effectful"},name)


if __name__=="__main__":
    unittest.main()
