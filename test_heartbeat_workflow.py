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
        self.assertIn('cron: "*/30 * * * *"',self.workflow)
        doc=Path("docs/heartbeat-operations.md").read_text(encoding="utf-8")
        self.assertIn("GitHub Actions does not guarantee",doc)
        self.assertIn("external uptime monitor",doc)

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

    def test_latency_probe_never_calls_remote_tools(self):
        w=self.workflow
        first=w.index("Measure first endpoint latencies")
        end=w.index("Validate heartbeat latency contract")
        probe=w[first:end]
        self.assertNotIn("tools/call",probe)


if __name__=="__main__":
    unittest.main()
