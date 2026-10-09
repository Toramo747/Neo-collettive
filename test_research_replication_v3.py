import importlib.util
import unittest
from pathlib import Path
path=Path("experiments/research-replication-v3/replicate.py")
s=importlib.util.spec_from_file_location("replication_v3",path)
m=importlib.util.module_from_spec(s)
s.loader.exec_module(m)

class ResearchReplicationV3Tests(unittest.TestCase):
    def test_prereg_and_no_leakage(self):
        p=m.load();plans=m.plans(p)
        self.assertEqual(set(plans),{"A","B"})
        for group in plans.values():
            self.assertEqual(set(group),{"exact_original","compact_matched","evolved"})
            self.assertTrue(all(len(v["rows"])==16 for v in group.values()))
        self.assertFalse(p["boundary"]["production_state_write"])
        self.assertFalse(p["boundary"]["automatic_promotion"])
        self.assertFalse(p["boundary"]["paid_api_calls"])

    def test_synthetic_control(self):
        c=m.v2.synthetic_controls()
        self.assertTrue(c["pass"])
        self.assertFalse(c["included_in_live_metrics"])

    def test_primary_matched_comparison_refuses_weak_control(self):
        p=m.load()
        def mtr(hits,threads,precision,topics,ok=16):
            return {"ok":ok,"score":{"score":{"relevant_hits":hits,"unique_signal_threads":threads,
                       "precision":precision,"topic_coverage":topics}}}
        self.assertEqual(m.verdict(mtr(1,0,0,0),mtr(30,3,.1,2),p),
                         "INCONCLUSIVE_WEAK_MATCHED_BASELINE")
        self.assertEqual(m.verdict(mtr(20,0,0,0),mtr(25,0,0,0),p),
                         "NO_GAIN_VS_MATCHED_BASELINE")
        self.assertEqual(m.verdict(mtr(20,0,0,0),mtr(25,3,.12,2),p),
                         "CANDIDATE_NOT_VALIDATED")
        self.assertEqual(m.verdict(mtr(20,0,0,0,15),mtr(25,3,.12,2),p),
                         "INCONCLUSIVE_PROVIDER_FAILURE")

    def test_privacy_and_no_runtime_mutation(self):
        code=path.read_text(encoding="utf-8")
        self.assertNotIn("replace_evidence_memory(",code)
        self.assertNotIn("trigger_deploy(",code)
        self.assertIn('"validated_independent_rounds":0',code)
        self.assertIn('"human_verified":False',code)
        self.assertIn('"automatic_promotion":False',code)
