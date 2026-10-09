import json
import unittest
from pathlib import Path
from importlib.util import spec_from_file_location, module_from_spec
from unittest.mock import patch

P=Path("experiments/research-holdout/compare.py")
spec=spec_from_file_location("research_holdout_compare",P)
m=module_from_spec(spec)
spec.loader.exec_module(m)

class IndependentResearchHoldoutTests(unittest.TestCase):
    def test_preregistered_equal_budget_and_fresh_topics(self):
        protocol=m.load_protocol()
        report=json.loads(Path("data/arena/research-algorithm/latest.json").read_text())
        plans=m.plans(protocol,report["ranked"][0]["genes"])
        self.assertEqual(len(plans["baseline"]),len(plans["treatment"]))
        self.assertEqual(len(plans["baseline"]),16)
        originals=set(report["benchmark"]["topics"])
        self.assertFalse(originals & {x["full"] for x in protocol["holdout_topics"]})
    def test_refuse_genome_drift(self):
        p=m.load_protocol()
        with self.assertRaises(ValueError):
            m.plans(p,{"query_mode":"pain"})
    def test_isolation_and_no_production_writes(self):
        p=m.load_protocol()
        self.assertFalse(p["decision_rule"]["promote_to_production"])
        self.assertFalse(p["boundary"]["production_state_write"])
        self.assertFalse(p["boundary"]["raw_external_text_persisted"])
        self.assertEqual("NONE",p["boundary"]["commercial_gate_influence"])
    def test_deduplicate_same_object_across_queries(self):
        g=m.load_protocol()["baseline_definition"]
        q=[{"topic":"contract renewal tracking","query":"contract renewal tracking manual"}]*2
        hit={"objectID":"111","story_id":"111","comment_text":"We spend hours on contract renewal tracking and need help"}
        rows=m.valid_thread_metrics(q,[[hit],[hit]],g)
        self.assertEqual(1,rows["deduped_object_count"])

if __name__=="__main__":
    unittest.main()
