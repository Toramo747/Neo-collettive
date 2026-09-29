import unittest

from public_snapshot import sanitize_public_snapshot, public_snapshot_has_sensitive_peer_data


class PublicSnapshotPrivacyTests(unittest.TestCase):
    def test_peer_text_and_ip_are_removed_but_safe_telemetry_remains(self):
        raw={
            "autopilot":{
                "inbound_messages":[{
                    "source_message_id":"m1","thread_id":"anon:1","text":"secret peer body",
                    "content_fingerprint":"abc","user_agent":"peer/1",
                    "intent_primary":"RESEARCH","intent_secondary":["DISCOVERY"],
                    "intent_confidence":0.91,"intent_markers":{"RESEARCH":["research"]},
                    "intent_negated_markers":{},"commercial_intent":False,
                    "identity_status":"anonymous","neo_response_message_id":"r1",
                    "response_reason":"bounded_reply",
                }],
                "inbound_traffic_events":[{
                    "content_fingerprint":"abc","category":"real_contact",
                    "reason":"a2a_text_message","ip_or_origin":"203.0.113.7",
                }],
                "agent_chat_events":[
                    {"direction":"INBOUND","text":"secret peer body","message_id":"m1"},
                    {"direction":"OUTBOUND","text":"private neo reply","message_id":"r1"},
                ],
            }
        }
        safe=sanitize_public_snapshot(raw)
        self.assertFalse(public_snapshot_has_sensitive_peer_data(safe))
        message=safe["autopilot"]["inbound_messages"][0]
        self.assertEqual(message["content_fingerprint"],"abc")
        self.assertEqual(message["response_reason"],"bounded_reply")
        self.assertNotIn("text",message)
        self.assertNotIn("ip_or_origin",safe["autopilot"]["inbound_traffic_events"][0])
        for event in safe["autopilot"]["agent_chat_events"]:
            self.assertNotIn("text",event)

    def test_sanitizer_does_not_mutate_private_source(self):
        raw={"autopilot":{"inbound_messages":[{"text":"private"}]}}
        safe=sanitize_public_snapshot(raw)
        self.assertEqual(raw["autopilot"]["inbound_messages"][0]["text"],"private")
        self.assertNotIn("text",safe["autopilot"]["inbound_messages"][0])


if __name__=="__main__":
    unittest.main()
