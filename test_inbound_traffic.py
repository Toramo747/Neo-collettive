import unittest
from datetime import datetime, timezone
from inbound_traffic import classify_inbound_event, append_event, summarize_events, retroactive_from_inbound_messages

class InboundTrafficTests(unittest.TestCase):
    def test_agent_card_fetch_is_crawler_probe(self):
        c,r,n=classify_inbound_event(endpoint="/.well-known/agent-card.json",method="GET")
        self.assertEqual((c,r),("crawler_probe","agent_card_fetch"))

    def test_a2a_message_with_text_is_real_contact(self):
        c,r,n=classify_inbound_event(endpoint="/a2a",method="POST",rpc_method="message/send",has_text=True)
        self.assertEqual((c,r),("real_contact","a2a_text_message"))

    def test_mcp_tools_call_is_real_contact(self):
        c,r,n=classify_inbound_event(endpoint="/mcp",method="POST",rpc_method="tools/call")
        self.assertEqual((c,r),("real_contact","mcp_tools_call"))

    def test_anomalous_request_is_unknown(self):
        c,r,n=classify_inbound_event(endpoint="/api/inbound/agents",method="POST",rpc_method="weird")
        self.assertEqual(c,"unknown")

    def test_directory_never_counts_as_real_contact(self):
        c,r,n=classify_inbound_event(endpoint="/a2a",method="POST",user_agent="agent-tools.cloud crawler",rpc_method="message/send",has_text=True)
        self.assertEqual(c,"crawler_probe")
        self.assertEqual(n,"agent-tools.cloud")
        c,r,n=classify_inbound_event(endpoint="/mcp",method="POST",origin="https://agent-tools.cloud",rpc_method="tools/call")
        self.assertEqual(c,"crawler_probe")

    def test_mcp_handshake_reclassified_when_session_calls_tool(self):
        rows=[]
        for rpc,cat in [("initialize","crawler_probe"),("tools/list","crawler_probe"),("tools/call","real_contact")]:
            c,r,n=classify_inbound_event(endpoint="/mcp",method="POST",rpc_method=rpc)
            rows=append_event(rows,{"timestamp_utc":"2026-09-28T06:00:00+00:00","endpoint":"/mcp","method":"POST","user_agent":"peer","ip_or_origin":"198.51.100.10","mcp_session_id":"s1","rpc_method":rpc,"category":c,"reason":r,"crawler_name":n})
        self.assertEqual([x["category"] for x in rows],["real_contact","real_contact","real_contact"])

    def test_summary_windows_and_real_contact_bounds(self):
        rows=[
            {"timestamp_utc":"2026-09-28T05:00:00+00:00","category":"crawler_probe","crawler_name":"agent-tools.cloud"},
            {"timestamp_utc":"2026-09-28T06:00:00+00:00","category":"real_contact"},
            {"timestamp_utc":"2026-09-20T06:00:00+00:00","category":"unknown"},
        ]
        s=summarize_events(rows,now=datetime(2026,9,28,7,0,tzinfo=timezone.utc))
        self.assertEqual(s["counts"]["total"]["crawler_probe"],1)
        self.assertEqual(s["counts"]["last_24h"]["real_contact"],1)
        self.assertEqual(s["counts"]["last_7d"]["unknown"],0)
        self.assertEqual(s["crawler_origins"][0]["name"],"agent-tools.cloud")
        self.assertEqual(s["real_contact_origins"][0]["name"],"unknown")

    def test_retroactive_existing_a2a_text_is_real_contact_only(self):
        rows=retroactive_from_inbound_messages([
            {"received_at_utc":"2026-09-23T05:00:00+00:00","method":"message/send","text":"hello","sender":{"agent_id":"peer-1","agent":"Peer"}},
            {"received_at_utc":"2026-09-23T05:01:00+00:00","method":"message/send","text":"","sender":{"agent_id":"peer-2"}},
        ])
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]["category"],"real_contact")
        self.assertTrue(rows[0]["historical_derived"])



if __name__=="__main__":
    unittest.main()
