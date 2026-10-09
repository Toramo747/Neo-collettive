"""No-network tests for one-gene April research query intervention."""
import importlib.util
import json
import unittest
from pathlib import Path

FILE=Path("experiments/research-april-pain-queries/run.py")
spec=importlib.util.spec_from_file_location("oxibay_april_query",FILE)
m=importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

class AprilQueryABTests(unittest.TestCase):
    def setUp(self):
        self.p,self.plan=m.load()

    def test_query_budget_and_only_gene_change(self):
        a=self.plan["legacy_mixed"]
        b=self.plan["candidate_pain"]
        self.assertEqual(len(a["pairs"]),16)
        self.assertEqual(len(b["pairs"]),16)
        self.assertEqual([k for k in a["genes"] if a["genes"][k]!=b["genes"][k]],["query_mode"])
        self.assertEqual(a["genes"]["query_mode"],"mixed")
        self.assertEqual(b["genes"]["query_mode"],"pain")
        self.assertEqual(self.p["window"]["id"],"2026-04")
        self.assertLessEqual(len({x["query"] for arm in self.plan.values() for x in arm["pairs"]}),32)

    def test_existing_positive_from_job_thread_is_not_removed(self):
        a=self.plan["legacy_mixed"]
        pos={"objectID":"fixture1","story_id":"fixture-thread",
             "story_title":"Ask HN: Who wants to be hired? (April 2026)",
             "comment_text":"I need a tool for restaurant booking manual data entry because this workaround wastes time"}
        batch=[[] for _ in a["pairs"]]
        batch[0]=[pos,pos]
        summary=m.shadow_review_stats(a["pairs"],batch,a["genes"],self.p)
        self.assertEqual(summary["accepted_records"],1)
        self.assertEqual(summary["context_flagged_accepted_records"],1)
        self.assertEqual(summary["context_first_top_slots_known_source_count"],1)
        self.assertTrue(summary["all_existing_accept_decisions_preserved"])

    def test_nonbuyer_not_silently_promoted(self):
        a=self.plan["legacy_mixed"]
        bad={"objectID":"fixture2","story_title":"Show HN: Tech demonstration",
             "comment_text":"A new feature release was announced"}
        batches=[[] for _ in a["pairs"]]
        batches[0]=[bad]
        summary=m.shadow_review_stats(a["pairs"],batches,a["genes"],self.p)
        self.assertEqual(summary["accepted_records"],0)
        self.assertEqual(summary["context_flagged_accepted_records"],0)

    def test_context_only_changes_review_order(self):
        a=self.plan["legacy_mixed"]
        b=[[] for _ in a["pairs"]]
        body="I need a tool for restaurant booking manual data entry because this workaround wastes time"
        b[0]=[{"objectID":f"fx-{i}","story_id":f"fx-thread-{i}",
                "story_title":"Normal discussion" if i<8 else "Ask HN: Who is hiring? (April 2026)",
                "comment_text":body} for i in range(12)]
        result=m.shadow_review_stats(a["pairs"],b,a["genes"],self.p)
        self.assertEqual(result["accepted_records"],12)
        self.assertEqual(result["baseline_top_slots_known_source_count"],0)
        self.assertEqual(result["context_first_top_slots_known_source_count"],4)
        self.assertEqual(result["baseline_review_slots_used"],8)
        self.assertEqual(result["context_first_review_slots_used"],8)

    def test_decision_fails_closed_and_never_promotes(self):
        def arm(ok,relevant,threads,coverage,precision):
            return {"queries_ok":ok,"relevant_hits":relevant,
                    "unique_signal_threads":threads,"topic_coverage":coverage,
                    "precision":precision}
        a=arm(16,20,1,2,.05)
        b=arm(16,20,4,2,.2)
        self.assertEqual(m.decide(self.p,{"legacy_mixed":a,"candidate_pain":b}),
                         "SCREEN_CANDIDATE_NOT_VALIDATED")
        a["queries_ok"]=15
        self.assertEqual(m.decide(self.p,{"legacy_mixed":a,"candidate_pain":b}),
                         "INCONCLUSIVE_PROVIDER_FAILURE")
        a["queries_ok"]=16
        a["relevant_hits"]=3
        self.assertEqual(m.decide(self.p,{"legacy_mixed":a,"candidate_pain":b}),
                         "INCONCLUSIVE_WEAK_BASELINE")
        self.assertFalse(self.p["decision_rule"]["automatic_promotion"])

    def test_no_data_leaks_or_paid_tools(self):
        for key in ("raw_external_text_persisted","source_urls_persisted",
                    "source_ids_persisted","query_strings_persisted","automatic_promotion","paid_api_calls",
                    "production_state_write","human_verified"):
            self.assertFalse(self.p["safety"][key])
        text=FILE.read_text(encoding="utf-8")
        self.assertNotIn("trigger_deploy(",text)
        self.assertNotIn("replace_evidence_memory(",text)
        self.assertNotIn("train_student(",text)

if __name__=="__main__":
    unittest.main()
