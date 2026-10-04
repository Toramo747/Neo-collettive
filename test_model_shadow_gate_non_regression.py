import json
import unittest

from arena_research_algorithm import evaluate_control_cases
from challenge_track import evaluate_public_control_cases


class ModelShadowGateNonRegressionTests(unittest.TestCase):
    def test_commercial_gate_public_controls_remain_identical(self):
        data=json.load(open("data/arena/research-algorithm/control_cases.json",encoding="utf-8"))
        result=evaluate_control_cases(data.get("cases") or [])
        self.assertEqual(result["cases"],24)
        self.assertEqual(result["correct"],24)
        self.assertEqual(result["family_cases"],24)
        self.assertEqual(result["family_correct"],24)

    def test_challenge_gate_public_controls_remain_identical(self):
        data=json.load(open("data/challenge/control_cases.json",encoding="utf-8"))
        result=evaluate_public_control_cases(data.get("cases") or [])
        self.assertGreaterEqual(result["cases"],12)
        self.assertEqual(result["correct"],result["cases"])


if __name__=="__main__":
    unittest.main()
