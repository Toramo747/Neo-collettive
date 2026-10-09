"""No-network, no-production tests for the bounded self-correction gametes."""
import importlib.util
import json
import unittest
from pathlib import Path

SRC = Path("experiments/research-autocorrection/engine.py")
spec = importlib.util.spec_from_file_location("oxibay_autocorrection", SRC)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class AutoCorrectionTests(unittest.TestCase):
    def setUp(self):
        self.p = m.load_policy()
        self.feedback = m.load_training(self.p)
        self.candidates = m.propose(self.p, self.feedback)

    def test_real_negative_feedback_not_relabelled_as_success(self):
        priority, counts = m.rejection_priority(self.feedback)
        self.assertEqual(priority[0], "no_buyer_voice")
        self.assertEqual(counts["no_buyer_voice"], 17)
        self.assertEqual(counts["irrelevant"], 16)
        self.assertEqual(counts["unknown_family"], 13)
        for window in self.feedback["windows"]:
            self.assertEqual(window["arms"]["evolved_g69"]["unique_signal_threads"],
                             window["arms"]["compact_matched"]["unique_signal_threads"])

    def test_eight_distinct_bounded_real_search_genomes(self):
        self.assertEqual(len(self.candidates), 8)
        self.assertEqual(len({x["id"] for x in self.candidates}), 8)
        signatures = {json.dumps(x["search_genes"], sort_keys=True) for x in self.candidates}
        self.assertEqual(len(signatures), 8)
        for candidate in self.candidates:
            self.assertEqual(len(m.build_queries(candidate["search_genes"])), 16)
            self.assertEqual(candidate["search_genes"]["source_scope"], "all")
            self.assertIsNone(candidate["external_score"])
            self.assertFalse(candidate["validated"])
            self.assertFalse(candidate["eligible_for_promotion"])
            self.assertTrue(0.1 <= candidate["knobs"]["exploration_rate"] <= 0.5)
            self.assertTrue(0 <= candidate["knobs"]["novelty_penalty"] <= 0.4)
            self.assertTrue(0 <= candidate["knobs"]["temporal_robustness"] <= 0.5)

    def test_training_window_leakage_is_fail_closed(self):
        c = self.candidates[0]
        self.assertEqual(m.evaluate_external(c, [
            {"id": "2026-06"}, {"id": "2026-11"}
        ], self.p)["verdict"], "EVALUATION_LEAKAGE_BLOCKED")

    def test_heldout_synthetic_examples_do_not_authorize_promotion(self):
        c = self.candidates[0]
        def arm(threads, relevant, precision, duplicate):
            return {"queries_ok":16, "metric_integrity":True,
                    "synthetic_controls_pass":True,"relevant_hits":relevant,
                    "unique_signal_threads":threads,"topic_coverage":2,
                    "precision":precision,"duplicate_ratio":duplicate}
        windows = [
            {"id":"synthetic-unseen-1","matched":arm(1,18,0.0556,0.1),
             "candidate":arm(4,20,0.20,0.1)},
            {"id":"synthetic-unseen-2","matched":arm(0,20,0.0,0.1),
             "candidate":arm(3,22,0.1364,0.1)},
        ]
        result=m.evaluate_external(c,windows,self.p)
        self.assertEqual(result["verdict"],"SHADOW_REVIEW_CANDIDATE_NOT_VALIDATED")
        self.assertEqual(result["independent_replications"],0)
        self.assertFalse(result["eligible_for_promotion"])
        windows[1]["candidate"]["unique_signal_threads"]=0
        self.assertEqual(m.evaluate_external(c,windows,self.p)["verdict"],"NO_REPRODUCIBLE_GAIN")

    def test_invalid_integrity_is_not_a_result(self):
        c=self.candidates[0]
        invalid={"id":"synthetic-new","matched":{"queries_ok":16},
                 "candidate":{"queries_ok":16}}
        result=m.evaluate_external(c,[invalid,{**invalid,"id":"synthetic-new-2"}],self.p)
        self.assertEqual(result["verdict"],"INVALID_OR_INCOMPLETE_EVALUATION")

    def test_shadow_contract_contains_no_side_effects(self):
        safety=self.p["safety"]
        self.assertTrue(safety["shadow_only"])
        self.assertFalse(safety["production_state_write"])
        self.assertFalse(safety["automatic_promotion"])
        self.assertFalse(safety["commercial_policy_mutation"])
        self.assertEqual(safety["commercial_gate_influence"],"NONE")
        source=SRC.read_text(encoding="utf-8")
        self.assertNotIn("requests.get(",source)
        self.assertNotIn("httpx.",source)
        self.assertNotIn("trigger_deploy(",source)
        self.assertNotIn("save_json(STATE_PATH",source)


if __name__ == "__main__":
    unittest.main()
