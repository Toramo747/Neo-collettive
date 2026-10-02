import json
import unittest

from public_snapshot import (
    MAX_PUBLIC_STRING_LENGTH,
    sanitize_public_autopilot,
    sanitize_public_snapshot,
    sanitize_public_jarvis_snapshot,
    validate_public_snapshot,
    validate_public_jarvis_snapshot,
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

    def test_select_diagnostics_are_aggregate_and_safe(self):
        raw={
            "snapshot_schema":7,
            "neo_version":"0.99.43",
            "latest_result":{
                "status":"SELECT",
                "evidence_quality":{
                    "current_cycle_useful_results":8,
                    "persistent_evidence_items":35,
                    "quarantined_evidence_items":12,
                    "qualified_problem_keys":["private-problem-key"],
                    "problem_clusters":{"a":{},"b":{},"c":{}},
                    "rejected_current_results":[
                        {"url":"https://secret.example/x","title":"PRIVATE"},
                        {"url":"https://secret.example/y","title":"PRIVATE2"},
                    ],
                    "ingestion_diagnostics":{
                        "raw_results_by_source":{"bing-rss":20,"github":5},
                        "query_relevance_pass_by_source":{"bing-rss":7,"github":2},
                        "rejected_by_reason":{"query_irrelevant":6,"vendor content":4},
                        "new_signal_rows":3,
                        "source_attempts":{"web":4,"hn":3,"github":2,"stackexchange":1},
                        "source_empty":{"web":1,"github":1},
                        "source_errors":{"stackexchange":1},
                        "search_provider":{
                            "name":"brave",
                            "calls_cycle":10,
                            "calls_day":149,
                            "errors":1,
                            "fallbacks":2,
                            "fallback_reasons":{"budget_exhausted":2},
                        },
                    },
                },
                "tool_opportunities":{
                    "top5":[
                        {
                            "gate_pass":False,
                            "monetization_score":72,
                            "missing":["two_independent_real_price_competitors","documented gap"],
                            "sources":[{"url":"https://private.example"}],
                        }
                    ],
                },
            },
            "autopilot":{"cycles_completed":1402},
        }
        public=sanitize_public_snapshot(raw)
        diag=public["autopilot"]["select_diagnostics"]
        self.assertEqual(diag["status"],"SELECT")
        self.assertEqual(diag["raw_results"],25)
        self.assertEqual(diag["relevance_pass"],9)
        self.assertEqual(diag["useful_results"],8)
        self.assertEqual(diag["persistent_evidence_items"],35)
        self.assertEqual(diag["quarantined_evidence_items"],12)
        self.assertEqual(diag["rejected_current_count"],2)
        self.assertEqual(diag["new_signal_rows"],3)
        self.assertEqual(diag["problem_cluster_count"],3)
        self.assertEqual(diag["qualified_problem_count"],1)
        self.assertEqual(diag["tool_candidate_count"],1)
        self.assertFalse(diag["top_gate_pass"])
        self.assertEqual(diag["top_monetization_score"],72)
        self.assertIn("two_independent_real_price_competitors",diag["top_missing"])
        self.assertIn("documented_gap",diag["top_missing"])
        self.assertEqual(diag["search_provider"]["calls_day"],149)
        sources={row["source"]:row for row in diag["search_sources"]}
        self.assertEqual(sources["web"]["attempts"],4)
        self.assertEqual(sources["github"]["empty"],1)
        self.assertEqual(sources["stackexchange"]["errors"],1)
        encoded=json.dumps(public,sort_keys=True)
        for forbidden in (
            "private-problem-key","secret.example","PRIVATE","PRIVATE2","private.example",
        ):
            self.assertNotIn(forbidden,encoded)
        validate_public_snapshot(public)

    def test_public_checkpoint_telemetry_is_bounded_and_numeric(self):
        raw={
            "autopilot":{
                "last_checkpoint":{
                    "ok":True,
                    "status":200,
                    "raw_bytes":123456,
                    "stored_bytes":54321,
                    "limit_bytes":100000,
                    "reason":"PRIVATE FAILURE DETAIL",
                    "heaviest_key":"PRIVATE_KEY",
                    "compaction":{
                        "applied":True,
                        "before_raw_bytes":234567,
                        "before_encoded_bytes":120000,
                        "after_raw_bytes":98765,
                        "after_encoded_bytes":54321,
                        "target_bytes":60000,
                        "trigger_bytes":90000,
                        "limit_bytes":100000,
                        "heaviest_key":"PRIVATE_KEY",
                    },
                },
            },
        }
        public=sanitize_public_snapshot(raw)
        cp=public["autopilot"]["last_checkpoint"]
        self.assertEqual(cp["ok"],True)
        self.assertEqual(cp["stored_bytes"],54321)
        self.assertEqual(cp["compaction"]["after_encoded_bytes"],54321)
        encoded=json.dumps(public,sort_keys=True)
        self.assertNotIn("PRIVATE FAILURE DETAIL",encoded)
        self.assertNotIn("PRIVATE_KEY",encoded)
        validate_public_snapshot(public)

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


    def test_jarvis_allowlist_drops_inbound_text_identifiers_and_commit_message(self):
        raw={
            "snapshot_utc":"2026-09-29T16:40:00Z",
            "source":"https://neo-collettive.onrender.com/api/render/diagnostics?target=neo",
            "target":"neo",
            "resource":"srv-1",
            "latest_log_utc":"2026-09-29T16:39:00Z",
            "latest_ask":{"message":"PRIVATE ASK"},
            "last_dialogue":{"reply":"PRIVATE REPLY"},
            "recent_inbound_traffic":[{
                "ip_or_origin":"203.0.113.55",
                "user_agent":"peer-agent/1.0",
                "source_message_id":"m1",
                "agent_id":"peer-secret",
            }],
            "service":{
                "name":"neo-collective-cloud",
                "type":"web_service",
                "region":"frankfurt",
                "suspended":False,
                "plan":"free",
                "updatedAt":"2026-09-29T16:00:00Z",
            },
            "inbound_traffic_summary":{
                "schema_v":2,
                "events_total":12,
                "counts":{"total":{"real_contact":2}},
                "real_contact_origins":[{"name":"203.0.113.55","requests":2}],
            },
            "categories":{"errors_5xx":1,"health_requests":4},
            "recent_deploys":[{
                "id":"dep-1","status":"live","createdAt":"2026-09-29T15:00:00Z",
                "updatedAt":"2026-09-29T15:01:00Z","finishedAt":"2026-09-29T15:02:00Z",
                "commit":{"id":"abcdef123456","message":"PRIVATE COMMIT MESSAGE","createdAt":"2026-09-29T14:59:00Z"},
            }],
            "note":"PRIVATE FREE TEXT",
        }
        public=sanitize_public_jarvis_snapshot(raw)
        encoded=json.dumps(public,sort_keys=True)
        for forbidden in (
            "source","latest_ask","last_dialogue","recent_inbound_traffic",
            "203.0.113.55","peer-agent/1.0","peer-secret","PRIVATE ASK",
            "PRIVATE REPLY","PRIVATE COMMIT MESSAGE","PRIVATE FREE TEXT",
            "real_contact_origins",
        ):
            self.assertNotIn(forbidden,encoded)
        self.assertEqual(public["inbound_traffic_summary"]["counts"]["total"]["real_contact"],2)
        self.assertNotIn("resource",public)
        self.assertNotIn("id",public["recent_deploys"][0])
        self.assertEqual(public["recent_deploys"][0]["commit_sha"],"abcdef123456")
        self.assertEqual(public["recent_deploys"][0]["commit_created_at"],"2026-09-29T14:59:00Z")
        validate_public_jarvis_snapshot(public)

    def test_jarvis_guard_rejects_unknown_key_ip_email_long_and_text(self):
        cases=[
            ("unknown", lambda d: d.__setitem__("future_field","x")),
            ("ipv4", lambda d: d.__setitem__("target","203.0.113.7")),
            ("ipv6", lambda d: d.__setitem__("target","2001:db8::7")),
            ("email", lambda d: d.__setitem__("target","peer@example.test")),
            ("long", lambda d: d.__setitem__("target","x"*(MAX_PUBLIC_STRING_LENGTH+1))),
            ("text", lambda d: d.__setitem__("message","PRIVATE")),
        ]
        for name,mutate in cases:
            public=sanitize_public_jarvis_snapshot({"snapshot_utc":"2026-09-29T16:40:00Z"})
            mutate(public)
            with self.subTest(case=name):
                with self.assertRaises(ValueError):
                    validate_public_jarvis_snapshot(public)


if __name__=="__main__":
    unittest.main()
