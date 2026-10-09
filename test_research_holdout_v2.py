"""No-network verification of the new independent shadow holdout."""
import importlib.util
import json
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

PATH = Path("experiments/research-holdout-v2/run.py")
spec = importlib.util.spec_from_file_location("oxibay_disjoint_holdout", PATH)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class DisjointResearchHoldoutTests(unittest.TestCase):
    def test_preregistration_and_isolation(self):
        p = m.load_protocol()
        assert len(m.planned_queries(p)["baseline"]) == 16
        assert len(m.planned_queries(p)["treatment"]) == 16
        self.assertFalse(p["boundary"]["production_state_write"])
        self.assertFalse(p["boundary"]["automatic_promotion"])
        self.assertFalse(p["boundary"]["paid_api_calls"])
        self.assertFalse(p["boundary"]["raw_external_text_persisted"])
        self.assertEqual("NONE", p["boundary"]["commercial_gate_influence"])
        prior = m.prior.load_protocol()
        self.assertFalse({t["full"] for t in p["holdout_topics"]} &
                         {t["full"] for t in prior["holdout_topics"]})
        self.assertEqual(p["decision_rule"]["required_independent_rounds_before_validation"], 3)

    def test_synthetic_controls_are_separate_and_pass(self):
        c = m.synthetic_controls()
        self.assertTrue(c["pass"], c)
        self.assertEqual(c["positive_observed"], 1)
        self.assertEqual(c["negative_observed"], 0)
        self.assertFalse(c["included_in_live_metrics"])
        self.assertEqual(c["fixture_type"], "AUTHOR_LABELLED_SYNTHETIC_ONLY")

    def test_duplicate_receipt_is_not_twice_a_signal(self):
        pairs = [{"topic": "manual data entry", "query": "manual data entry workaround"}] * 2
        hit = {"objectID": "object-1", "story_id": "thread-1", "comment_text": m.POSITIVE_TEXT}
        g = m.load_protocol()["baseline_definition"]
        stats = m.diagnostic_metrics(pairs, [[hit], [hit]], g)
        self.assertEqual(stats["score"]["deduped_object_count"], 1)
        self.assertEqual(sum(stats["stages"].values()), 1)
        self.assertEqual(stats["stages"]["valid_signal"], 1)

    def test_valid_query_calls_without_signals_cannot_pass(self):
        a = {"score": {"unique_signal_threads": 0, "precision": 0, "topic_coverage": 0}}
        b = {"score": {"unique_signal_threads": 0, "precision": 0, "topic_coverage": 0}}
        rule = m.load_protocol()["decision_rule"]
        self.assertEqual(m.verdict(a, b, True, True, rule), "NO_DEMONSTRATED_GAIN")
        self.assertEqual(m.verdict(a, b, True, False, rule), "INCONCLUSIVE_PROVIDER_FAILURE")
        self.assertEqual(m.verdict(a, b, False, True, rule), "INVALID_CONTROL")

    def test_never_count_synthetic_cases_as_external_data(self):
        src = PATH.read_text(encoding="utf-8")
        self.assertIn("controls = synthetic_controls()", src)
        self.assertIn('"human_verified_external_labels": False', src)
        self.assertIn('"automatic_promotion": False', src)
        self.assertIn('"production_state_write": False', src)
        self.assertNotIn("replace_evidence_memory(", src)
        self.assertNotIn("trigger_deploy(", src)


if __name__ == "__main__":
    unittest.main()
