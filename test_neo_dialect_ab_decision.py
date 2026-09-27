import pathlib
import unittest

class NeoDialectABDecisionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text=pathlib.Path("docs/neo-dialect/ab-decision.md").read_text(encoding="utf-8")

    def test_blocked_status_is_explicit(self):
        self.assertIn("BLOCKED / NOT_MEANINGFUL_YET",self.text)
        self.assertIn("Do not run the A/B experiment now",self.text)

    def test_no_fake_semantic_delta(self):
        self.assertIn("no semantic delta",self.text)
        self.assertIn("stochastic model/runtime variation",self.text)

    def test_activation_gate_requires_real_rfc_and_draft(self):
        self.assertIn("at least one numbered RFC",self.text)
        self.assertIn("Andrea explicitly approves",self.text)
        self.assertIn("neo-dialect/1.1-draft",self.text)
        self.assertIn("falsifiable hypothesis",self.text)

    def test_metrics_are_preserved_for_future_run(self):
        for phrase in (
            "valid_message_rate",
            "fallback_rate",
            "loop_count",
            "turns_to_agreement",
            "result_completion_rate",
            "bye_completion_rate",
            "injection_blocks",
            "protocol_specific_failures",
        ):
            self.assertIn(phrase,self.text)

    def test_zero_cost_arena_boundary_is_explicit(self):
        for phrase in ("zero-cost","Arena-only","score weight 0.0","no external contact","no production influence"):
            self.assertIn(phrase,self.text)

if __name__=="__main__":
    unittest.main()
