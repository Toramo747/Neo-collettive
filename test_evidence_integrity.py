import unittest

from evidence_integrity import (
    canonical_problem_key,
    canonical_url,
    commercial_family,
    demand_signal_type,
    gate_eligible_problem_key,
    migrate_evidence_memory,
    structured_paid_source,
    thesis_attributed_problem_key,
)


class EvidenceIntegrityTests(unittest.TestCase):
    def test_rate_substring_does_not_create_paid_demand(self):
        tags=demand_signal_type("", "generate accurate integrate operate")
        self.assertNotIn("PAID_DEMAND", tags)

    def test_excel_does_not_match_excellent(self):
        self.assertEqual(commercial_family("excellent customer service"), "other")

    def test_llm_does_not_match_stillman(self):
        self.assertNotEqual(commercial_family("Stillman workflow problem"), "ai_tools")

    def test_vendor_pricing_is_competition_not_paid_demand(self):
        tags=demand_signal_type("Enterprise plans", "Pricing subscription book a demo")
        self.assertIn("COMPETITION", tags)
        self.assertNotIn("PAID_DEMAND", tags)

    def test_buyer_budget_can_create_paid_demand(self):
        tags=demand_signal_type(
            "Looking for contractor",
            "Need help with manual reporting. Budget 500 EUR, hiring freelancer.",
            "paid_market",
        )
        self.assertIn("PAID_DEMAND", tags)
        self.assertIn("BUY_INTENT", tags)
        self.assertIn("PAIN", tags)

    def test_disconfirm_never_positive(self):
        tags=demand_signal_type(
            "LLM automation solved",
            "This is not needed and easy to automate. Budget irrelevant.",
            "disconfirm",
        )
        self.assertEqual(tags, ["DISCONFIRM"])

    def test_legacy_ai_keys_become_generic_and_nonqualifying(self):
        for tail in ("llm","agentic","generative_ai","ai_assistant","ai_tool","ai_automation"):
            key=canonical_problem_key("ai_tools","ai_tools:"+tail)
            self.assertEqual(key,"ai_tools:generic_technology")
            self.assertFalse(gate_eligible_problem_key(key))

    def test_generic_never_gate_eligible(self):
        self.assertFalse(gate_eligible_problem_key("ai_tools:generic_technology"))
        self.assertFalse(gate_eligible_problem_key("ai_tools:general"))

    def test_url_dedup_strips_tracking_and_fragment(self):
        a=canonical_url("https://Example.com/path/?utm_source=x&a=1#frag")
        b=canonical_url("https://example.com/path?a=1")
        self.assertEqual(a,b)

    def test_v2_gate_evidence_is_quarantined_after_v3_tagger_upgrade(self):
        original=[{
            "schema_v":2,
            "tagger_v":2,
            "migration_v":2,
            "gate_eligible":True,
            "domain":"remoteok.com",
            "family":"ai_tools",
            "problem_key_raw":"ecommerce_tools:general",
            "problem_key":"ai_tools:small_businesses:produce_recurring_client_and_management_reports",
            "thesis_bound":True,
            "url":"https://remoteok.com/remote-jobs/unrelated-role",
            "title":"Unrelated structured vacancy",
            "last_seen_epoch":1,
        }]
        once,meta=migrate_evidence_memory(original)
        self.assertFalse(once[0]["gate_eligible"])
        self.assertEqual(once[0]["quarantine_reason"],"legacy_unverified_tagger_v1")
        self.assertEqual(once[0]["schema_v"],3)
        self.assertEqual(once[0]["tagger_v"],2)
        self.assertEqual(meta["changed"],1)

    def test_migration_is_idempotent_and_quarantines_v1(self):
        original=[{
            "domain":"news.ycombinator.com",
            "family":"ai_tools",
            "problem_key":"ai_tools:llm",
            "url":"https://news.ycombinator.com/item?id=1",
            "title":"AI example",
            "last_seen_epoch":1,
        }]
        once,meta1=migrate_evidence_memory(original)
        twice,meta2=migrate_evidence_memory(once)
        self.assertEqual(once,twice)
        self.assertFalse(once[0]["gate_eligible"])
        self.assertEqual(once[0]["problem_key"],"ai_tools:generic_technology")
        self.assertEqual(meta2["changed"],0)

    def test_structured_paid_source_requires_paid_market_role(self):
        self.assertTrue(structured_paid_source("remotive-api","paid_market"))
        self.assertTrue(structured_paid_source("remoteok-api","paid_market"))
        self.assertFalse(structured_paid_source("remotive-api","buyer"))
        self.assertFalse(structured_paid_source("web","paid_market"))

    def test_thesis_attribution_requires_strong_relevance(self):
        observed="spreadsheet_process:general"
        problem_id="ai_tools:small_businesses:produce_recurring_client_and_management_reports"
        self.assertEqual(
            thesis_attributed_problem_key(observed,problem_id,"th-123",54,2),
            observed,
        )
        self.assertEqual(
            thesis_attributed_problem_key(observed,problem_id,"th-123",80,1),
            observed,
        )

    def test_thesis_attribution_uses_concrete_problem_id_when_strong(self):
        observed="spreadsheet_process:general"
        problem_id="ai_tools:small_businesses:produce_recurring_client_and_management_reports"
        self.assertEqual(
            thesis_attributed_problem_key(observed,problem_id,"th-123",55,2),
            problem_id,
        )
        self.assertTrue(gate_eligible_problem_key(problem_id))

    def test_plain_devops_maps_to_developer_tools(self):
        self.assertEqual(commercial_family("Hiring DevOps engineer for deployment automation"),"developer_tools")

    def test_generic_hypothesis_terms_remain_nonqualifying(self):
        self.assertFalse(gate_eligible_problem_key("ai_tools:generic_technology"))
        self.assertEqual(canonical_problem_key("ai_tools","ai_tools:llm"),"ai_tools:generic_technology")

    def test_search_vocabulary_is_not_human_thesis_identity(self):
        # Search aliases are retrieval helpers only; generic technology still cannot qualify.
        self.assertEqual(canonical_problem_key("ai_tools","ai_tools:llm"),"ai_tools:generic_technology")
        self.assertFalse(gate_eligible_problem_key("ai_tools:generic_technology"))


if __name__=="__main__":
    unittest.main()
