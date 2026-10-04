import json
import os
import unittest
from unittest.mock import patch

import hidden_control_gate as h

class HiddenCommercialControlTests(unittest.TestCase):
    def test_missing_optional_holdout_is_allowed(self):
        with patch.dict(os.environ,{},clear=True):
            result=h.evaluate_hidden_control()
        self.assertTrue(result["ok"])
        self.assertEqual(result["cases"],0)

    def test_missing_required_holdout_fails_closed(self):
        with patch.dict(os.environ,{h.REQUIRE_KEY:"1"},clear=True):
            with self.assertRaises(RuntimeError):
                h.enforce_hidden_control()

    def test_generic_runtime_holdout_can_pass_without_public_file(self):
        payload={"cases":[{
            "id":"runtime-only",
            "title":"Need help with spreadsheet cleanup",
            "body":"We manually clean CSV files every week and need a better workflow.",
            "source":"hn-algolia-routed",
            "url":"https://news.ycombinator.com/item?id=999",
            "expect":{"buyer":True,"first_person":True,"family":"spreadsheet_process","positive":True},
        }]}
        with patch.dict(os.environ,{h.REQUIRE_KEY:"1",h.ENV_KEY:json.dumps(payload)},clear=True):
            result=h.enforce_hidden_control()
        self.assertTrue(result["ok"])
        self.assertEqual(result["correct"],1)

if __name__=="__main__":
    unittest.main()
