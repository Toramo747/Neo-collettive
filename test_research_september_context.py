"""No-network tests of shadow context routing and aggregate accounting."""
import importlib.util
import json
import unittest
from pathlib import Path

SRC=Path("experiments/research-september-context/check.py")
spec=importlib.util.spec_from_file_location("oxibay_sep_context",SRC)
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

class SeptemberContextTests(unittest.TestCase):
    def setUp(self):
        self.p=m.load()

    def test_predeclared_three_contexts_and_boundary(self):
        self.assertEqual(self.p["period"]["name"],"2026-09")
        self.assertEqual(len(self.p["contexts"]),3)
        self.assertEqual(self.p["query_budget"]["max_total_provider_requests"],5)
        self.assertFalse(self.p["boundary"]["production_write"])
        self.assertFalse(self.p["boundary"]["automatic_promotion"])
        self.assertEqual(self.p["shadow_parameter"]["policy"],"REVIEW_ONLY_NEVER_AUTO_REJECT")

    def test_job_seeker_and_hiring_remain_review_flags_not_rejections(self):
        self.assertEqual(m.route("applicant_offers",family=True,buyer=True,vendor_or_supply=False),
                         "REVIEW_JOB_SEEKER_OFFER_CONTEXT")
        self.assertEqual(m.route("employer_job_posts",family=True,buyer=True,vendor_or_supply=False),
                         "REVIEW_JOB_POSTING_NOT_SOFTWARE_DEMAND")
        self.assertEqual(m.route("applicant_offers",family=False,buyer=False,vendor_or_supply=True),
                         "NO_HEURISTIC_OVERLAP")

    def test_showcase_with_real_unmet_need_is_not_suppressed(self):
        self.assertEqual(m.route("show_hn_projects",family=True,buyer=True,vendor_or_supply=False),
                         "REVIEW_MIXED_SHOWCASE_CONTEXT")
        self.assertEqual(m.route("show_hn_projects",family=False,buyer=True,vendor_or_supply=False),
                         "NO_HEURISTIC_OVERLAP")
        with self.assertRaises(ValueError):
            m.route("nonexistent",family=True,buyer=True,vendor_or_supply=False)

    def test_no_raw_records_in_output(self):
        sample=[
            {"objectID":"fixture1","title":"I need a spreadsheet tool for repetitive manual work",
             "story_text":"Trying to automate invoice reconciliation"},
            {"objectID":"fixture1","title":"duplicate"},
            {"objectID":"fixture2","title":"Show HN my app","story_text":"We built our tool last week"}]
        out=m.aggregate("show_hn_projects",sample,self.p)
        self.assertEqual(out["examined"],2)
        self.assertEqual(set(out),set(m.AGGREGATE_FIELDS))
        self.assertNotIn("spreadsheet",json.dumps(out))
        self.assertLessEqual(out["buyer_family_overlap"],out["buyer_voice_heuristic"])
        self.assertLessEqual(out["source_context_review_flags"],out["examined"])

    def test_empty_results_are_not_success(self):
        out=m.aggregate("applicant_offers",[],self.p)
        self.assertEqual(out["examined"],0)
        self.assertTrue(m.load()["required_controls"]["unknown_provider_or_missing_story_inconclusive"])

    def test_code_never_modifies_classifier_or_production(self):
        s=SRC.read_text(encoding="utf-8")
        self.assertNotIn("replace_evidence_memory(",s)
        self.assertNotIn("trigger_deploy(",s)
        self.assertNotIn("save_json(STATE_PATH",s)
        self.assertIn('"classifier_predictions_modified":False',s)

if __name__=="__main__":
    unittest.main()
