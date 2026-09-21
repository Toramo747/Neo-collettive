import unittest

from evidence_integrity import (
    canonical_problem_key,
    canonical_url,
    commercial_family,
    demand_signal_type,
    gate_eligible_problem_key,
    migrate_evidence_memory,
)


class EvidenceIntegrityTests(unittest.TestCase):
    def test_rate_substring_does_not_create_paid_demand(self):
        tags=demand_signal_type("", "generate accurate integrate operate")
        self.assertNotIn("PAID_DEMAND", tags)

    def test_excel_does_not_match_excellent(self):
        self.assertEqual(commercial_family("excellent customer service"), "other")

    def test_llm_does_not_match_stillman(self):
        self.assertEqual(commercial_family("Stillman workflow problem"), "workflow_automation")

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


if __name__=="__main__":
    unittest.main()
