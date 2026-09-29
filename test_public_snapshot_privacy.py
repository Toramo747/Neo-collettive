import json
import unittest

from public_snapshot import (
    MAX_PUBLIC_STRING_LENGTH,
    sanitize_public_autopilot,
    sanitize_public_snapshot,
    validate_public_snapshot,
)


class PublicSnapshotPrivacyTests(unittest.TestCase):
    def test_public_snapshot_is_allowlist_not_denylist(self):
        raw={
            "captured_at_utc":"2026-09-29T16:00:00Z",
            "snapshot_schema":7,
            "neo_version":"0.99.42",
            "brand":"must-be-dropped",
            "runtime_profile":{
                "profile_id":"mycelix-prod-main",
                "deployment_role":"production",
                "state_schema":1,
                "config_fingerprint":"abcdef0123456789",
                "new_future_identifier":"must-be-dropped",
            },
            "autopilot":{
                "enabled":True,
                "cycles_completed":10,
                "new_future_field":{"text":"PRIVATE FUTURE TEXT"},
                "inbound_messages":[{"text":"PRIVATE INBOUND TEXT"}],
                "build_history":[{"reply":"PRIVATE NEO REPLY"}],
            },
            "new_top_level":{"message":"PRIVATE TOP LEVEL TEXT"},
        }
        public=sanitize_public_snapshot(raw)
        encoded=json.dumps(public,sort_keys=True)
        for forbidden in (
            "brand","new_future_identifier","new_future_field","inbound_messages",
            "build_history","PRIVATE FUTURE TEXT","PRIVATE INBOUND TEXT",
            "PRIVATE NEO REPLY","new_top_level","PRIVATE TOP LEVEL TEXT",
        ):
            self.assertNotIn(forbidden,encoded)
        self.assertEqual(public["runtime_profile"]["profile_id"],"mycelix-prod-main")
        self.assertEqual(public["autopilot"]["cycles_completed"],10)
        validate_public_snapshot(public)

    def test_public_autopilot_keeps_only_bounded_traffic_fields(self):
        raw={
            "cycles_completed":7,
            "inbound_traffic_events":[{
                "timestamp_utc":"2026-09-29T13:00:00Z",
                "content_fingerprint":"abc123",
                "category":"real_contact",
                "reason":"a2a_text_message",
                "ip_or_origin":"203.0.113.55",
                "user_agent":"secret-agent/1.0",
                "thread_id":"thread-secret",
                "source_message_id":"m1",
                "text":"PRIVATE INBOUND TEXT",
            }],
            "inbound_security_events":[{
                "received_at_utc":"2026-09-29T13:00:01Z",
                "traffic_class":"ADVERSARIAL_SPAM",
                "reason":"blocked_by_inbound_security",
                "text_excerpt":"PRIVATE SECURITY TEXT",
            }],
            "agent_chat_monitor":{"thread_count":2,"threads":[{"last_text":"PRIVATE NEO REPLY"}]},
            "agent_demand_observatory":{"messages_observed":4,"agents":[{"agent_id":"peer-secret"}]},
        }
        public=sanitize_public_autopilot(raw)
        encoded=json.dumps(public,sort_keys=True)
        for forbidden in (
            "203.0.113.55","secret-agent/1.0","thread-secret","peer-secret",
            "PRIVATE INBOUND TEXT","PRIVATE SECURITY TEXT","PRIVATE NEO REPLY",
        ):
            self.assertNotIn(forbidden,encoded)
        self.assertEqual(public["inbound_traffic_events"][0],{
            "timestamp_utc":"2026-09-29T13:00:00Z",
            "content_fingerprint":"abc123",
            "category":"real_contact",
            "reason":"a2a_text_message",
        })
        self.assertEqual(public["agent_chat_monitor"],{"thread_count":2})
        self.assertEqual(public["agent_demand_observatory"],{"messages_observed":4})

    def test_guard_rejects_unknown_key(self):
        public=sanitize_public_snapshot({"neo_version":"0.99.42"})
        public["unexpected"]="x"
        with self.assertRaisesRegex(ValueError,"unknown_key"):
            validate_public_snapshot(public)

    def test_guard_rejects_ipv4_ipv6_and_email(self):
        for bad in ("203.0.113.55","2001:db8::1","privacy@example.test"):
            public=sanitize_public_snapshot({"neo_version":"0.99.42"})
            public["neo_version"]=bad
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    validate_public_snapshot(public)

    def test_guard_rejects_long_strings(self):
        public=sanitize_public_snapshot({"neo_version":"0.99.42"})
        public["neo_version"]="x"*(MAX_PUBLIC_STRING_LENGTH+1)
        with self.assertRaisesRegex(ValueError,"string_too_long"):
            validate_public_snapshot(public)

    def test_guard_rejects_free_text_key_even_if_nested(self):
        public=sanitize_public_snapshot({"neo_version":"0.99.42"})
        public["autopilot"]["inbound_traffic_events"]=[{
            "timestamp_utc":"2026-09-29T13:00:00Z",
            "content_fingerprint":"abc123",
            "category":"real_contact",
            "reason":"a2a_text_message",
            "text":"PRIVATE",
        }]
        with self.assertRaises(ValueError):
            validate_public_snapshot(public)


if __name__=="__main__":
    unittest.main()
