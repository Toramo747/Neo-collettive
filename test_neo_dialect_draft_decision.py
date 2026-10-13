import pathlib
import unittest

class NeoDialectDraftDecisionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text=pathlib.Path("docs/neo-dialect/1.1-draft-decision.md").read_text(encoding="utf-8")

    def test_no_draft_decision_is_explicit(self):
        self.assertIn("NO_DRAFT_NEEDED",self.text)
        self.assertIn("0 numbered RFCs",self.text)

    def test_future_draft_requires_approved_rfc(self):
        self.assertIn("at least one numbered RFC",self.text)
        self.assertIn("recurring DIALECT evidence",self.text)
        self.assertIn("no equivalent A2A primitive",self.text)

    def test_production_1_0_is_protected(self):
        for phrase in (
            "docs/neo-dialect.md",
            "schemas/neo-dialect/1.0/**",
            "neo_dialect.py",
            "/neo-dialect/1.0",
        ):
            self.assertIn(phrase,self.text)

    def test_ab_is_blocked_without_semantic_delta(self):
        self.assertIn("not meaningful yet",self.text)
        self.assertIn("no accepted semantic delta",self.text)

if __name__=="__main__":
    unittest.main()
