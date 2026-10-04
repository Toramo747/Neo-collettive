import json
import os
import unittest
from unittest.mock import patch

import hidden_challenge_control_gate as h


class HiddenChallengeControlTests(unittest.TestCase):
    def _passing_case(self):
        return {
            "id":"hidden-runtime-only",
            "now_epoch":1800000000,
            "expect_ready":True,
            "evidence":[
                {"challenge_key":"h1","requester_key":"r1","domain":"github.com","created_at_epoch":1789000000,"workaround":True,"feasibility":"unknown","reward":False,"resolved":False},
                {"challenge_key":"h1","requester_key":"r2","domain":"stackoverflow.com","created_at_epoch":1790000000,"workaround":False,"feasibility":"unknown","reward":False,"resolved":False},
                {"challenge_key":"h1","requester_key":"r3","domain":"github.com","created_at_epoch":1791000000,"workaround":False,"feasibility":"unknown","reward":False,"resolved":False},
            ],
        }

    def test_missing_optional_holdout_is_allowed(self):
        with patch.dict(os.environ,{},clear=True):
            result=h.evaluate_hidden_challenge_control()
        self.assertTrue(result["ok"])
        self.assertEqual(result["cases"],0)

    def test_missing_required_holdout_fails_closed(self):
        with patch.dict(os.environ,{h.REQUIRE_KEY:"1"},clear=True):
            with self.assertRaises(RuntimeError):
                h.enforce_hidden_challenge_control()

    def test_labels_must_be_supplied_in_hidden_payload(self):
        case=self._passing_case()
        case.pop("expect_ready")
        payload={"cases":[case]}
        with patch.dict(os.environ,{h.REQUIRE_KEY:"1",h.ENV_KEY:json.dumps(payload)},clear=True):
            with self.assertRaisesRegex(RuntimeError,"label_missing"):
                h.enforce_hidden_challenge_control()

    def test_runtime_hidden_holdout_passes_when_labeled(self):
        payload={"cases":[self._passing_case()]}
        with patch.dict(os.environ,{h.REQUIRE_KEY:"1",h.ENV_KEY:json.dumps(payload)},clear=True):
            result=h.enforce_hidden_challenge_control()
        self.assertTrue(result["ok"])
        self.assertEqual(result["correct"],1)


if __name__=="__main__":
    unittest.main()
