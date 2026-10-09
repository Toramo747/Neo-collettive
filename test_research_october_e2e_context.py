"""Synthetic control suite; no actual HN/network requests in tests."""
import importlib.util
import unittest
from pathlib import Path

SRC=Path("experiments/research-october-e2e-context/run.py")
spec=importlib.util.spec_from_file_location("oxibay_october_e2e",SRC)
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

class OctoberMatchedContextTests(unittest.TestCase):
    def setUp(self):
        self.p,self.pairs=m.load()

    def test_plan_frozen_queries(self):
        self.assertEqual(len(self.pairs),16)
        self.assertEqual(len(set(x["query"] for x in self.pairs)),16)
        self.assertEqual(self.p["source_window"]["id"],"2026-10-01_to_2026-10-09_utc_exclusive")
        self.assertFalse(self.p["safety"]["production_write"])
        self.assertFalse(self.p["safety"]["automatic_promotion"])
        self.assertEqual(self.p["decision_contract"]["expected_score_difference"],0)

    def test_source_context_is_from_story_only(self):
        self.assertEqual(m.context_for({"story_title":"Ask HN: Who is hiring? (October 2026)"}),"employer_job_posts")
        self.assertEqual(m.context_for({"story_title":"Ask HN: Who wants to be hired? (October 2026)"}),"applicant_offers")
        self.assertEqual(m.context_for({"story_title":"Show HN: My PDF tool"}),"show_hn_projects")
        self.assertEqual(m.context_for({"story_title":"Random question","comment_text":"Show HN: please help"}),"other_or_unknown")

    def test_identical_baseline_shadow_all_legacy_decisions_unchanged(self):
        example={"objectID":"synthetic-1","story_id":"synthetic-story","story_title":"Ask HN: Who wants to be hired? (October 2026)",
                 "comment_text":"I need a tool for manual data entry because this workaround wastes time"}
        batches=[[] for _ in self.pairs]
        # The fixture is positive for content, but not necessarily relevance.
        batches[0]=[example,example]
        result=m.evaluate(self.pairs,batches,self.p["fixed_baseline"])
        self.assertEqual(result["deduplicated_objects"],1)
        self.assertTrue(result["baseline_and_shadow_equal_scores"])
        self.assertTrue(result["baseline_and_shadow_equal_labels"])
        self.assertEqual(result["delta_unique_threads"],0)
        self.assertEqual(result["delta_precision"],0)
        self.assertEqual(sum(result["baseline_stage_counts"].values()),1)

    def test_negative_source_flags_cannot_change_a_positive(self):
        fake={"objectID":"synthetic-2","story_id":"synthetic-story-2","story_title":"Ask HN: Who wants to be hired? (October 2026)",
              "comment_text":"I need a tool for restaurant booking manual data entry because this workaround wastes time"}
        batch=[[] for _ in self.pairs]
        batch[0]=[fake]
        result=m.evaluate(self.pairs,batch,self.p["fixed_baseline"])
        # A source-context note is not an automatic rejection.
        self.assertEqual(result["signal_hits"],1)
        self.assertEqual(result["review_queue_positive_records"],1)
        self.assertEqual(result["context"]["applicant_offers"]["valid_signal"],1)
        self.assertEqual(result["delta_unique_threads"],0)

    def test_unknown_context_never_forces_negative(self):
        fake={"objectID":"synthetic-3","story_id":"synthetic-story-3","story_title":"Ordinary discussion",
              "comment_text":"I need a tool for restaurant booking manual data entry because this workaround wastes time"}
        batch=[[] for _ in self.pairs]
        batch[0]=[fake]
        result=m.evaluate(self.pairs,batch,self.p["fixed_baseline"])
        self.assertEqual(result["signal_hits"],1)
        self.assertEqual(result["review_queue_positive_records"],0)
        self.assertEqual(result["context"]["other_or_unknown"]["valid_signal"],1)

    def test_full_exact_guard_accounting_and_query_caps(self):
        data=[[] for _ in self.pairs]
        data[0]=[
          {"objectID":"s1","story_id":"t1","story_title":"Show HN: Restaurant tool",
           "comment_text":"A product release note was published"},
          {"objectID":"s2","story_id":"t2","story_title":"Another",
           "comment_text":"I need a tool for restaurant booking manual data entry because this workaround wastes time"}
        ]
        result=m.evaluate(self.pairs,data,self.p["fixed_baseline"])
        self.assertEqual(result["deduplicated_objects"],2)
        self.assertEqual(result["signal_hits"],1)
        self.assertTrue(result["metric_integrity"])
        self.assertLessEqual(result["review_queue_positive_records"],result["signal_hits"])
        self.assertEqual(result["context"]["show_hn_projects"]["examined"],1)
        data[0]=[{"objectID":str(i)} for i in range(31)]
        with self.assertRaises(ValueError):m.evaluate(self.pairs,data,self.p["fixed_baseline"])

    def test_user_constraints(self):
        for v in ("raw_source_content_persisted","source_ids_persisted","source_urls_persisted",
                  "paid_api_calls","human_reviewed","automatic_promotion"):
            self.assertFalse(self.p["safety"][v])
        src=SRC.read_text(encoding="utf-8")
        self.assertNotIn("trigger_deploy(",src)
        self.assertNotIn("replace_evidence_memory(",src)
        self.assertNotIn("train_student(",src)

if __name__=="__main__":
    unittest.main()
