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

    def test_metric_mismatch_fails_closed(self):
        p=m.load()
        def arm(relevant,signals,threads,valid,buckets):
            stages={"valid_signal":valid, **buckets}
            return {"ok":16,"score":{"score":{"relevant_hits":relevant,"precision":signals/max(1,relevant),
                "signal_hits":signals,"unique_signal_threads":threads,"topic_coverage":2,
                "deduped_object_count":sum(stages.values())},"stages":stages}}
        clean=arm(15,1,1,1,{"irrelevant":14,"no_buyer_voice":12})
        mismatch=arm(18,4,4,5,{"irrelevant":15,"no_buyer_voice":8,"no_demand_tags":5,"unknown_family":2})
        out={"exact_original":clean,"compact_matched":clean,"evolved":mismatch}
        self.assertFalse(m.metric_audit(mismatch)["consistent"])
        self.assertEqual(m.audited_verdict(out,{"pass":True},p),"INCONCLUSIVE_METRIC_DISAGREEMENT")
        fixed=arm(18,4,4,4,{"irrelevant":15,"no_buyer_voice":8,"no_demand_tags":5,"unknown_family":2})
        self.assertTrue(m.metric_audit(fixed)["consistent"])
        out["evolved"]=fixed
        self.assertNotEqual(m.audited_verdict(out,{"pass":True},p),"INCONCLUSIVE_METRIC_DISAGREEMENT")


    def test_long_text_relevance_is_identical_to_scorer(self):
        # Author-made synthetic HN fixture: the topic and demand evidence occur
        # after the composited score_hits 1600-character boundary, but within
        # the individually cleaned 1600-character comment body.
        genes=m.load()["shared_genes"]
        topic="manual data entry"
        title=("Routine operations have become difficult for several departments "
               "and the issue repeats throughout the year")
        body=("ordinary contextual filler " * 56 +
              m.v2.POSITIVE_TEXT)
        self.assertLessEqual(len(body),1600)
        self.assertGreater(len(title+" "+body),1600)
        self.assertNotIn(topic, (title+" "+body)[:1600].lower())
        hit={"objectID":"synthetic-long-1","story_id":"synthetic-long-1",
             "title":title,"comment_text":body}
        measures=m.v2.diagnostic_metrics(
            [{"topic":topic,"query":"manual data entry workaround"}],
            [[hit]],genes)
        self.assertEqual(
            measures["score"]["signal_hits"],
            measures["stages"]["valid_signal"],
            "Diagnostic and production-aligned scorer must classify the same cleaned text")
        self.assertEqual(measures["score"]["signal_hits"], 0)
        self.assertEqual(measures["stages"]["irrelevant"], 1)
