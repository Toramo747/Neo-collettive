import unittest
from gate_stability import apply_gate_hysteresis

class GateStabilityTests(unittest.TestCase):
    def _row(self, passed, score=90):
        return {"family":"finance_ops","tool_name":"X","gate_pass":passed,"monetization_score":score,"missing":[],"sources":[{"domain":"a.example"}]}

    def test_requires_two_passes_to_enter(self):
        s,rows=apply_gate_hysteresis({},[self._row(True)])
        self.assertFalse(rows[0]["stable_gate_pass"])
        s,rows=apply_gate_hysteresis(s,[self._row(True)])
        self.assertTrue(rows[0]["stable_gate_pass"])

    def test_one_failure_does_not_drop_stable_gate(self):
        s,_=apply_gate_hysteresis({},[self._row(True)])
        s,rows=apply_gate_hysteresis(s,[self._row(True)])
        self.assertTrue(rows[0]["stable_gate_pass"])
        s,rows=apply_gate_hysteresis(s,[self._row(False,30)])
        self.assertTrue(rows[0]["stable_gate_pass"])
        s,rows=apply_gate_hysteresis(s,[self._row(False,30)])
        self.assertFalse(rows[0]["stable_gate_pass"])

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
