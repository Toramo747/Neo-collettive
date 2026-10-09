"""Tests without network or private data for preregistered temporal search holdout."""
import importlib.util
import unittest
from pathlib import Path

path = Path("experiments/research-temporal-holdout/run.py")
spec = importlib.util.spec_from_file_location("oxibay_temporal", path)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def fixture(score_signals, threads, relevant, precision, topics, stage_valid=None, ok=16):
    if stage_valid is None:
        stage_valid = score_signals
    return {
        "ok": ok,
        "score": {
            "score": {"signal_hits": score_signals, "unique_signal_threads": threads,
                      "deduped_object_count": 20, "topic_coverage": topics,
                      "relevant_hits": relevant, "precision": precision},
            "stages": {"valid_signal": stage_valid, "irrelevant": 20-stage_valid}
        }
    }


class TemporalHoldoutTests(unittest.TestCase):
    def test_preregistered_windows_genes_and_boundaries(self):
        p = m.load()
        q = m.plan(p)
        self.assertEqual(len(p["temporal_windows"]), 3)
        self.assertEqual(len(p["topics"]), 4)
        self.assertEqual(set(q), {"compact_matched", "evolved_g69"})
        self.assertEqual(len(q["compact_matched"]), 16)
        self.assertEqual(len(q["evolved_g69"]), 16)
        self.assertFalse(p["constraints"]["paid_api_calls"])
        self.assertFalse(p["constraints"]["automatic_promotion"])
        self.assertFalse(p["constraints"]["production_state_write"])
        self.assertFalse(p["constraints"]["human_verified"])

    def test_signal_threshold_and_precision(self):
        p = m.load()
        a = fixture(1, 1, 20, .05, 1)
        b = fixture(3, 3, 20, .15, 2)
        self.assertEqual(m.decide(a, b, p, True), "TEMPORAL_CANDIDATE_NOT_VALIDATED")
        b["score"]["score"]["precision"] = .01
        self.assertEqual(m.decide(a, b, p, True), "NO_DEMONSTRATED_GAIN")
        a["score"]["score"]["relevant_hits"] = 7
        self.assertEqual(m.decide(a, b, p, True), "INCONCLUSIVE_WEAK_BASELINE")

    def test_fail_closed_inconsistent_metrics(self):
        p=m.load()
        a = fixture(1, 1, 20, .05, 1)
        b = fixture(3, 3, 20, .15, 2, stage_valid=4)
        self.assertEqual(m.decide(a,b,p,True),"INCONCLUSIVE_METRIC_DISAGREEMENT")
        self.assertEqual(m.decide(a,b,p,False),"INVALID_SYNTHETIC_CONTROLS")
        a["ok"]=15
        b=fixture(3,3,20,.15,2)
        self.assertEqual(m.decide(a,b,p,True),"INCONCLUSIVE_PROVIDER_FAILURE")

    def test_no_case_data_artifacts_or_production_writes(self):
        code=path.read_text(encoding="utf-8")
        self.assertIn('"validated_independent_replications": 0', code)
        self.assertIn('"cross_source_validation": False',code)
        self.assertIn('"human_verified": False',code)
        self.assertIn('"raw_external_text_persisted": False',code)
        self.assertNotIn("trigger_deploy(",code)
        self.assertNotIn("replace_evidence_memory(",code)

    def test_existing_synthetic_controls_pass(self):
        result=m.v3.v2.synthetic_controls()
        self.assertTrue(result["pass"])
        self.assertFalse(result["included_in_live_metrics"])


if __name__ == "__main__":
    unittest.main()
