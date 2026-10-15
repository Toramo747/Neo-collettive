import asyncio
import unittest
from unittest import mock

import cloud_mcp


class LightweightPinnedAgentsTests(unittest.TestCase):
    def run_pinned(self, candidates, trusted):
        async def fake_trusted(limit=8, exclude_ids=None, stage="general"):
            self.assertEqual(limit, 1)
            return trusted
        with mock.patch.object(cloud_mcp, "_trusted_agent_details", fake_trusted):
            return asyncio.run(cloud_mcp._lightweight_pinned_agents(candidates, set(), "research"))

    def test_common_and_best_performer_are_pinned_when_missing(self):
        out = self.run_pinned([{"id": "x", "url": "https://other.example/a2a"}], [{"id": "t1", "name": "Trusted"}])
        self.assertEqual([a["id"] for a in out], ["agent-commons", "t1"])
        self.assertTrue(all(a["_pinned"] for a in out))
        self.assertTrue(cloud_mcp.common_jobs.is_common_agent(out[0]))

    def test_common_not_duplicated_when_registry_returned_it(self):
        out = self.run_pinned([{"id": "c", "url": "https://agents.dooza.ai/a2a"}], [])
        self.assertEqual(out, [])

    def test_slow_trusted_lookup_does_not_block_probe(self):
        async def slow(limit=8, exclude_ids=None, stage="general"):
            await asyncio.sleep(10)
        with mock.patch.object(cloud_mcp, "_trusted_agent_details", slow), \
             mock.patch.object(cloud_mcp, "LIGHTWEIGHT_PINNED_TIMEOUT_SECONDS", 0.05):
            out = asyncio.run(cloud_mcp._lightweight_pinned_agents([], set(), "research"))
        self.assertEqual([a["id"] for a in out], ["agent-commons"])

    def test_disabled_flag_returns_nothing(self):
        with mock.patch.object(cloud_mcp, "LIGHTWEIGHT_PINNED_ENABLED", False):
            self.assertEqual(asyncio.run(cloud_mcp._lightweight_pinned_agents([], set(), "x")), [])

    def test_lightweight_path_uses_pinned_pool_and_bonus(self):
        src = open("cloud_mcp.py", encoding="utf-8").read()
        self.assertIn("await _lightweight_pinned_agents(candidates,existing_ids,trust_stage)\n        if lightweight", src)
        self.assertIn('if agent.get("_pinned"):\n            score += 6', src)


if __name__ == "__main__":
    unittest.main()
