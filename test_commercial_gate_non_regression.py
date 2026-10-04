import json
import unittest

from arena_research_algorithm import evaluate_control_cases


class CommercialGateNonRegressionTests(unittest.TestCase):
    def test_existing_public_commercial_controls_are_identical(self):
        data=json.load(open("data/arena/research-algorithm/control_cases.json",encoding="utf-8"))
        result=evaluate_control_cases(data.get("cases") or [])
        self.assertEqual(result["cases"],24)
        self.assertEqual(result["correct"],24)
        self.assertEqual(result["family_cases"],24)
        self.assertEqual(result["family_correct"],24)
        self.assertTrue(all(row.get("ok") is True for row in result.get("details") or []))
        self.assertTrue(all(row.get("family_ok") is True for row in result.get("details") or []))

    def test_commercial_control_file_has_not_been_repurposed_for_challenges(self):
        data=json.load(open("data/arena/research-algorithm/control_cases.json",encoding="utf-8"))
        self.assertEqual(data.get("purpose"),"public_generalization_control")
        self.assertNotIn("challenge",json.dumps(data).lower())


if __name__=="__main__":
    unittest.main()
