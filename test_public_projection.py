from __future__ import annotations

import json
import unittest
from copy import deepcopy

import cloud_mcp
from public_projection import (
    FORBIDDEN_PUBLIC_KEYS,
    project_agent_chats,
    project_inbound_agents,
    project_intelligence,
    sanitize_public_url,
    validate_public_projection,
)


PRIVATE_MARKER="SYNTHETIC_PRIVATE_MARKER"
PRIVATE_IP="198.51.100.42"


def _walk_keys(value):
    out=[]
    if isinstance(value,dict):
        for key,child in value.items():
            out.append(str(key).lower())
            out.extend(_walk_keys(child))
    elif isinstance(value,list):
        for child in value:
            out.extend(_walk_keys(child))
    return out


async def _call(app,path,headers=None):
    scope={
        "type":"http","http_version":"1.1","method":"GET","scheme":"https",
        "path":path,"raw_path":path.encode(),"query_string":b"",
        "headers":[(str(k).lower().encode(),str(v).encode()) for k,v in (headers or {}).items()],
        "client":("203.0.113.9",1234),"server":("testserver",443),
    }
    sent=[]
    delivered=False
    async def receive():
        nonlocal delivered
        if delivered:
            return {"type":"http.disconnect"}
        delivered=True
        return {"type":"http.request","body":b"","more_body":False}
    async def send(message):
        sent.append(message)
    await app(scope,receive,send)
    status=next(x["status"] for x in sent if x["type"]=="http.response.start")
    body=b"".join(x.get("body",b"") for x in sent if x["type"]=="http.response.body")
    return status,body


class PublicProjectionUnitTests(unittest.TestCase):
    def test_projection_drops_raw_text_and_ids(self):
        monitor={
            "thread_count":1,
            "waiting_peer":1,
            "reply_due":0,
            "threads":[{
                "thread_id":"raw-thread-private",
                "agent_id":"raw-agent-private",
                "agent":"Raw Agent",
                "last_text":PRIVATE_MARKER,
                "pending_question":PRIVATE_MARKER,
                "admission_status":"ANONYMOUS",
                "dialogue_stage":"IDENTITY",
                "identity_status":"anonymous",
                "intent_primary":"DISCOVERY",
                "intent_secondary":["CONTACT"],
                "engagement_status":"WAITING_PEER",
                "inbound_messages":1,
                "outbound_messages":0,
                "first_seen_utc":"2026-09-30T01:00:00+00:00",
                "last_seen_utc":"2026-09-30T01:01:00+00:00",
            }],
        }
        out=project_agent_chats(monitor,secret_material="synthetic-salt")
        raw=json.dumps(out,sort_keys=True)
        self.assertNotIn(PRIVATE_MARKER,raw)
        self.assertNotIn("raw-thread-private",raw)
        self.assertNotIn("raw-agent-private",raw)
        self.assertTrue(out["threads"][0]["thread_ref"].startswith("thread_"))
        self.assertTrue(out["threads"][0]["agent_ref"].startswith("agent_"))
        for key in _walk_keys(out):
            self.assertNotIn(key,FORBIDDEN_PUBLIC_KEYS)

    def test_agent_projection_drops_network_and_free_text(self):
        stats={
            "peer-private":{
                "status":"ANONYMOUS",
                "dialogue_status":"IDENTITY",
                "identity_status":"anonymous",
                "intent_primary":"DISCOVERY",
                "last_seen_utc":"2026-09-30T01:00:00+00:00",
                "ip_or_origin":PRIVATE_IP,
                "user_agent":"synthetic-private-agent",
                "text":PRIVATE_MARKER,
            }
        }
        out=project_inbound_agents(stats,secret_material="synthetic-salt")
        raw=json.dumps(out,sort_keys=True)
        self.assertNotIn(PRIVATE_MARKER,raw)
        self.assertNotIn(PRIVATE_IP,raw)
        self.assertNotIn("peer-private",raw)

    def test_intelligence_projection_is_counts_only(self):
        state={
            "dialogue_history":[{"problem_excerpt":PRIVATE_MARKER}],
            "knowledge_ledger":[{"claim":PRIVATE_MARKER}],
            "hypothesis_queue":[{"status":"HYPOTHESIS","text":PRIVATE_MARKER}],
            "inbound_messages":[{"text":PRIVATE_MARKER}],
            "inbound_agent_stats":{"peer-private":{}},
            "cycles_completed":12,
        }
        out=project_intelligence(state)
        self.assertEqual(out["dialogue_count"],1)
        self.assertEqual(out["knowledge_count"],1)
        self.assertEqual(out["open_hypothesis_count"],1)
        self.assertEqual(out["inbound_count"],1)
        self.assertNotIn(PRIVATE_MARKER,json.dumps(out))

    def test_url_sanitizer_preserves_structure_and_redacts_values(self):
        out=sanitize_public_url("https://example.invalid/path/sub?invite=synthetic-value&mode=observe")
        self.assertIsNotNone(out)
        self.assertTrue(out.startswith("https://example.invalid/path/sub?"))
        self.assertIn("invite=<redacted>",out)
        self.assertIn("mode=<redacted>",out)
        self.assertNotIn("synthetic-value",out)
        self.assertNotIn("observe",out)

    def test_validator_fails_closed_on_forbidden_key_and_sensitive_string(self):
        with self.assertRaises(ValueError):
            validate_public_projection({"text":"synthetic"})
        with self.assertRaises(ValueError):
            validate_public_projection({"safe":"invite=synthetic"})


class PublicProjectionRuntimeTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.old_state=deepcopy(cloud_mcp.AUTOPILOT_STATE)
        self.old_admin=cloud_mcp.NEO_ADMIN_TOKEN
        self.old_hmac=cloud_mcp.HEARTBEAT_TOKEN
        cloud_mcp.NEO_ADMIN_TOKEN="synthetic-admin"
        cloud_mcp.HEARTBEAT_TOKEN="synthetic-hmac"
        if hasattr(cloud_mcp.app,"_failed"):
            cloud_mcp.app._failed.clear()
        cloud_mcp.AUTOPILOT_STATE.update({
            "inbound_messages":[{
                "message_id":"raw-message-private",
                "received_at_utc":"2026-09-30T01:00:00+00:00",
                "thread_id":"raw-thread-private",
                "text":PRIVATE_MARKER+" https://example.invalid/path?invite=synthetic-value",
                "sender":{"agent_id":"raw-agent-private","agent":"Raw Agent","declared":False},
                "method":"message/send",
                "agent_card_url":"https://example.invalid/card",
                "ip_or_origin":PRIVATE_IP,
                "user_agent":"private-user-agent",
            }],
            "agent_chat_events":[{
                "event_id":"event-private",
                "message_id":"raw-message-private",
                "timestamp_utc":"2026-09-30T01:00:00+00:00",
                "thread_id":"raw-thread-private",
                "direction":"INBOUND",
                "agent_id":"raw-agent-private",
                "agent":"Raw Agent",
                "text":PRIVATE_MARKER,
                "intent_primary":"DISCOVERY",
                "intent_secondary":["CONTACT"],
                "admission_status":"ANONYMOUS",
                "dialogue_stage":"IDENTITY",
                "identity_status":"anonymous",
            }],
            "inbound_agent_stats":{
                "raw-agent-private":{
                    "status":"ANONYMOUS",
                    "dialogue_status":"IDENTITY",
                    "identity_status":"anonymous",
                    "intent_primary":"DISCOVERY",
                    "last_seen_utc":"2026-09-30T01:00:00+00:00",
                    "ip_or_origin":PRIVATE_IP,
                    "user_agent":"private-user-agent",
                    "text":PRIVATE_MARKER,
                }
            },
            "dialogue_history":[{"problem_excerpt":PRIVATE_MARKER}],
            "knowledge_ledger":[{"claim":PRIVATE_MARKER}],
            "hypothesis_queue":[{"status":"HYPOTHESIS","text":PRIVATE_MARKER}],
        })

    def tearDown(self):
        cloud_mcp.AUTOPILOT_STATE.clear()
        cloud_mcp.AUTOPILOT_STATE.update(self.old_state)
        cloud_mcp.NEO_ADMIN_TOKEN=self.old_admin
        cloud_mcp.HEARTBEAT_TOKEN=self.old_hmac
        if hasattr(cloud_mcp.app,"_failed"):
            cloud_mcp.app._failed.clear()

    async def test_all_projection_routes_hide_synthetic_private_data(self):
        for path in (
            "/inbox","/agent-chats","/api/agent-chats",
            "/api/inbound/agents","/api/intelligence","/intelligence",
        ):
            with self.subTest(path=path):
                status,body=await _call(cloud_mcp.app,path)
                self.assertEqual(status,200)
                text=body.decode("utf-8","replace")
                self.assertNotIn(PRIVATE_MARKER,text)
                self.assertNotIn(PRIVATE_IP,text)
                self.assertNotIn("raw-thread-private",text)
                self.assertNotIn("raw-agent-private",text)
                self.assertNotIn("invite=",text)
                self.assertNotIn("synthetic-value",text)

    async def test_raw_data_is_available_only_on_admin_routes(self):
        for path in ("/api/admin/inbound","/api/admin/agent-chats"):
            with self.subTest(path=path):
                status,_=await _call(cloud_mcp.app,path)
                self.assertEqual(status,401)
                if hasattr(cloud_mcp.app,"_failed"):
                    cloud_mcp.app._failed.clear()
                status,body=await _call(
                    cloud_mcp.app,path,
                    headers={"authorization":"Bearer synthetic-admin"},
                )
                self.assertEqual(status,200)
                self.assertIn(PRIVATE_MARKER,body.decode("utf-8","replace"))


if __name__=="__main__":
    unittest.main()
