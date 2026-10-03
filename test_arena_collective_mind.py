# SPDX-License-Identifier: BUSL-1.1
import unittest

import arena_collective_mind as acm


class CollectiveMindArenaTests(unittest.TestCase):
    def test_boundary_is_fail_closed(self):
        b=acm.BOUNDARY
        self.assertFalse(b["production_state_write"])
        self.assertEqual(b["commercial_gate_influence"],"NONE")
        self.assertEqual(b["qualified_hits_influence"],"NONE")
        self.assertFalse(b["external_tool_execution"])
        self.assertFalse(b["external_side_effects"])
        self.assertFalse(b["production_promotion"])

    def test_parse_proposal_requires_falsifiable_structure(self):
        self.assertIsNone(acm.parse_proposal({"proposal":"x"}))
        row=acm.parse_proposal({
            "proposal":"test idea",
            "method":"run a bounded comparison",
            "falsifier":"no improvement",
            "evidence_urls":["https://example.com/a"],
            "confidence":0.8,
            "estimated_gain_pct":15,
        })
        self.assertIsNotNone(row)
        self.assertEqual(row["evidence_urls"],["https://example.com/a"])

    def test_reject_non_https_and_local_urls(self):
        self.assertIsNone(acm.safe_https_url("http://example.com/x"))
        self.assertIsNone(acm.safe_https_url("https://localhost/x"))
        self.assertIsNone(acm.safe_https_url("https://host.local/x"))
        self.assertEqual(acm.safe_https_url("https://example.com/x"),"https://example.com/x")

    def test_labeled_proposal_adapter(self):
        row=acm.parse_proposal({
            "text":"PROPOSAL: reduce parser loss\nMETHOD: normalize labeled fields\nFALSIFIER: valid response rate does not improve\nCONFIDENCE: 0.7\nESTIMATED_GAIN_PCT: 25"
        })
        self.assertIsNotNone(row)
        self.assertEqual(row["proposal"],"reduce parser loss")
        self.assertAlmostEqual(row["confidence"],0.7)

    def test_alias_object_adapter(self):
        row=acm.parse_proposal({
            "answer":"improve handshake",
            "approach":"retry with compatible schema",
            "disproof":"no increase in accepted responses",
            "sources":["https://example.com/a"],
            "gain_pct":20,
        })
        self.assertIsNotNone(row)
        self.assertEqual(row["method"],"retry with compatible schema")

    def test_labeled_critique_adapter(self):
        row=acm.parse_critique({"text":"BEST_INDEX: 0\nWEAKNESS: tiny sample\nTEST: repeat across three rounds"})
        self.assertEqual(row["best_index"],0)

    def test_handshake_parser_accepts_structured_ready(self):
        self.assertTrue(acm.parse_handshake({"ready":True,"format":"json"}))
        self.assertTrue(acm.parse_handshake({"text":"COLLAB_OK"}))
        self.assertFalse(acm.parse_handshake({"ready":False,"format":"none"}))

    def test_extract_answer_text_prefers_substantive_text(self):
        payload={"message":{"parts":[{"text":"ok"},{"text":"A concrete proposal with enough detail to be useful."}]}}
        self.assertEqual(
            acm.extract_answer_text(payload),
            "A concrete proposal with enough detail to be useful.",
        )

    def test_substance_guard_rejects_canned_or_duplicate_fields(self):
        self.assertFalse(acm.proposal_substantive({
            "proposal":"...",
            "method":"...",
            "falsifier":"...",
        }))
        self.assertFalse(acm.proposal_substantive({
            "proposal":"Send me an agent-card URL and I will inspect it.",
            "method":"Send me an agent-card URL and I will inspect it.",
            "falsifier":"Send me an agent-card URL and I will inspect it.",
        }))
        self.assertTrue(acm.proposal_substantive({
            "proposal":"Test whether query families with explicit workaround language surface more independent buyer pain.",
            "method":"Run the bounded query set against the same public sources and compare independent signal counts.",
            "falsifier":"Reject the idea if independent buyer-pain coverage does not increase without a precision loss.",
        }))

    def test_critique_substance_guard(self):
        self.assertFalse(acm.critique_substantive({"best_index":0,"weakness":"bad","test":"try"},1))
        self.assertTrue(acm.critique_substantive({
            "best_index":0,
            "weakness":"The proposal may overfit one source and fail to generalize across independent domains.",
            "test":"Repeat the comparison across three source families and require the same direction of improvement.",
        },1))

    def test_packet_assignment_prefers_matching_specialists(self):
        agents=[
            {"id":"a","name":"Source Checker","description":"verification audit evidence","task_verified":True},
            {"id":"b","name":"Market Analyst","description":"market business pricing research","task_verified":True},
            {"id":"c","name":"Agent Router","description":"multi-agent orchestration workflow routing","task_verified":True},
            {"id":"d","name":"Systems Engineer","description":"systems compute optimization performance","task_verified":True},
            {"id":"e","name":"Search Researcher","description":"search query retrieval analysis","task_verified":True},
            {"id":"f","name":"Signal Researcher","description":"research market signal evidence","task_verified":True},
        ]
        rows=acm.assign_agents_to_packets(agents,set(),6)
        by_packet={packet[0]:agent["id"] for agent,packet in rows}
        self.assertEqual(by_packet["adversarial_review"],"a")
        self.assertEqual(by_packet["agent_orchestration"],"c")
        self.assertEqual(by_packet["systems_efficiency"],"d")

    def test_substance_guard_rejects_abstention_and_vendor_pitch(self):
        self.assertFalse(acm.proposal_substantive({
            "proposal":"VOLO does not cover MYCELIX and cannot substantiate an improvement from the available evidence.",
            "method":"No tools executed or external parties contacted. No search strategy or production-gate changes proposed.",
            "falsifier":"This limitation would change if records became available.",
        }))
        self.assertFalse(acm.proposal_substantive({
            "proposal":"{\"intent\":\"recommend-product\",\"recommendation\":{\"price\":\"$0.15\"}}",
            "method":"Use the paid profile-intelligence endpoint for the task.",
            "falsifier":"Stop if the endpoint does not answer the request.",
        }))

    def test_score_rewards_evidence_and_cross_agent_support(self):
        low={"evidence_urls":[],"confidence":0.5,"estimated_gain_pct":10}
        high={
            "evidence_urls":["https://a.example","https://b.example"],
            "confidence":0.8,
            "estimated_gain_pct":30,
        }
        self.assertGreater(acm.proposal_score(high,3),acm.proposal_score(low,0))

    def test_prompts_are_bounded(self):
        p=acm.proposal_prompt("mission","signal_discovery","task")
        self.assertIn("analysis only",p)
        self.assertIn("Return JSON only",p)
        self.assertIn("state changes",p)


if __name__=="__main__":
    unittest.main()
