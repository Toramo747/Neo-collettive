import unittest

from seti_radar import (
    SETI_ENGINE_VERSION,
    explicit_agent_endpoint_url,
    indexed_endpoint_leads,
    inbound_admission_transition,
    interview_candidate_eligibility,
    interview_response_score,
    merge_private_candidate_state,
    merge_signal_memory,
    registry_match,
    score_public_result,
)


class SetiRadarTests(unittest.TestCase):
    def test_engine_version_is_multisource_revision(self):
        self.assertGreaterEqual(SETI_ENGINE_VERSION,2)

    def test_machine_signature_scores_high(self):
        row={
            "title":"Autonomous runtime JSON-RPC message/send",
            "url":"https://example.ai/.well-known/agent-card.json",
            "snippet":"Supports JSONRPC message/send, task_id polling and webhook callbacks.",
        }
        scored=score_public_result(row)
        self.assertGreaterEqual(scored["agent_likelihood_score"],75)
        self.assertEqual(scored["classification"],"HIGH_INTEREST")
        self.assertEqual(scored["source_kind"],"web_index")

    def test_official_registry_is_filtered_as_noise(self):
        row={
            "title":"A2A Registry",
            "url":"https://a2aregistry.org/api/agents",
            "snippet":"message/send jsonrpc agent card",
        }
        scored=score_public_result(row)
        self.assertEqual(scored["classification"],"NOISE")

    def test_code_index_is_marked_as_code_artifact(self):
        row={
            "title":"acme/agent / agent-card.json",
            "url":"https://github.com/acme/agent/blob/main/agent-card.json",
            "snippet":"jsonrpc message/send Agent2Agent",
            "source":"github-code-index-grepapp",
        }
        scored=score_public_result(row)
        self.assertEqual(scored["source_kind"],"code_artifact")
        self.assertNotEqual(scored["classification"],"NOISE")

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

    def test_indexed_agent_card_endpoint_is_extracted_without_fetch(self):
        row={
            "title":"Public agent manifest",
            "url":"https://github.com/acme/agent/blob/main/README.md",
            "snippet":"Agent card available at https://runtime.acme.ai/.well-known/agent-card.json and supports message/send.",
            "source":"github-code-index-grepapp",
        }
        leads=indexed_endpoint_leads(row)
        self.assertEqual(len(leads),1)
        self.assertEqual(leads[0]["url"],"https://runtime.acme.ai/.well-known/agent-card.json")
        self.assertTrue(leads[0]["indexed_declared_endpoint"])

    def test_explicit_endpoint_rejects_artifact_host(self):
        self.assertTrue(explicit_agent_endpoint_url("https://agent.example.ai/a2a"))
        self.assertFalse(explicit_agent_endpoint_url("https://github.com/acme/agent/a2a"))

    def test_interview_gate_requires_repeat_and_explicit_endpoint(self):
        base={
            "classification":"HIGH_INTEREST",
            "max_score":84,
            "observations":2,
            "scan_count":2,
            "source_diversity":1,
        }
        eligible=dict(base,url="https://agent.example.ai/.well-known/agent-card.json")
        self.assertTrue(interview_candidate_eligibility(eligible)["eligible"])

        artifact=dict(base,url="https://github.com/example/agent/blob/main/agent-card.json")
        self.assertFalse(interview_candidate_eligibility(artifact)["eligible"])

        first_seen=dict(eligible,scan_count=1,observations=1)
        first_result=interview_candidate_eligibility(first_seen)
        self.assertTrue(first_result["eligible"])
        self.assertTrue(first_result["confidence"]["first_contact"])

        interesting=dict(first_seen,classification="INTERESTING",max_score=58)
        self.assertTrue(interview_candidate_eligibility(interesting)["eligible"])

    def test_interview_response_requires_capability_and_protocol(self):
        good=(
            "I am a public research agent. My capabilities include evidence review and source analysis. "
            "I support A2A JSON-RPC message/send. Documentation is available from my public reference page. "
            "A limitation is that I cannot verify private data or guarantee source accuracy without corroboration."
        )
        scored=interview_response_score(good)
        self.assertTrue(scored["accepted"])
        weak=interview_response_score("Hello, I can help.")
        self.assertFalse(weak["accepted"])

    def test_inbound_contact_is_parked_before_protocol_aware_intro(self):
        first=inbound_admission_transition(True,"Hello, I can help.",{})
        self.assertEqual(first["status"],"PARKED")
        self.assertTrue(first["retry_allowed"])
        self.assertFalse(first["newly_admitted"])

    def test_inbound_contact_can_be_admitted_after_substantive_intro(self):
        intro=(
            "I am Atlas, an autonomous research agent. My capabilities include public-source "
            "evidence review and technical critique. I support A2A JSON-RPC message/send and MCP. "
            "My limitation is that I cannot verify private systems; documentation and sources are "
            "provided when available."
        )
        admitted=inbound_admission_transition(True,intro,{"status":"PARKED","interview_attempts":1})
        self.assertEqual(admitted["status"],"ADMITTED")
        self.assertTrue(admitted["newly_admitted"])
        self.assertGreaterEqual(admitted["interview_score"],65)

    def test_anonymous_inbound_never_enters_admitted_state(self):
        intro=(
            "I am a public research agent with capabilities, A2A JSON-RPC message/send support, "
            "documented limitations, evidence references and source URLs."
        )
        state=inbound_admission_transition(False,intro,{})
        self.assertEqual(state["status"],"ANONYMOUS")
        self.assertFalse(state["newly_admitted"])

    def test_parked_inbound_stops_retry_after_three_weak_intros(self):
        state=inbound_admission_transition(
            True,
            "Hello, I can help with things.",
            {"status":"PARKED","interview_attempts":2},
        )
        self.assertEqual(state["status"],"PARKED")
        self.assertFalse(state["retry_allowed"])
        self.assertIn("three",state["reason"])

    def test_private_candidate_state_correlates_without_affecting_public_memory(self):
        rows=[{
            "fingerprint":"fp1",
            "title":"Agent Runtime",
            "url":"https://agent.example.ai/.well-known/agent-card.json",
            "domain":"agent.example.ai",
            "snippet":"jsonrpc message/send",
            "agent_likelihood_score":88,
            "classification":"HIGH_INTEREST",
            "signals":[{"type":"a2a_message_send","markers":["message/send"],"weight":24}],
            "source":"github-code-index-grepapp",
            "registry_status":"not_found_in_checked_registries",
            "first_seen_utc":"2026-09-22T09:00:00+00:00",
            "last_seen_utc":"2026-09-22T09:00:00+00:00",
        }]
        state,summary=merge_private_candidate_state({},rows,max_entries=16)
        self.assertEqual(summary["private_candidates"],1)
        self.assertEqual(summary["private_high_interest"],1)
        candidate=next(iter(state["candidates"].values()))
        self.assertEqual(candidate["url"],"https://agent.example.ai/.well-known/agent-card.json")
        state2,summary2=merge_private_candidate_state(state,rows,max_entries=16)
        candidate2=next(iter(state2["candidates"].values()))
        self.assertEqual(candidate2["observations"],2)
        self.assertEqual(summary2["reobserved_this_scan"],1)

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
