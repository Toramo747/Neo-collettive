import unittest
from pathlib import Path

from state_recovery import apply_monotonic_cycle_floor, merge_supplementary_state, reconcile_thesis_cycles, select_freshest_state, state_freshness


class StateRecoveryTests(unittest.TestCase):
    def test_higher_cycle_projection_does_not_replace_durable_private_state(self):
        source,payload,meta=select_freshest_state([
            ("render_env",{
                "cycles_completed":139,
                "state_saved_at_utc":"2026-09-23T03:00:00+00:00",
                "commercial_evidence_memory":[{"id":"durable"}],
            }),
            ("repo_snapshot",{
                "cycles_completed":141,
                "last_finished_utc":"2026-09-23T00:41:36+00:00",
            }),
        ])
        self.assertEqual(source,"render_env")
        self.assertEqual(payload["cycles_completed"],139)
        self.assertEqual(len(payload["commercial_evidence_memory"]),1)
        self.assertTrue(meta["projection_bypassed"])

    def test_sparse_repo_projection_never_beats_durable_env_on_tie(self):
        source,payload,meta=select_freshest_state([
            ("render_env",{
                "cycles_completed":141,
                "state_saved_at_utc":"2026-09-23T00:40:00+00:00",
                "commercial_evidence_memory":[{"id":"e1"}],
            }),
            ("repo_snapshot",{
                "cycles_completed":141,
                "last_finished_utc":"2026-09-23T00:41:36+00:00",
            }),
        ])
        self.assertEqual(source,"render_env")
        self.assertEqual(len(payload["commercial_evidence_memory"]),1)
        self.assertTrue(meta["projection_bypassed"])

    def test_newer_sparse_repo_projection_cannot_erase_28_evidence_rows(self):
        evidence=[{"id":f"e{i}"} for i in range(28)]
        source,payload,meta=select_freshest_state([
            ("render_env",{
                "cycles_completed":1948,
                "state_saved_at_utc":"2026-10-04T07:55:53+00:00",
                "commercial_evidence_memory":evidence,
            }),
            ("repo_snapshot",{
                "cycles_completed":1948,
                "last_finished_utc":"2026-10-04T07:58:02+00:00",
            }),
        ])
        self.assertEqual(source,"render_env")
        self.assertEqual(len(payload["commercial_evidence_memory"]),28)
        self.assertTrue(meta["projection_bypassed"])

    def test_exact_tie_prefers_fuller_local_state(self):
        source,_,_=select_freshest_state([
            ("repo_snapshot",{"cycles_completed":8}),
            ("render_env",{"cycles_completed":8}),
            ("local_snapshot",{"cycles_completed":8}),
        ])
        self.assertEqual(source,"local_snapshot")

    def test_empty_candidates_return_fresh(self):
        source,payload,meta=select_freshest_state([
            ("render_env",None),
            ("repo_snapshot",{}),
        ])
        self.assertEqual(source,"fresh")
        self.assertIsNone(payload)
        self.assertEqual(meta["candidates"],0)

    def test_freshness_handles_invalid_values(self):
        self.assertEqual(state_freshness({"cycles_completed":"bad"}),(0,0.0))

    def test_supplementary_merge_preserves_inbound_from_older_snapshot(self):
        selected={
            "cycles_completed":146,
            "inbound_messages":[],
            "inbound_agent_stats":{},
        }
        older={
            "cycles_completed":144,
            "inbound_messages":[
                {"message_id":"m1","received_at_utc":"2026-09-23T05:08:00+00:00","thread_id":"sender:a"}
            ],
            "inbound_agent_stats":{
                "a":{"agent_id":"a","status":"ADMITTED","last_seen_utc":"2026-09-23T05:08:00+00:00"}
            },
        }
        merged=merge_supplementary_state(selected,[("repo_snapshot",older)])
        self.assertEqual(len(merged["inbound_messages"]),1)
        self.assertIn("a",merged["inbound_agent_stats"])

    def test_supplementary_merge_preserves_telemetry_across_restart(self):
        before={
            "cycles_completed":144,
            "inbound_traffic_events":[{
                "event_id":"traffic-1","timestamp_utc":"2026-09-28T08:00:00+00:00",
                "endpoint":"/health","category":"crawler_probe",
            }],
        }
        after=merge_supplementary_state(
            {"cycles_completed":145,"inbound_traffic_events":[]},
            [("local_snapshot",before)],
        )
        self.assertEqual([x["event_id"] for x in after["inbound_traffic_events"]],["traffic-1"])

    def test_security_and_traffic_survive_multiple_consecutive_deploy_merges(self):
        mavis_traffic={
            "event_id":"traffic-mavis","timestamp_utc":"2026-09-28T04:50:12.687030+00:00",
            "endpoint":"/a2a","category":"malicious_solicitation",
        }
        mavis_security={
            "event_id":"sec-mavis","received_at_utc":"2026-09-28T04:50:12.687030+00:00",
            "traffic_class":"MALICIOUS_SOLICITATION",
            "reason":"download_execute_or_reward_solicitation",
        }
        deploy1=merge_supplementary_state(
            {"cycles_completed":200,"inbound_traffic_events":[],"inbound_security_events":[]},
            [("render_env",{
                "cycles_completed":199,
                "inbound_traffic_events":[mavis_traffic],
                "inbound_security_events":[mavis_security],
            })],
        )
        deploy2=merge_supplementary_state(
            {"cycles_completed":201,"inbound_traffic_events":[],"inbound_security_events":[]},
            [("repo_snapshot",deploy1)],
        )
        self.assertEqual([x["event_id"] for x in deploy2["inbound_traffic_events"]],["traffic-mavis"])
        self.assertEqual([x["event_id"] for x in deploy2["inbound_security_events"]],["sec-mavis"])
        self.assertEqual(deploy2["inbound_security_stats"]["malicious_solicitations"],1)

    def test_supplementary_merge_preserves_pending_inbound_review(self):
        before={"cycles_completed":144,"inbound_review_queue":[{
            "received_at_utc":"2026-09-28T10:00:00Z","source_agent_id":"peer-1",
            "thread_id":"t-1","claim_excerpt":"untrusted claim",
            "review_status":"PENDING_EXPLICIT_REVIEW",
        }]}
        after=merge_supplementary_state({"cycles_completed":145},[("local_snapshot",before)])
        self.assertEqual(after["inbound_review_queue"][0]["review_status"],"PENDING_EXPLICIT_REVIEW")


    def test_cycle_floor_raises_only_counter(self):
        selected={
            "cycles_completed":179,
            "family_performance":{"support":{"observations":7}},
            "active_thesis":{"id":"th-1"},
        }
        restored,meta=apply_monotonic_cycle_floor(
            selected,
            {
                "cycles_completed":181,
                "observed_at_utc":"2026-09-23T12:22:53.006851+00:00",
            },
        )
        self.assertEqual(restored["cycles_completed"],181)
        self.assertEqual(restored["family_performance"],selected["family_performance"])
        self.assertEqual(restored["active_thesis"],selected["active_thesis"])
        self.assertTrue(meta["applied"])
        self.assertEqual(meta["payload_cycles"],179)
        self.assertEqual(meta["floor_cycles"],181)

    def test_cycle_floor_never_regresses_newer_payload(self):
        restored,meta=apply_monotonic_cycle_floor(
            {"cycles_completed":184,"recent_sectors":["security"]},
            {
                "cycles_completed":181,
                "observed_at_utc":"2026-09-23T12:22:53.006851+00:00",
            },
        )
        self.assertEqual(restored["cycles_completed"],184)
        self.assertEqual(restored["recent_sectors"],["security"])
        self.assertFalse(meta["applied"])

    def test_cycle_floor_requires_auditable_timestamp(self):
        restored,meta=apply_monotonic_cycle_floor(
            {"cycles_completed":179},
            {"cycles_completed":999},
        )
        self.assertEqual(restored["cycles_completed"],179)
        self.assertFalse(meta["available"])
        self.assertFalse(meta["applied"])


    def test_thesis_cycles_reconcile_lagging_checkpoint(self):
        restored,meta=reconcile_thesis_cycles(
            {
                "status":"ACTIVE",
                "created_at_cycle":180,
                "cycles_used":3,
                "budget_cycles":4,
            },
            184,
        )
        self.assertEqual(restored["cycles_used"],4)
        self.assertTrue(meta["reconciled"])
        self.assertEqual(meta["derived_cycles_used"],4)

    def test_thesis_cycles_never_regress_stored_counter(self):
        restored,meta=reconcile_thesis_cycles(
            {
                "status":"ACTIVE",
                "created_at_cycle":180,
                "cycles_used":5,
            },
            184,
        )
        self.assertEqual(restored["cycles_used"],5)
        self.assertFalse(meta["reconciled"])
        self.assertEqual(meta["effective_cycles_used"],5)

    def test_deploy_forces_checkpoint_before_trigger(self):
        w=Path(".github/workflows/neo-render-deploy.yml").read_text(encoding="utf-8")
        force=w.index("Force durable checkpoint before deploy")
        trigger=w.index("Trigger Render deploy")
        self.assertLess(force,trigger)
        block=w[force:trigger]
        self.assertIn("-X POST",block)
        self.assertIn("/api/checkpoint-status",block)
        self.assertIn('d.get("ok") is not True',block)
        self.assertIn('code}" = "404"',block)
        self.assertIn("checkpoint too old",block)
        self.assertIn("pre-deploy checkpoint failed for non-overflow reason",block)
        self.assertIn("overflow_bootstrap_authorized",block)
        self.assertIn("legacy_overflow_bootstrap",block)
        self.assertIn("678f8e302237f3e9c6b403f80c2930aab860a3c3",block)
        self.assertIn("persistent_evidence_items",block)
        self.assertIn("evidence_regression_blocked",block)
        self.assertIn("timestamp_repaired",block)
        self.assertNotIn("one_time_memory_repair_bootstrap_authorized",block)
        self.assertNotIn('source_version=="0.99.53"',block)
        self.assertNotIn('source_commit=="520db03797bf9592052fb20e1f7a22b35e45a1d4"',block)
        self.assertIn("Verify repaired commercial evidence memory",w)
        self.assertIn("post-repair evidence recovery below verified floor",w)

    def test_thesis_cycles_match_completed_age_before_final_budget_cycle(self):
        restored,meta=reconcile_thesis_cycles(
            {
                "status":"ACTIVE",
                "created_at_cycle":180,
                "cycles_used":3,
            },
            183,
        )
        self.assertEqual(restored["cycles_used"],3)
        self.assertFalse(meta["reconciled"])
        self.assertEqual(meta["derived_cycles_used"],3)


if __name__=="__main__":
    unittest.main()
