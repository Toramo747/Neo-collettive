import unittest
from gate_stability import apply_gate_hysteresis

class GateStabilityTests(unittest.TestCase):
    def _row(self, passed, score=90, tool="X", family="finance_ops"):
        return {
            "family":family,"tool_name":tool,"target_user":"ops","problem":"manual reconciliation",
            "gate_pass":passed,"monetization_score":score,"missing":[],
            "sources":[{"domain":"a.example"}],
        }

    def test_requires_two_passes_to_enter(self):
        s,rows=apply_gate_hysteresis({},[self._row(True)])
        self.assertFalse(rows[0]["stable_gate_pass"])
        s,rows=apply_gate_hysteresis(s,[self._row(True)])
        self.assertTrue(rows[0]["stable_gate_pass"])

    def test_two_rows_same_candidate_cannot_promote_in_one_cycle(self):
        row=self._row(True)
        duplicate=dict(row)
        duplicate["monetization_score"]=95
        s,rows=apply_gate_hysteresis({},[row,duplicate])
        self.assertFalse(rows[0]["stable_gate_pass"])
        self.assertFalse(rows[1]["stable_gate_pass"])
        key=rows[0]["gate_candidate_key"]
        self.assertEqual(s["candidates"][key]["pass_streak"],1)

    def test_two_candidates_same_family_keep_independent_streaks(self):
        s,rows=apply_gate_hysteresis({},[
            self._row(True,tool="Invoice X"),
            self._row(True,tool="Invoice Y"),
        ])
        self.assertFalse(rows[0]["stable_gate_pass"])
        self.assertFalse(rows[1]["stable_gate_pass"])
        self.assertNotEqual(rows[0]["gate_candidate_key"],rows[1]["gate_candidate_key"])

    def test_one_failure_does_not_drop_stable_gate(self):
        s,_=apply_gate_hysteresis({},[self._row(True)])
        s,rows=apply_gate_hysteresis(s,[self._row(True)])
        self.assertTrue(rows[0]["stable_gate_pass"])
        s,rows=apply_gate_hysteresis(s,[self._row(False,30)])
        self.assertTrue(rows[0]["stable_gate_pass"])
        s,rows=apply_gate_hysteresis(s,[self._row(False,30)])
        self.assertFalse(rows[0]["stable_gate_pass"])

    def test_absent_candidate_decays_after_two_cycles(self):
        s,_=apply_gate_hysteresis({},[self._row(True)])
        s,rows=apply_gate_hysteresis(s,[self._row(True)])
        key=rows[0]["gate_candidate_key"]
        self.assertTrue(s["candidates"][key]["stable"])
        s,_=apply_gate_hysteresis(s,[])
        self.assertTrue(s["candidates"][key]["stable"])
        s,_=apply_gate_hysteresis(s,[])
        self.assertFalse(s["candidates"][key]["stable"])

    def test_flip_records_only_private_metadata(self):
        s,_=apply_gate_hysteresis({},[self._row(False,30)],version="1",commit="abc")
        s,_=apply_gate_hysteresis(s,[self._row(True,90)],version="2",commit="def")
        self.assertEqual(len(s["flips"]),1)
        f=s["flips"][0]
        self.assertEqual(f["from_raw"],False)
        self.assertEqual(f["to_raw"],True)
        self.assertTrue(f["evidence_unchanged"])
        self.assertEqual(f["previous_score"],30)
        self.assertEqual(f["current_score"],90)
        self.assertIn("previous_fingerprint",f)
        self.assertIn("current_fingerprint",f)
        self.assertNotIn("sources",f)

if __name__=="__main__":
    unittest.main()
