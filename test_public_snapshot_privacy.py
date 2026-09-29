import json
import unittest

from public_snapshot import sanitize_public_autopilot


class PublicSnapshotPrivacyTests(unittest.TestCase):
    def test_public_snapshot_excludes_inbound_text_reply_and_plain_ip(self):
        raw={
            "cycles_completed":7,
            "inbound_messages":[{
                "message_id":"m1","thread_id":"thread-secret","text":"PRIVATE INBOUND TEXT",
                "sender":{"agent_id":"peer-secret"},
            }],
            "agent_chat_events":[{
                "direction":"OUTBOUND","text":"PRIVATE NEO REPLY","thread_id":"thread-secret",
            }],
            "inbound_review_queue":[{"claim":"PRIVATE CLAIM","source_agent_id":"peer-secret"}],
            "inbound_agent_stats":{"peer-secret":{"last_seen_utc":"2026-09-29T13:00:00Z"}},
            "inbound_traffic_events":[{
                "timestamp_utc":"2026-09-29T13:00:00Z",
                "content_fingerprint":"abc123",
                "category":"real_contact",
                "reason":"a2a_text_message",
                "ip_or_origin":"203.0.113.55",
                "user_agent":"secret-agent/1.0",
                "thread_id":"thread-secret",
                "source_message_id":"m1",
                "tool_name":"secret_tool",
            }],
            "inbound_security_events":[{
                "received_at_utc":"2026-09-29T13:00:01Z",
                "traffic_class":"ADVERSARIAL_SPAM",
                "reason":"blocked_by_inbound_security",
                "text_excerpt":"PRIVATE SECURITY TEXT",
            }],
            "inbound_traffic_summary":{"counts":{"total":{"real_contact":1}}},
        }
        public=sanitize_public_autopilot(raw)
        encoded=json.dumps(public,sort_keys=True)
        for forbidden in (
            "PRIVATE INBOUND TEXT","PRIVATE NEO REPLY","PRIVATE CLAIM","PRIVATE SECURITY TEXT",
            "203.0.113.55","secret-agent/1.0","thread-secret","peer-secret","secret_tool",
        ):
            self.assertNotIn(forbidden,encoded)
        self.assertEqual(public["inbound_traffic_events"][0]["content_fingerprint"],"abc123")
        self.assertEqual(public["inbound_traffic_events"][0]["category"],"real_contact")
        self.assertEqual(public["inbound_traffic_events"][0]["reason"],"a2a_text_message")
        self.assertEqual(public["inbound_traffic_summary"]["counts"]["total"]["real_contact"],1)

    def test_public_snapshot_excludes_agent_chat_monitor_threads(self):
        raw={
            "agent_chat_monitor":{
                "thread_count":2,
                "threads":[
                    {"thread_id":"thread-secret","last_text":"PRIVATE INBOUND TEXT"},
                    {"thread_id":"peer-secret","last_text":"PRIVATE NEO REPLY"},
                ],
            },
        }
        public=sanitize_public_autopilot(raw)
        encoded=json.dumps(public,sort_keys=True)
        self.assertNotIn("thread-secret",encoded)
        self.assertNotIn("peer-secret",encoded)
        self.assertNotIn("PRIVATE INBOUND TEXT",encoded)
        self.assertNotIn("PRIVATE NEO REPLY",encoded)
        self.assertEqual(public["agent_chat_monitor"].get("thread_count"),2)
        self.assertNotIn("threads",public["agent_chat_monitor"])


if __name__=="__main__":
    unittest.main()
