# SPDX-License-Identifier: BUSL-1.1
"""Offline tests: zero-cost synthetic Arena benchmark."""
import json
import unittest
from unittest.mock import patch
import arena_free_model_benchmark as b

class FreeModelBenchmarkTests(unittest.TestCase):
    def test_fixture_is_synthetic(self):
        f=b.fixture()
        self.assertEqual(12,len(f["cases"]))
        self.assertTrue(f["strictly_no_private_data"])
    def test_gold_answer_never_in_prompt(self):
        c=b.fixture()["cases"][0]
        p=b.prompt(c)
        self.assertNotIn('"decision":',p)
        self.assertNotIn(c["failure_mode"],p)
    def test_perfect_grader(self):
        for c in b.fixture()["cases"]:
            answer=json.dumps({"decision":c["decision"],"rationale":"Measured reasoning on this synthetic case.","falsifier":"Reject if a repeated evaluation disagrees.","evidence_ids":c["evidence_ids"]})
            r=b.grade(answer,c)
            if c["decision"]=="ACCEPT":
                self.assertTrue(r["decision_correct"],c["id"])
            else:
                self.assertTrue(r["decision_correct"],c["id"])
    def test_no_invented_ids(self):
        c=b.fixture()["cases"][0]
        r=b.grade(json.dumps({"decision":c["decision"],"rationale":"Synthetic reasoning for this test.","falsifier":"","evidence_ids":["REAL-UNKNOWN"]}),c)
        self.assertTrue(r["fabricated_ids"])
        self.assertFalse(r["decision_correct"])
    def test_bad_json_rejected(self):
        r=b.grade("approved",b.fixture()["cases"][0])
        self.assertFalse(r["valid_json"])
    def test_not_installed_means_no_inference(self):
        with patch.object(b,"installed_models",return_value={}),patch.object(b,"infer",side_effect=AssertionError("should not infer")):
            r=b.evaluate([b.MODELS[0]],10,60)
            self.assertFalse(r["all_models_compared_completely"])
            self.assertEqual("SKIPPED_NOT_INSTALLED",r["results"][0]["status"])
    def test_no_paid_endpoints(self):
        for path in ("https://example.com","/v1/chat/completions","http://127.0.0.1:1234"):
            with self.assertRaises(ValueError):
                b.request_json(path,None,5)
    def test_plan_no_network(self):
        with patch.object(b,"installed_models",side_effect=AssertionError("network called")):
            p=b.plan(list(b.MODELS))
        self.assertFalse(p["would_infer"])
        self.assertTrue(p["no_paid_api"])
        self.assertFalse(p["automatic_promotion"])

if __name__=="__main__":
    unittest.main()
