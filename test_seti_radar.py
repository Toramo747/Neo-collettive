import unittest

from seti_radar import (
    SETI_ENGINE_VERSION,
    explicit_agent_endpoint_url,
    indexed_endpoint_leads,
    indexed_url_declared_as_agent_endpoint,
    inbound_admission_transition,
    interview_candidate_eligibility,
    interview_response_score,
    seti_dialogue_round,
    seti_followup_state,
    seti_progressive_interview_prompt,
    seti_retry_ready,
    merge_private_candidate_state,
    merge_signal_memory,
    summarize_candidate_eligibility,
    summarize_interview_readiness,
    seti_candidate_attempt_state,
    registry_match,
    registry_agent_candidate,
    score_public_result,
)


class SetiRadarTests(unittest.TestCase):
    def test_engine_version_is_multisource_revision(self):
        self.assertGreaterEqual(SETI_ENGINE_VERSION,2)

    def test_engine_version_covers_readiness_bootstrap(self):
        self.assertGreaterEqual(SETI_ENGINE_VERSION,9)

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

    def test_context_declared_nonstandard_endpoint_is_extracted(self):
        row={
            "title":"Public research agent",
            "url":"https://github.com/acme/agent/blob/main/README.md",
            "snippet":"A2A endpoint: https://runtime.acme.ai/rpc/v1 supports JSON-RPC message/send.",
            "source":"github-code-index-grepapp",
        }
        leads=indexed_endpoint_leads(row)
        self.assertEqual(len(leads),1)
        self.assertEqual(leads[0]["url"],"https://runtime.acme.ai/rpc/v1")
        self.assertEqual(leads[0]["endpoint_evidence"],"indexed_context_declaration")

    def test_escaped_indexed_endpoint_is_normalized(self):
        row={
            "title":"Agent card sample",
            "url":"https://github.com/acme/agent/blob/main/card.json",
            "snippet":r'Agent Card {"url":"https:\/\/runtime.acme.ai\/custom","protocolVersion":"0.3.0"}',
            "source":"github-code-index-grepapp",
        }
        leads=indexed_endpoint_leads(row)
        self.assertEqual(len(leads),1)
        self.assertEqual(leads[0]["url"],"https://runtime.acme.ai/custom")

    def test_nearby_documentation_url_is_not_mistaken_for_endpoint(self):
        text="A2A JSON-RPC message/send is supported. Documentation: https://docs.acme.ai/guide"
        self.assertFalse(indexed_url_declared_as_agent_endpoint(text,"https://docs.acme.ai/guide"))

    def test_explicit_endpoint_rejects_artifact_host(self):
        self.assertTrue(explicit_agent_endpoint_url("https://agent.example.ai/a2a"))
        self.assertFalse(explicit_agent_endpoint_url("https://github.com/acme/agent/a2a"))


    def test_public_registry_direct_endpoint_becomes_bounded_candidate(self):
        candidate=registry_agent_candidate({
            "id":"research-1",
            "name":"Research Agent",
            "description":"Evidence review and technical critique.",
            "url":"https://research.example.ai/a2a",
            "conformance":"standard",
            "task_verified":True,
            "is_healthy":True,
        },"community_a2a_registry")
        self.assertIsNotNone(candidate)
        self.assertEqual(candidate["classification"],"HIGH_INTEREST")
        self.assertTrue(candidate["indexed_declared_endpoint"])
        eligibility=interview_candidate_eligibility(candidate)
        self.assertTrue(eligibility["eligible"])
        self.assertEqual(eligibility["contact_mode"],"direct_a2a")

    def test_public_registry_artifact_or_non_https_is_rejected(self):
        self.assertIsNone(registry_agent_candidate({
            "name":"Repo only",
            "url":"https://github.com/acme/agent",
        }))
        self.assertIsNone(registry_agent_candidate({
            "name":"Unsafe",
            "url":"http://agent.example.ai/a2a",
        }))

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

    def test_progressive_interview_rounds_target_missing_fields(self):
        base="Round 1 base prompt"
        prior={
            "status":"PARKED",
            "attempts":1,
            "markers":{"identity":True,"capabilities":True,"protocol":False,"limits":False,"evidence":False},
            "response_full":"I am an agent and I can analyze text.",
            "attempt_history":[{
                "attempt":1,
                "response":"I am an agent and I can analyze text.",
            }],
        }
        self.assertEqual(seti_dialogue_round(prior),2)
        prompt=seti_progressive_interview_prompt(prior,base)
        self.assertIn("Round 2/3",prompt)
        self.assertIn("protocol/interface",prompt)
        self.assertIn("falsifiable test",prompt)
        self.assertEqual(seti_followup_state(prior),"FOLLOWUP_DUE")

    def test_third_round_is_final_and_falsifiable(self):
        prior={
            "status":"PARKED",
            "attempts":2,
            "markers":{"identity":True,"capabilities":True,"protocol":True,"limits":False,"evidence":False},
            "attempt_history":[
                {"attempt":1,"response":"first substantive answer"},
                {"attempt":2,"response":"second substantive answer"},
            ],
        }
        self.assertEqual(seti_dialogue_round(prior),3)
        prompt=seti_progressive_interview_prompt(prior,"base")
        self.assertIn("Round 3/3",prompt)
        self.assertIn("falsification condition",prompt)

    def test_transport_failures_do_not_advance_dialogue_round(self):
        prior={
            "status":"PARKED",
            "attempts":1,
            "reason":"ReadTimeout",
            "attempt_history":[{"attempt":1,"response":"","reason":"ReadTimeout"}],
        }
        self.assertEqual(seti_dialogue_round(prior),1)
        self.assertEqual(seti_followup_state(prior),"RETRY_TRANSPORT")

    def test_interview_readiness_distinguishes_rate_limit_and_exhaustion(self):
        candidate={"classification":"INTERESTING","max_score":70,"url":"https://agent.example.ai/a2a"}
        now="2026-09-23T12:00:00+00:00"
        self.assertEqual(seti_candidate_attempt_state(candidate,{},now)["reason"],"ready")
        parked={"status":"PARKED","attempts":1,"last_attempt_utc":"2026-09-23T11:30:00+00:00"}
        self.assertEqual(seti_candidate_attempt_state(candidate,parked,now,3600)["reason"],"rate_limited")
        exhausted={"status":"PARKED","attempts":3,"last_attempt_utc":"2026-09-23T10:00:00+00:00"}
        self.assertEqual(seti_candidate_attempt_state(candidate,exhausted,now,3600)["reason"],"attempts_exhausted")

    def test_readiness_summary_counts_ready_candidates(self):
        candidates={
            "a":{"classification":"INTERESTING","max_score":70,"url":"https://agent-a.example.ai/a2a"},
            "b":{"classification":"INTERESTING","max_score":70,"url":"https://agent-b.example.ai/a2a"},
        }
        interviews={"b":{"status":"PARKED","attempts":1,"last_attempt_utc":"2026-09-23T11:30:00+00:00"}}
        summary=summarize_interview_readiness(candidates,interviews,{},"2026-09-23T12:00:00+00:00",3600)
        self.assertEqual(summary["eligible"],2)
        self.assertEqual(summary["ready_now"],1)
        self.assertEqual(summary["reason_counts"]["rate_limited"],1)
        self.assertEqual(summary["reason_counts"]["ready"],1)

    def test_followup_is_rate_limited_and_stops_after_three_attempts(self):
        prior={
            "status":"PARKED",
            "attempts":1,
            "last_attempt_utc":"2026-09-23T09:00:00+00:00",
            "response_full":"substantive reply",
        }
        self.assertFalse(seti_retry_ready(prior,"2026-09-23T09:30:00+00:00",3600))
        self.assertTrue(seti_retry_ready(prior,"2026-09-23T10:00:01+00:00",3600))
        exhausted=dict(prior,attempts=3)
        self.assertEqual(seti_followup_state(exhausted),"EXHAUSTED")
        self.assertFalse(seti_retry_ready(exhausted,"2026-09-24T10:00:01+00:00",3600))

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

    def test_declared_endpoint_flag_survives_private_correlation(self):
        rows=[{
            "fingerprint":"fp2",
            "title":"Agent Runtime",
            "url":"https://runtime.example.ai/custom-rpc",
            "domain":"runtime.example.ai",
            "snippet":"A2A endpoint",
            "agent_likelihood_score":90,
            "classification":"HIGH_INTEREST",
            "signals":[],
            "source":"github-code-index-grepapp-declared-endpoint",
            "indexed_declared_endpoint":True,
            "endpoint_evidence":"indexed_context_declaration",
        }]
        state,_=merge_private_candidate_state({},rows,max_entries=16)
        candidate=next(iter(state["candidates"].values()))
        self.assertTrue(candidate["indexed_declared_endpoint"])
        eligibility=interview_candidate_eligibility(candidate)
        self.assertTrue(eligibility["eligible"])
        self.assertEqual(eligibility["reason"],"indexed_declared_public_agent_endpoint")

    def test_eligibility_summary_explains_high_interest_bottleneck(self):
        candidates={
            "a":{"classification":"HIGH_INTEREST","max_score":90,"url":"https://runtime.example.ai/custom","indexed_declared_endpoint":True},
            "b":{"classification":"HIGH_INTEREST","max_score":95,"url":"https://example.ai/blog"},
            "c":{"classification":"INTERESTING","max_score":60,"url":"https://github.com/acme/repo"},
        }
        summary=summarize_candidate_eligibility(candidates)
        self.assertEqual(summary["high_interest"],2)
        self.assertEqual(summary["high_interest_eligible"],1)
        self.assertEqual(summary["high_interest_reason_counts"]["indexed_declared_public_agent_endpoint"],1)
        self.assertEqual(summary["high_interest_reason_counts"]["no_explicit_agent_endpoint"],1)

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
