import unittest

from seti_radar import (
    merge_signal_memory,
    registry_match,
    score_public_result,
)


class SetiRadarTests(unittest.TestCase):
    def test_machine_signature_scores_high(self):
        row={
            "title":"Autonomous runtime JSON-RPC message/send",
            "url":"https://example.ai/.well-known/agent-card.json",
            "snippet":"Supports JSONRPC message/send, task_id polling and webhook callbacks.",
        }
        scored=score_public_result(row)
        self.assertGreaterEqual(scored["agent_likelihood_score"],75)
        self.assertEqual(scored["classification"],"HIGH_INTEREST")

    def test_official_registry_is_filtered_as_noise(self):
        row={
            "title":"A2A Registry",
            "url":"https://a2aregistry.org/api/agents",
            "snippet":"message/send jsonrpc agent card",
        }
        scored=score_public_result(row)
        self.assertEqual(scored["classification"],"NOISE")

    def test_registry_match_detects_known_candidate(self):
        candidate={
            "title":"Hidden Agent Runtime",
            "url":"https://agent.example.ai/a2a",
        }
        discovery={
            "a2a_registry":{
                "ok":True,
                "data":{"agents":[{"name":"Example Agent","url":"https://agent.example.ai/a2a"}]},
            },
            "mcp_registry":{"ok":True,"data":{"servers":[]}},
        }
        self.assertTrue(registry_match(candidate,discovery))

    def test_persistence_bonus_without_storing_target(self):
        scan={
            "scanned_at_utc":"2026-09-22T08:00:00+00:00",
            "signals":[{
                "fingerprint":"abc123",
                "title":"Example",
                "url":"https://example.ai/a2a",
                "domain":"example.ai",
                "snippet":"jsonrpc message/send",
                "agent_likelihood_score":60,
                "classification":"INTERESTING",
                "signals":[],
                "registry_status":"not_found_in_checked_registries",
            }],
        }
        memory,rows=merge_signal_memory({},scan)
        self.assertEqual(memory["abc123"]["seen_count"],1)
        self.assertNotIn("url",memory["abc123"])
        memory2,rows2=merge_signal_memory(memory,scan)
        self.assertEqual(memory2["abc123"]["seen_count"],2)
        self.assertGreater(rows2[0]["agent_likelihood_score"],60)


if __name__ == "__main__":
    unittest.main()
