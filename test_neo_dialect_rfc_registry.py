import pathlib
import re
import unittest

class NeoDialectRFCRegistryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root=pathlib.Path("docs/neo-dialect/rfc")
        cls.text=(cls.root/"README.md").read_text(encoding="utf-8")

    def test_no_numbered_rfc_exists_without_eligible_gap(self):
        numbered=[
            p for p in self.root.glob("*.md")
            if p.name!="README.md" and re.match(r"^\d{3}-",p.name)
        ]
        self.assertEqual(numbered,[])

    def test_recurring_clarification_candidate_is_screened_out(self):
        self.assertIn("clarification_overloaded_into_counter",self.text)
        self.assertIn("**NO RFC**",self.text)
        self.assertIn("TASK_STATE_INPUT_REQUIRED",self.text)

    def test_model_failures_are_not_rfc_inputs(self):
        for phrase in (
            "conversation_id_mismatch",
            "non-JSON",
            "glossary drift",
            "model-generation",
        ):
            self.assertIn(phrase,self.text)

    def test_required_rfc_fields_are_declared(self):
        for phrase in (
            "observed problem and evidence counts",
            "JSON schema",
            "neo-dialect/1.0 compatibility impact",
            "security risks",
            "Critic objections",
        ):
            self.assertIn(phrase,self.text)

    def test_zero_rfc_conclusion_is_explicit(self):
        self.assertIn("0 eligible RFCs",self.text)
        self.assertIn("neo-dialect 1.0 is sufficient for now",self.text)

if __name__=="__main__":
    unittest.main()
