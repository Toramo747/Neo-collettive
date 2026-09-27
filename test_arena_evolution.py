import copy, tempfile, unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path
from arena_evolution import initial_state, register_initial_predictions, evaluate_due, refresh_scores, maybe_evolve, save_json

class EvolutionTests(unittest.TestCase):
    def test_score_uses_only_evaluated_predictions(self):
        s=initial_state()
        p={"prediction_id":"p","agent":"Scout","variant_id":"scout-evidence","statement":"x","probability":0.8,
           "created_at_utc":"2026-09-01T00:00:00+00:00","due_at_utc":"2026-09-02T00:00:00+00:00",
           "status":"EVALUATED","outcome":True,"calibration_score":0.96,"sources":["test"]}
        s["predictions"]=[p]
        s["consensus"]={"AGREE":9999}
        refresh_scores(s)
        score=[v["score"] for v in s["variants"] if v["variant_id"]=="scout-evidence"][0]
        self.assertEqual(score,0.96)
        s["consensus"]={"AGREE":0}
        refresh_scores(s)
        self.assertEqual([v["score"] for v in s["variants"] if v["variant_id"]=="scout-evidence"][0],0.96)

    def test_pending_prediction_has_no_score(self):
        s=initial_state(); register_initial_predictions(s,created_at=datetime(2026,9,27,tzinfo=timezone.utc)); refresh_scores(s)
        self.assertTrue(all(v["score"] is None for v in s["variants"]))

    def test_due_prediction_evaluated_against_verifier(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); save_json(root/"micelio.json",{"beliefs":[]})
            s=initial_state()
            s["predictions"]=[{"prediction_id":"p","agent":"Scout","variant_id":"scout-evidence","statement":"x","probability":0.75,
                               "created_at_utc":"2026-09-01T00:00:00+00:00","due_at_utc":"2026-09-02T00:00:00+00:00",
                               "status":"PENDING","verification":{"test":"production_health_profile"}}]
            evaluate_due(s,root,at=datetime(2026,9,3,tzinfo=timezone.utc),
                         overrides={"production_health_profile":lambda:(True,["fixture"])})
            p=s["predictions"][0]
            self.assertEqual(p["status"],"EVALUATED"); self.assertTrue(p["outcome"])
            self.assertAlmostEqual(p["calibration_score"],0.9375)

    def test_mutation_tracks_genealogy_and_never_promotes(self):
        s=initial_state()
        for v in s["variants"]:
            if v["agent"]=="Scout":
                v["score"]={"scout-breadth":0.2,"scout-gap":0.5,"scout-evidence":0.9}[v["variant_id"]]
        maybe_evolve(s,5,at=datetime(2026,9,30,tzinfo=timezone.utc))
        self.assertTrue(s["genealogy"])
        child=s["genealogy"][0]["child_variant_id"]
        cv=[v for v in s["variants"] if v["variant_id"]==child][0]
        self.assertEqual(cv["parent_id"],"scout-evidence")
        self.assertFalse(cv["production_promoted"])
        self.assertTrue(any(v["variant_id"]=="scout-breadth" and v["status"]=="RETIRED" for v in s["variants"]))

    def test_no_automatic_promotion(self):
        s=initial_state()
        self.assertFalse(s["production_proposal"]["automatic_promotion"])
        self.assertTrue(s["production_proposal"]["approval_required"])
        self.assertFalse(any(v["production_promoted"] for v in s["variants"]))

if __name__=="__main__": unittest.main()
