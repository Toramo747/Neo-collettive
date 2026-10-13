import asyncio
import unittest
from datetime import datetime, timezone
from unittest import mock

import common_jobs


class CommonJobsTests(unittest.TestCase):
    def test_detects_common_by_name_or_host(self):
        self.assertTrue(common_jobs.is_common_agent({"name": "Common Agent Network"}))
        self.assertTrue(common_jobs.is_common_agent({"name": "x", "url": "https://agents.dooza.ai/a2a"}))
        self.assertFalse(common_jobs.is_common_agent({"name": "Other", "url": "https://evil.example/agents.dooza.ai"}))
        self.assertFalse(common_jobs.is_common_agent(None))

    def test_payload_has_jobs_data_part_and_stable_daily_id(self):
        now = datetime(2026, 10, 12, 8, tzinfo=timezone.utc)
        p = common_jobs.job_payload("find evidence  of X", now)
        parts = p["params"]["message"]["parts"]
        self.assertEqual(parts[0]["kind"], "text")
        self.assertEqual(parts[1]["data"]["channel"], "jobs")
        self.assertEqual(parts[1]["data"]["agent"], "neo")
        self.assertEqual(p["params"]["message"]["messageId"], common_jobs.job_payload("find evidence of X", now)["params"]["message"]["messageId"])
        tomorrow = datetime(2026, 10, 13, 8, tzinfo=timezone.utc)
        self.assertNotEqual(p["params"]["message"]["messageId"], common_jobs.job_payload("find evidence of X", tomorrow)["params"]["message"]["messageId"])

    def test_daily_cap(self):
        now = datetime(2026, 10, 12, 8, tzinfo=timezone.utc)
        state = {}
        allowed = []
        for _ in range(12):
            state, ok = common_jobs.reserve_slot(state, now, cap=10)
            allowed.append(ok)
        self.assertEqual(sum(allowed), 10)
        self.assertEqual(state["skipped_today"], 2)
        state, ok = common_jobs.reserve_slot(state, datetime(2026, 10, 13, 0, 1, tzinfo=timezone.utc), cap=10)
        self.assertTrue(ok)
        self.assertEqual(state["posted_today"], 1)
        self.assertEqual(state["posted_total"], 11)


class TransportRoutingTests(unittest.TestCase):
    def test_common_goes_to_job_board_not_registry_and_is_not_evidence(self):
        import cloud_mcp
        calls = []

        async def fake_request(client, method, url, json_body=None, **kw):
            calls.append((url, json_body))
            return {"status": 200, "headers": {"content-type": "application/json"}, "body": "{\"result\":{}}"}

        cloud_mcp.AUTOPILOT_STATE["common_jobs"] = {}
        with mock.patch.object(cloud_mcp.endpoint_verifier, "_bounded_request", fake_request):
            ans = asyncio.run(cloud_mcp._ask_a2a_transport({"id": "c1", "name": "Common Agent Network"}, "probe"))
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][0], common_jobs.COMMON_A2A_URL)
        self.assertEqual(calls[0][1]["params"]["message"]["parts"][1]["data"]["channel"], "jobs")
        self.assertFalse(ans["quality_ok"])
        self.assertEqual(ans["transport"], "common_job_board")
        self.assertEqual(cloud_mcp.AUTOPILOT_STATE["common_jobs"]["ok_total"], 1)

        before = dict(cloud_mcp.AUTOPILOT_STATE.get("agent_trust") or {})
        cloud_mcp._update_agent_trust([ans], "research")
        self.assertEqual(before.get("c1"), (cloud_mcp.AUTOPILOT_STATE.get("agent_trust") or {}).get("c1"))


if __name__ == "__main__":
    unittest.main()
