import unittest
from pathlib import Path


class HeartbeatWorkflowLatencyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workflow = Path(".github/workflows/mycelix-heartbeat-v3.yml").read_text(encoding="utf-8")

    def test_health_and_mcp_initialize_latency_samples_are_recorded(self):
        w=self.workflow
        self.assertIn("Measure first endpoint latencies",w)
        self.assertIn("Measure subsequent endpoint latencies",w)
        self.assertIn("https://neo-collettive.onrender.com/health",w)
        self.assertIn("https://neo-collettive.onrender.com/mcp",w)
        self.assertIn('"method":"initialize"',w)
        self.assertIn("mcp_initialize",w)
        self.assertIn("first_sample",w)
        self.assertIn("subsequent_sample",w)

    def test_first_sample_tsv_has_exact_field_count(self):
        w=self.workflow
        self.assertIn("printf '%s\\thealth\\t%s\\t%s\\t%s\\t%s\\n'",w)
        self.assertIn("printf '%s\\tmcp_initialize\\t%s\\t%s\\t%s\\t%s\\n'",w)
        self.assertNotIn("printf '%s\\thealth\\t%s\\t%s\\t%s\\t%s\\t%s\\n'",w)

    def test_first_request_is_explicit_cold_start_candidate(self):
        w=self.workflow
        self.assertIn("run_first_request",w)
        self.assertIn("cold_start_candidate",w)
        self.assertIn("The first HTTP request of each heartbeat run is /health",w)

    def test_latency_is_persisted_in_runtime_snapshot(self):
        w=self.workflow
        self.assertIn('"snapshot_schema": 7',w)
        self.assertIn('latency=load("/tmp/endpoint-latency.json",{})',w)
        self.assertIn('"endpoint_latency": latency',w)

    def test_uptime_monitor_instructions(self):
        doc=Path("docs/uptime-monitor.md").read_text(encoding="utf-8")
        self.assertIn("cron-job.org",doc)
        self.assertIn("https://neo-collettive.onrender.com/health",doc)
        self.assertIn("Europe/Rome",doc)
        self.assertIn("07:00-23:00",doc)
        self.assertIn("525",doc)
        self.assertIn("Andrea",doc)

    def test_render_budget_documented(self):
        doc=Path("docs/render-free-budget.md").read_text(encoding="utf-8")
        self.assertIn("750",doc)
        self.assertIn("637.5",doc)
        self.assertIn("07:00-23:00",doc)
        self.assertIn("15%",doc)

    def test_schedule_is_realistic_and_documented(self):
        self.assertIn('cron: "7,37 * * * *"',self.workflow)
        doc=Path("docs/heartbeat-operations.md").read_text(encoding="utf-8")
        self.assertIn("GitHub Actions does not guarantee",doc)
        self.assertIn("external uptime monitor",doc)

    def test_watchdog_schedule_is_resilient_and_dispatches_primary(self):
        w=Path(".github/workflows/mycelix-heartbeat-watchdog-v2.yml").read_text(encoding="utf-8")
        self.assertIn('cron: "2,12,22,32,42,52 * * * *"',w)
        self.assertIn("mycelix-heartbeat-watchdog",w)
        self.assertIn("cancel-in-progress: false",w)
        self.assertIn("actions/workflows/mycelix-heartbeat-v3.yml/dispatches",w)

    def test_runtime_snapshot_persists_inbound_audit_streams(self):
        w=self.workflow
        for field in (
            '"inbound_traffic_events"',
            '"inbound_traffic_summary"',
            '"inbound_security_events"',
            '"inbound_security_stats"',
            '"inbound_review_queue"',
        ):
            self.assertIn(field,w)

    def test_self_traffic_marker_requires_hmac_proof(self):
        w=self.workflow
        self.assertIn("X-MYCELIX-Self-Traffic-Proof",w)
        self.assertIn("self_traffic_auth.py sign-url",w)
        self.assertIn("secrets.NEO_HEARTBEAT_TOKEN",w)

    def test_no_workflow_sends_legacy_heartbeat_header(self):
        workflows=Path(".github/workflows")
        offenders=[]
        for path in sorted(workflows.glob("*.yml")):
            text=path.read_text(encoding="utf-8")
            if "X-NEO-Heartbeat-Token" in text:
                offenders.append(path.name)
        self.assertEqual(offenders,[])

    def test_hmac_signer_uses_runtime_env_value_without_literal_quote_escaping(self):
        w=self.workflow
        self.assertIn('NEO_HEARTBEAT_TOKEN="${HEARTBEAT_TOKEN}"',w)
        self.assertNotIn('NEO_HEARTBEAT_TOKEN=\\\"',w)

    def test_snapshot_prefers_top_level_latest_result(self):
        w=self.workflow
        self.assertIn('"latest_result": raw.get("latest_result") or ap.get("latest_result")',w)

    def test_poll_accepts_top_level_latest_result_fallback(self):
        w=self.workflow
        self.assertIn('latest=ap.get("latest_result") or d.get("latest_result")',w)

    def test_prior_cycle_error_requires_clean_completion(self):
        w=self.workflow
        self.assertIn('hb.get("last_error")',w)
        self.assertIn('if [ "$require_new_cycle" = "1" ]; then',w)
        self.assertIn("requires a clean completed cycle",w)

    def test_autonomy_status_exposes_hidden_control_for_snapshot(self):
        source=Path("cloud_mcp.py").read_text(encoding="utf-8")
        start=source.index("async def api_autonomy_status")
        end=source.index("\n\nasync def system",start)
        block=source[start:end]
        self.assertIn("hidden_control=_hidden_control_telemetry()",block)
        self.assertIn('"hidden_control":hidden_control',block)
        self.assertIn('ap_private.get("hidden_control") or raw.get("hidden_control")',self.workflow)

    def test_snapshot_uses_authenticated_full_autopilot_status(self):
        w=self.workflow
        self.assertIn("https://neo-collettive.onrender.com/api/autopilot/status",w)
        self.assertNotIn("https://neo-collettive.onrender.com/api/autonomy/status",w)
        self.assertIn('"evidence_memory_telemetry": ap.get("evidence_memory_telemetry") or {}',w)
        self.assertIn('"evidence_store_status": ap.get("evidence_store_status") or {}',w)
        self.assertIn('"last_checkpoint": ap.get("last_checkpoint") or {}',w)

    def test_successful_snapshot_notifies_runtime_freshness(self):
        w=self.workflow
        self.assertIn("/api/runtime/snapshot-published",w)
        self.assertIn("X-MYCELIX-Self-Traffic-Proof",w)
        self.assertIn("github-actions-heartbeat",w)
        self.assertLess(w.index("git push origin HEAD:main"),w.index("/api/runtime/snapshot-published"))

    def test_snapshot_commit_is_outside_deploy_and_pr_freeze_paths(self):
        deploy=Path(".github/workflows/neo-render-deploy.yml").read_text(encoding="utf-8")
        deploy_trigger=deploy.split("permissions:",1)[0]
        freeze=Path(".github/workflows/memory-repair-freeze.yml").read_text(encoding="utf-8")
        self.assertNotIn('"neo_latest_result.json"',deploy_trigger)
        self.assertNotIn('"neo_cycle_floor.json"',deploy_trigger)
        self.assertIn("pull_request:",freeze)
        self.assertNotIn("\n  push:",freeze)
        self.assertIn('git commit -m "MYCELIX runtime snapshot [skip render]"',self.workflow)

    def test_deploy_has_no_one_time_memory_repair_bootstrap(self):
        deploy=Path(".github/workflows/neo-render-deploy.yml").read_text(encoding="utf-8")
        self.assertNotIn('source_version=="0.99.53"',deploy)
        self.assertNotIn('source_commit=="520db03797bf9592052fb20e1f7a22b35e45a1d4"',deploy)
        self.assertNotIn("one_time_memory_repair_bootstrap_authorized",deploy)
        self.assertIn("pre-deploy checkpoint failed for non-overflow reason",deploy)

    def test_latency_probe_never_calls_remote_tools(self):
        w=self.workflow
        first=w.index("Measure first endpoint latencies")
        end=w.index("Validate heartbeat latency contract")
        probe=w[first:end]
        self.assertNotIn("tools/call",probe)


if __name__=="__main__":
    unittest.main()
