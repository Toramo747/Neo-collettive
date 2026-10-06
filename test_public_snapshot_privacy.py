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
            "diagnostics":{
                "status_endpoint_reached":True,
                "source_commit":"abc123",
                "runtime_contract_verified":True,
                "hidden_control":{"required":True,"cases":10,"correct":9,"ok":False},
            },
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
                        "enabled":False,
                        "raw_results_by_source":{"bing-rss":20,"github":5},
                        "query_relevance_pass_by_source":{"bing-rss":7,"github":2},
                        "rejected_by_reason":{"query_irrelevant":6,"vendor content":4},
                        "new_signal_rows":3,
                        "buyer_voice_by_source":{"brave-search":3,"hn-algolia-routed":2},
                        "source_attempts":{"web":4,"hn":3,"github":2,"stackexchange":1},
                        "source_empty":{"web":1,"github":1},
                        "source_errors":{"stackexchange":1},
                        "search_provider":{
                            "name":"brave",
                            "calls_cycle":10,
                            "calls_day":149,
                            "errors":1,
                            "fallbacks":2,
                            "configured_provider":"brave",
                            "provider_key_present":True,
                            "fallback_used":True,
                            "fallback_reasons":{"budget_exhausted":2},
                        },
                        "funnel":{
                            "queries_planned":10,
                            "queries_executed":9,
                            "calls_by_source":{"web":4,"hn":3,"github":2},
                            "errors_by_source":{"web":{"ReadTimeout":1}},
                            "raw_received":25,
                            "deduped":20,
                            "query_relevant":9,
                            "family_matched":6,
                            "buyer_voice":5,
                            "commercial_signal":3,
                            "persisted":2,
                            "discarded_by_reason":{"vendor_content":2},
                            "monotonicity_warnings":[],
                        },
                        "agent_probes":{
                            "probes_attempted":5,
                            "agents_reached":2,
                            "answers_received":3,
                            "valid_answers":2,
                            "rejected_answers":1,
                            "timeouts":0,
                        },
                    },
                },
                "tool_opportunities":{
                    "candidate_counts":{
                        "configured_categories":5,
                        "evidenced_candidates":2,
                        "gate_eligible_candidates":1,
                        "qualified_candidates":0,
                    },
                    "top5":[
                        {
                            "gate_pass":False,
                            "monetization_score":72,
                            "missing":["two_competitors_with_real_price","documented gap"],
                            "sources":[{"url":"https://private.example"}],
                        }
                    ],
                },
            },
            "autopilot":{"cycles_completed":1402},
        }
        public=sanitize_public_snapshot(raw)
        self.assertEqual(public["diagnostics"]["hidden_control"],{
            "required":True,"cases":10,"correct":9,"ok":False,
        })
        diag=public["autopilot"]["select_diagnostics"]
        self.assertEqual(diag["status"],"SELECT")
        self.assertFalse(diag["ingestion_enabled"])
        self.assertEqual(diag["raw_results"],25)
        self.assertEqual(diag["relevance_pass"],9)
        self.assertEqual(diag["useful_results"],8)
        self.assertEqual(diag["persistent_evidence_items"],35)
        self.assertEqual(diag["quarantined_evidence_items"],12)
        self.assertEqual(diag["rejected_current_count"],2)
        self.assertEqual(diag["new_signal_rows"],3)
        self.assertEqual(diag["problem_cluster_count"],3)
        self.assertEqual(diag["qualified_problem_count"],1)
        self.assertEqual(diag["configured_categories"],5)
        self.assertEqual(diag["evidenced_candidates"],2)
        self.assertEqual(diag["gate_eligible_candidates"],1)
        self.assertEqual(diag["qualified_candidates"],0)
        self.assertFalse(diag["top_gate_pass"])
        self.assertEqual(diag["top_monetization_score"],72)
        self.assertIn("two_competitors_with_real_price",diag["top_missing"])
        self.assertIn("documented_gap",diag["top_missing"])
        self.assertEqual(diag["search_provider"]["calls_day"],149)
        self.assertEqual(diag["search_provider"]["configured_provider"],"brave")
        self.assertTrue(diag["search_provider"]["provider_key_present"])
        self.assertTrue(diag["search_provider"]["fallback_used"])
        self.assertEqual(diag["funnel"]["raw_received"],25)
        self.assertEqual(diag["funnel"]["persisted"],2)
        self.assertIn(
            {"source":"web","error":"ReadTimeout","count":1},
            diag["funnel"]["errors_by_source"],
        )
        self.assertEqual(diag["agent_probes"]["valid_answers"],2)
        voices={row["source"]:row["count"] for row in diag["buyer_voice_by_source"]}
        self.assertEqual(voices["brave-search"],3)
        self.assertEqual(voices["hn-algolia-routed"],2)
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

    def test_select_diagnostics_accept_compact_director_top_level_shape(self):
        raw={
            "snapshot_schema":7,
            "neo_version":"0.99.43",
            "latest_result":{
                "status":"SELECT",
                "current_cycle_useful_results":4,
                "persistent_evidence_items":11,
                "quarantined_evidence_items":3,
                "qualified_problem_keys":["private-problem-key"],
                "problem_clusters":{"a":{},"b":{}},
                "rejected_current_results":[{"url":"https://secret.example/x","title":"PRIVATE"}],
                "ingestion_diagnostics":{
                    "enabled":True,
                    "raw_results_by_source":{"brave-search":6},
                    "query_relevance_pass_by_source":{"brave-search":2},
                    "new_signal_rows":1,
                    "search_provider":{
                        "name":"brave",
                        "configured_provider":"brave",
                        "provider_key_present":True,
                        "fallback_used":False,
                        "calls_cycle":3,
                        "calls_day":17,
                        "errors":0,
                        "fallbacks":0,
                        "fallback_reasons":{},
                    },
                    "funnel":{
                        "queries_planned":10,
                        "queries_executed":3,
                        "calls_by_source":{"web":3},
                        "errors_by_source":{},
                        "raw_received":6,
                        "deduped":5,
                        "query_relevant":2,
                        "family_matched":1,
                        "buyer_voice":1,
                        "commercial_signal":1,
                        "persisted":1,
                        "discarded_by_reason":{"query_irrelevant":3},
                        "monotonicity_warnings":[],
                    },
                    "agent_probes":{
                        "probes_attempted":5,
                        "agents_reached":1,
                        "answers_received":2,
                        "valid_answers":1,
                        "rejected_answers":1,
                        "timeouts":0,
                    },
                },
                "tool_opportunities":{
                    "candidate_counts":{
                        "configured_categories":9,
                        "evidenced_candidates":6,
                        "gate_eligible_candidates":6,
                        "qualified_candidates":0,
                    },
                    "top5":[],
                },
            },
            "autopilot":{"cycles_completed":1585},
        }
        public=sanitize_public_snapshot(raw)
        diag=public["autopilot"]["select_diagnostics"]
        self.assertTrue(diag["ingestion_enabled"])
        self.assertEqual(diag["raw_results"],6)
        self.assertEqual(diag["relevance_pass"],2)
        self.assertEqual(diag["useful_results"],4)
        self.assertEqual(diag["persistent_evidence_items"],11)
        self.assertEqual(diag["quarantined_evidence_items"],3)
        self.assertEqual(diag["rejected_current_count"],1)
        self.assertEqual(diag["problem_cluster_count"],2)
        self.assertEqual(diag["qualified_problem_count"],1)
        self.assertEqual(diag["search_provider"]["configured_provider"],"brave")
        self.assertEqual(diag["funnel"]["queries_planned"],10)
        self.assertEqual(diag["funnel"]["raw_received"],6)
        encoded=json.dumps(public,sort_keys=True)
        self.assertNotIn("private-problem-key",encoded)
        self.assertNotIn("secret.example",encoded)
        self.assertNotIn("PRIVATE",encoded)
        validate_public_snapshot(public)

    def test_candidate_telemetry_is_bounded_hmac_only_and_code_only(self):
        raw={
            "snapshot_schema":7,
            "neo_version":"0.99.50",
            "latest_result":{
                "status":"SELECT",
                "tool_opportunities":{
                    "top5":[],
                    "candidate_counts":{},
                    "candidate_telemetry":[{
                        "candidate_id":"0123456789abcdef",
                        "evidence_fingerprint":"fedcba9876543210",
                        "id_key_version":"v1",
                        "score":90,
                        "source_count":4,
                        "independent_domain_count":3,
                        "raw_gate_pass":True,
                        "stable_gate_pass":False,
                        "pass_streak":1,
                        "fail_streak":0,
                        "missing_codes":["documented_gap","https://secret.example/x"],
                        "cycle":1958,
                        "commit":"0123456789abcdef0123456789abcdef01234567",
                        "first_cycle_after_deploy":True,
                        "seconds_since_first_raw_pass":12,
                        "tagger_version":"3",
                        "url":"https://private.example/x",
                        "domain":"private.example",
                        "title":"PRIVATE TITLE",
                    }],
                },
            },
            "autopilot":{"cycles_completed":1958},
        }
        public=sanitize_public_snapshot(raw)
        rows=public["autopilot"]["select_diagnostics"]["candidates"]
        self.assertEqual(len(rows),1)
        row=rows[0]
        self.assertEqual(row["candidate_id"],"0123456789abcdef")
        self.assertEqual(row["evidence_fingerprint"],"fedcba9876543210")
        self.assertEqual(row["missing_codes"],["documented_gap"])
        encoded=json.dumps(rows,sort_keys=True)
        for forbidden in ("secret.example","private.example","PRIVATE TITLE","https://"):
            self.assertNotIn(forbidden,encoded)
        validate_public_snapshot(public)

        bad=json.loads(json.dumps(public))
        bad["autopilot"]["select_diagnostics"]["candidates"][0]["missing_codes"]=["secret.example"]
        with self.assertRaisesRegex(ValueError,"candidate_missing_code"):
            validate_public_snapshot(bad)

        bad=json.loads(json.dumps(public))
        bad["autopilot"]["select_diagnostics"]["candidates"][0]["tagger_version"]="secret.example"
        with self.assertRaisesRegex(ValueError,"candidate_tagger"):
            validate_public_snapshot(bad)

    def test_challenge_snapshot_is_aggregate_hmac_only_and_text_free(self):
        raw={
            "snapshot_schema":7,
            "neo_version":"0.99.51",
            "latest_result":{
                "status":"SELECT",
                "tool_opportunities":{"top5":[],"candidate_counts":{}},
                "challenge_shadow":{
                    "mode":"shadow",
                    "status":"CHALLENGE_READY",
                    "tagger_version":"1",
                    "manual_confirmation_required":True,
                    "thresholds":{"min_requesters":3,"min_domains":2,"min_age_days":60},
                    "funnel":{
                        "collected":9,"routed":4,"independent_requesters":3,
                        "age_qualified":3,"workarounds":1,"feasibility_checked":4,"ready":1,
                    },
                    "candidate_counts":{"observed":2,"ready":1},
                    "candidates":[{
                        "candidate_id":"0123456789abcdef",
                        "evidence_fingerprint":"fedcba9876543210",
                        "id_key_version":"v1",
                        "score":85,
                        "source_count":4,
                        "independent_domain_count":2,
                        "independent_requester_count":3,
                        "age_days":120,
                        "workaround_count":1,
                        "feasibility_code":"unknown",
                        "reward_signal_count":1,
                        "raw_gate_pass":True,
                        "stable_gate_pass":True,
                        "pass_streak":2,
                        "fail_streak":0,
                        "missing_codes":["https://secret.example/x","unknown_requirement"],
                        "cycle":2000,
                        "commit":"0123456789abcdef0123456789abcdef01234567",
                        "first_cycle_after_deploy":False,
                        "seconds_since_first_raw_pass":300,
                        "tagger_version":"1",
                        "url":"https://private.example/x",
                        "domain":"private.example",
                        "title":"PRIVATE CHALLENGE",
                        "text":"PRIVATE TEXT",
                    }],
                },
            },
            "autopilot":{"cycles_completed":2000},
        }
        public=sanitize_public_snapshot(raw)
        diag=public["autopilot"]["challenge_diagnostics"]
        self.assertEqual(diag["status"],"CHALLENGE_READY")
        self.assertEqual(diag["funnel"]["routed"],4)
        self.assertEqual(len(diag["candidates"]),1)
        self.assertEqual(diag["candidates"][0]["missing_codes"],["unknown_requirement"])
        encoded=json.dumps(diag,sort_keys=True)
        for forbidden in ("secret.example","private.example","PRIVATE CHALLENGE","PRIVATE TEXT","https://"):
            self.assertNotIn(forbidden,encoded)
        validate_public_snapshot(public)

        bad=json.loads(json.dumps(public))
        bad["autopilot"]["challenge_diagnostics"]["candidates"][0]["missing_codes"]=["secret.example"]
        with self.assertRaisesRegex(ValueError,"challenge_missing_code"):
            validate_public_snapshot(bad)

    def test_model_shadow_snapshot_is_aggregate_only(self):
        raw={
            "snapshot_schema":7,
            "neo_version":"0.99.52",
            "autopilot":{
                "cycles_completed":2001,
                "model_shadow":{
                    "schema_v":1,
                    "mode":"shadow",
                    "student_metrics":{
                        "student_available":True,
                        "observed":100,
                        "agreement":82,
                        "disagreement":18,
                        "agreement_rate_ppm":820000,
                        "lexicon_positive":40,
                        "student_positive":42,
                        "student_low_confidence":7,
                        "student_version_code":"student-v1",
                        "text":"PRIVATE EVIDENCE",
                        "url":"https://secret.example/x",
                    },
                    "challenge_cluster_map":{
                        "schema_v":1,
                        "updated_at_utc":"2026-10-04T10:00:00Z",
                        "mapping":[{
                            "evidence_id":"0123456789abcdef",
                            "cluster_id":"fedcba9876543210",
                            "review_state":"REVIEW_REQUIRED",
                            "requester_weight":3,
                            "domain":"secret.example",
                            "text":"PRIVATE",
                        }],
                    },
                    "promotion":{"mode":"manual_only","approved":False},
                },
            },
        }
        public=sanitize_public_snapshot(raw)
        shadow=public["autopilot"]["model_shadow"]
        self.assertEqual(shadow["observed"],100)
        self.assertEqual(shadow["agreement"],82)
        self.assertEqual(shadow["challenge_clusters"]["mapping_count"],1)
        self.assertEqual(shadow["challenge_clusters"]["cluster_count"],1)
        self.assertEqual(shadow["challenge_clusters"]["review_required"],1)
        self.assertEqual(shadow["promotion"],{"mode":"manual_only","approved":False})
        encoded=json.dumps(shadow,sort_keys=True)
        for forbidden in (
            "PRIVATE","secret.example","https://",
            "0123456789abcdef","fedcba9876543210",
            '"mapping"',
        ):
            self.assertNotIn(forbidden,encoded)
        validate_public_snapshot(public)

        bad=json.loads(json.dumps(public))
        bad["autopilot"]["model_shadow"]["text"]="PRIVATE"
        with self.assertRaises(ValueError):
            validate_public_snapshot(bad)

    def test_evaluator_contract_snapshot_is_numeric_only(self):
        raw={"autopilot":{"evaluator_contracts":{
            "commercial":{"benchmark_ok":True,"robustness_ok":True,"control_ok":True,"best_fitness":61.5,"promotion_ready":False,"secret":"x"},
            "challenge":{"benchmark_ok":True,"robustness_ok":True,"control_ok":False,"best_fitness":100.0,"promotion_ready":False},
            "warp":{"benchmark_ok":True,"robustness_ok":False,"control_ok":False,"best_fitness":0.0,"promotion_ready":False},
        }}}
        public=sanitize_public_snapshot(raw)
        rows=public["autopilot"]["evaluator_contracts"]
        self.assertEqual(rows["commercial"]["best_fitness"],61.5)
        self.assertNotIn("secret",json.dumps(rows))
        validate_public_snapshot(public)

    def test_evidence_store_status_uses_restored_runtime_counts(self):
        raw={
            "autopilot":{
                "commercial_evidence_memory":[{"id":1},{"id":2},{"id":3}],
                "pending_evidence":[{"id":4}],
                "commercial_evidence_archive_rows":[{"id":5},{"id":6}],
                "evidence_store_status":{
                    "status":"ok","active_count":0,"pending_count":0,"archive_count":0,
                },
            },
        }
        public=sanitize_public_snapshot(raw)
        status=public["autopilot"]["evidence_store_status"]
        self.assertEqual(status["active_count"],3)
        self.assertEqual(status["pending_count"],1)
        self.assertEqual(status["archive_count"],2)
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
