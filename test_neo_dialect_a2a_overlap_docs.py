import pathlib
import unittest

class A2AOverlapDocTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.path=pathlib.Path("docs/neo-dialect/a2a-overlap.md")
        cls.text=cls.path.read_text(encoding="utf-8")

    def test_sources_and_boundary_are_documented(self):
        self.assertIn("a2aproject/A2A/blob/main/docs/specification.md",self.text)
        self.assertIn("a2aproject/A2A/blob/main/specification/a2a.proto",self.text)
        self.assertIn("neo-dialect/1.0 is unchanged",self.text)

    def test_observed_clarification_gap_is_not_promoted_to_rfc(self):
        self.assertIn("clarification_overloaded_into_counter",self.text)
        self.assertIn("must not become a neo-dialect RFC",self.text)
        self.assertIn("TASK_STATE_INPUT_REQUIRED",self.text)

    def test_common_a2a_primitives_are_not_duplicated(self):
        for phrase in (
            "Do not add CLARIFY",
            "Do not add PROGRESS",
            "Do not add CANCEL",
            "Do not add generic ERROR",
            "Artifact + Part",
            "A2A-Version",
        ):
            self.assertIn(phrase,self.text)

    def test_true_dialect_scope_is_negotiation_semantics(self):
        for phrase in ("PROPOSE","COUNTER","AGREE","proposal -> counter -> agreement"):
            self.assertIn(phrase,self.text)
        self.assertIn("neo-dialect 1.0 is sufficient for now",self.text)

if __name__=="__main__":
    unittest.main()
