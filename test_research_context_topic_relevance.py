"""Frozen topics versus contextual source records; pure synthetic and no network."""
import importlib.util
import json
import unittest
from pathlib import Path

SRC=Path("experiments/research-context-topic-relevance/check.py")
s=importlib.util.spec_from_file_location("oxibay_topic_relevance",SRC)
m=importlib.util.module_from_spec(s)
s.loader.exec_module(m)

class TopicRelevanceTests(unittest.TestCase):
    def setUp(self):
        self.p,self.old=m.load()

    def test_unchanged_legacy_frozen_topic_genome(self):
        self.assertEqual(len(self.p["topics"]),4)
        self.assertEqual(self.p["frozen_baseline"]["min_relevance_tokens"],1)
        self.assertEqual(self.p["max_public_requests"],5)
        self.assertEqual(self.p["max_records_per_context"],60)
        self.assertFalse(self.p["boundaries"]["source_context_used_to_change_label"])
        self.assertFalse(self.p["boundaries"]["production_write"])

    def test_untargeted_positive_body_rejected_by_relevance(self):
        # Legacy content-only positive but not any frozen benchmark domain.
        unrelated={"objectID":"fake1","story_id":"fake-story-1",
            "comment_text":"I need a tool for manual data entry because this workaround wastes time"}
        outcome=m.summarize_context("applicant_offers",[unrelated],self.p)
        self.assertEqual(outcome["records_examined"],1)
        self.assertEqual(outcome["content_only_positive_records"],1)
        self.assertEqual(outcome["topic_record_positive_evaluations"],0)
        for rec in outcome["by_domain"].values():
            self.assertEqual(rec["topic_content_positive_rows"],0)
            self.assertEqual(rec["rejection_irrelevant"],1)

    def test_targeted_examples_are_not_context_vetoed(self):
        hit={"objectID":"fake2","story_id":"fake-story-2",
            "comment_text":"I need a tool for restaurant booking manual data entry because this workaround wastes time"}
        for context in self.p["contexts"]:
            outcome=m.summarize_context(context,[hit],self.p)
            self.assertEqual(outcome["content_only_positive_records"],1)
            self.assertEqual(outcome["by_domain"]["hospitality"]["topic_content_positive_rows"],1)
            self.assertEqual(outcome["legacy_decision_changes"],0)

    def test_deduplication_and_privacy(self):
        hit={"objectID":"same","story_id":"synthetic-thread",
            "comment_text":"I need a tool for inventory alert manual data entry because this workaround wastes time"}
        summary=m.summarize_context("show_hn_projects",[hit,hit],self.p)
        self.assertEqual(summary["records_examined"],1)
        self.assertNotIn("same",json.dumps(summary))
        self.assertTrue(all(rec["stage_integrity"] for rec in summary["by_domain"].values()))
        self.assertGreaterEqual(summary["buyer_family_overlaps"],summary["content_only_positive_records"])

    def test_budget_and_nonpromotion(self):
        self.assertEqual(self.p["comparison_type"],
            "fixed_source_corpus_with_counterfactual_topic_relevance_not_end_to_end_retrieval")
        self.assertFalse(self.p["boundaries"]["automatic_promotion"])
        self.assertEqual(self.p["boundaries"]["human_labels"],0)
        self.assertEqual(self.p["boundaries"]["commercial_gate_influence"],"NONE")
        src=SRC.read_text()
        self.assertNotIn("trigger_deploy(",src)
        self.assertNotIn("replace_evidence_memory(",src)

if __name__=="__main__":
    unittest.main()
