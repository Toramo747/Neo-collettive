import tempfile
import unittest
from pathlib import Path
import json
import arena_warp_propulsion as arena

class WarpArenaTests(unittest.TestCase):
    def test_baselines_score(self):
        scores=[arena.score_candidate(c) for c in arena.baseline_candidates()]
        self.assertEqual(len(scores),4)
        self.assertTrue(all(0.0 <= x["fitness"] <= 1.0 for x in scores))
        self.assertTrue(all(x["status"]=="THEORETICAL_ONLY" for x in scores))

    def test_superluminal_is_flagged(self):
        c=arena.Candidate("alcubierre_like",0.2,1.0,1.2,0.2,0.1)
        s=arena.score_candidate(c)
        self.assertIn("SUPERLUMINAL_CAUSALITY_UNRESOLVED",s["hard_flags"])

    def test_generation_is_isolated(self):
        state,report=arena.run_generation({},32,42)
        self.assertFalse(state["production_promoted"])
        self.assertEqual(report["boundary"]["production_runtime_influence"],"NONE")
        self.assertEqual(report["boundary"]["promotion"],"HUMAN_SCIENTIFIC_REVIEW_ONLY")
        self.assertEqual(report["population"],32)

if __name__=="__main__":
    unittest.main()
