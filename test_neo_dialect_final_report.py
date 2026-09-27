import json
import pathlib
import unittest

class NeoDialectFinalReportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report=json.loads(pathlib.Path("data/arena/neo-dialect-evolution-report.json").read_text(encoding="utf-8"))
        cls.doc=pathlib.Path("docs/neo-dialect/evolution-report.md").read_text(encoding="utf-8")
        cls.cloud=pathlib.Path("cloud_mcp.py").read_text(encoding="utf-8")

    def test_report_matches_study_contract(self):
        self.assertEqual(self.report["status"],"FINAL")
        self.assertEqual(self.report["baseline"]["sessions"],12)
        self.assertEqual(self.report["baseline"]["complete_to_bye"],12)
        self.assertEqual(len(self.report["transcripts"]),12)

    def test_no_rfc_is_recommended(self):
        self.assertIsNone(self.report["recommended_rfc"])
        self.assertEqual(self.report["rfc"]["admitted"],0)
        self.assertEqual(self.report["rfc"]["recommended"],0)
        self.assertIn("No RFC is recommended for approval",self.doc)

    def test_constraints_are_preserved(self):
        c=self.report["constraints"]
        self.assertEqual(c["cost_eur"],0)
        self.assertTrue(c["arena_only"])
        self.assertEqual(c["score_weight"],0.0)
        self.assertFalse(c["external_agent_contact"])
        self.assertFalse(c["automatic_promotion"])
        self.assertFalse(self.report["production_spec_changed"])

    def test_transcripts_are_exposed_read_only(self):
        self.assertIn('Route("/arena/neo-dialect", arena_neo_dialect_page, methods=["GET"])',self.cloud)
        self.assertIn("neo-dialect-failure-study.json",self.cloud)
        self.assertIn("Transcript disponibili",self.cloud)
        self.assertNotIn('Route("/arena/neo-dialect", arena_neo_dialect_page, methods=["POST"])',self.cloud)

if __name__=="__main__":
    unittest.main()
