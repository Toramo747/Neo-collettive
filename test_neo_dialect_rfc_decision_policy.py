import pathlib
import unittest

class NeoDialectRFCDecisionPolicyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text=pathlib.Path("docs/neo-dialect/rfc-decision-policy.md").read_text(encoding="utf-8")

    def test_current_zero_rfc_state_is_explicit(self):
        self.assertIn("0 admitted numbered RFCs",self.text)
        self.assertIn("N/A — no RFC admitted",self.text)
        self.assertIn("0 RFC classified. 0 RFC recommended.",self.text)

    def test_three_future_outcomes_are_defined(self):
        for phrase in ("migliora","neutra","peggiora"):
            self.assertIn(phrase,self.text)

    def test_critic_can_veto_metric_improvement(self):
        self.assertIn("independent veto",self.text)
        self.assertIn("even when headline metrics improve",self.text)
        self.assertIn("final status is VETOED",self.text)

    def test_only_non_vetoed_improvement_can_be_recommended(self):
        self.assertIn("only a non-vetoed migliora result may be recommended",self.text)
        self.assertIn("No RFC is automatically promoted",self.text)

    def test_rejected_clarification_candidate_is_not_misclassified(self):
        self.assertIn("REJECTED_BEFORE_RFC",self.text)
        self.assertIn("never became an RFC",self.text)

if __name__=="__main__":
    unittest.main()
