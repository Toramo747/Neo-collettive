"""No-network verification of 8-gamete retrospective external HN screening."""
import importlib.util
import json
import unittest
from pathlib import Path

SOURCE = Path("experiments/research-autocorrection-external/compare.py")
spec = importlib.util.spec_from_file_location("research_autocorrection_external", SOURCE)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class AutoCorrectionExternalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.p, cls.candidates, cls.policy = m.read_protocol()
        cls.genes, cls.plans, cls.queries = m.make_plan(cls.p, cls.candidates)

    def test_preregistration_frozen_new_periods(self):
        self.assertEqual([x["id"] for x in self.p["evaluation_windows"]], ["2026-08", "2026-09"])
        self.assertFalse(set(self.p["training_only_months"]) &
                         {w["id"] for w in self.p["evaluation_windows"]})
        self.assertEqual(len(self.p["evaluation_topics"]), 4)
        self.assertEqual(self.p["decision_rule"]["minimum_net_unique_thread_gain"], 2)

    def test_all_eight_and_one_matched_baseline_at_identical_budget(self):
        self.assertEqual(len(self.candidates), 8)
        self.assertEqual(len(self.plans), 9)
        self.assertEqual(len(self.genes), 9)
        self.assertTrue(all(len(rows) == 16 for rows in self.plans.values()))
        self.assertLessEqual(len(self.queries), 144)
        self.assertEqual(self.genes["baseline"]["term_order"], "topic_first")
        self.assertTrue(all(g["query_count"] == 4 and g["source_scope"] == "all"
                            for g in self.genes.values()))

    def test_fixed_history_cannot_be_training_and_validation(self):
        sample = self.candidates[0]
        bad = [{"id": "2026-06"}, {"id": "2026-09"}]
        outcome = m.engine.evaluate_external(sample, bad, self.policy)
        self.assertEqual(outcome["verdict"], "EVALUATION_LEAKAGE_BLOCKED")
        self.assertFalse(outcome["eligible_for_promotion"])

    def test_bad_or_missing_provider_data_is_not_positive(self):
        p = self.p["baseline_genes"]
        pairs = m.build_arm_queries(self.p, p)
        broken = {x["query"]: {"ok": False, "hits": []} for x in pairs}
        measured = m.measure(pairs, broken, p, True)
        self.assertFalse(measured["valid"])
        self.assertEqual(measured["ok"], 0)
        self.assertFalse(m.public_metrics(measured)["valid"])

    def test_no_external_data_is_logged_or_written_in_source(self):
        code = SOURCE.read_text(encoding="utf-8")
        self.assertIn('"human_review": "NOT_PERFORMED"', code)
        self.assertIn('"independent_validated_replications": 0', code)
        self.assertIn('"raw_external_text_or_identifiers_persisted": False', code)
        self.assertNotIn("save_json(STATE_PATH", code)
        self.assertNotIn("trigger_deploy(", code)
        self.assertFalse(self.p["constraints"]["no_runtime_or_arena_state_writes"] is False)
        self.assertTrue(self.p["constraints"]["zero_paid_provider_queries"])

    def test_synthetic_control_is_not_buyer_verification(self):
        control = m.v3.v2.synthetic_controls()
        self.assertTrue(control["pass"])
        self.assertFalse(control["included_in_live_metrics"])


if __name__ == "__main__":
    unittest.main()
