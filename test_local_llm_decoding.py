# SPDX-License-Identifier: BUSL-1.1
import json
import unittest
from unittest.mock import patch

import arena_local_llm_compare as cmp
import local_llm_decoding as dec


class RobustDecodingTests(unittest.TestCase):
    def test_bounded_schema_limits_unbounded_strings_only(self):
        s = {"type": "object", "properties": {
            "a": {"type": "string"}, "b": {"type": "string", "maxLength": 9},
            "c": {"type": "string", "enum": ["x"]}, "d": {"type": "array", "items": {"type": ["string", "null"]}},
            "e": {"type": "integer"}}}
        b = dec.bounded_schema(s, 50)
        p = b["properties"]
        self.assertEqual(p["a"]["maxLength"], 50)
        self.assertEqual(p["b"]["maxLength"], 9)
        self.assertNotIn("maxLength", p["c"])
        self.assertEqual(p["d"]["items"]["maxLength"], 50)
        self.assertNotIn("maxLength", p["e"])
        self.assertNotIn("maxLength", s["properties"]["a"])  # original untouched

    def test_robust_options_add_repetition_control(self):
        self.assertGreater(dec.ROBUST_OPTIONS["repeat_penalty"], 1.0)
        self.assertGreater(dec.ROBUST_OPTIONS["num_predict"], dec.BASELINE_OPTIONS["num_predict"])
        self.assertEqual(dec.RETRY_OPTIONS["temperature"], 0.0)

    def test_robust_retries_once_on_invalid_json(self):
        calls = []

        def fake_post(url, payload, timeout=120):
            calls.append(payload)
            return {"response": "Un'opinione generale Un'opinione generale" if len(calls) % 2 else "{}"}
        with patch.object(cmp, "post_json", side_effect=fake_post):
            r = cmp.run_model("m", "robust")
        self.assertEqual(r["decoding"], "robust")
        self.assertEqual(r["metrics"]["retries"], len(r["transcript"]))
        self.assertEqual(calls[1]["options"]["temperature"], 0.0)
        self.assertIn("repeat_penalty", calls[0]["options"])

    def test_baseline_unchanged_and_never_retries(self):
        calls = []

        def fake_post(url, payload, timeout=120):
            calls.append(payload)
            return {"response": "not json"}
        with patch.object(cmp, "post_json", side_effect=fake_post):
            r = cmp.run_model("m", "baseline")
        self.assertEqual(r["metrics"]["retries"], 0)
        self.assertEqual(calls[0]["options"], dec.BASELINE_OPTIONS)
        self.assertEqual(len(calls), len(r["transcript"]))

    def test_preregistered_rule(self):
        def m(v, q):
            return {"model": "x", "metrics": {"schema_valid_rate": v, "average_quality_score": q,
                                               "average_generation_seconds": 1.0, "retries": 0}}
        self.assertTrue(cmp.decoding_ab([m(0.5, 0.6)], [m(0.75, 0.6)])["models"]["x"]["adopt_robust"])
        self.assertFalse(cmp.decoding_ab([m(0.5, 0.6)], [m(0.7, 0.9)])["models"]["x"]["adopt_robust"])
        self.assertFalse(cmp.decoding_ab([m(0.5, 0.6)], [m(1.0, 0.5)])["models"]["x"]["adopt_robust"])
        json.dumps(cmp.decoding_ab([m(0.5, 0.6)], [m(1.0, 0.7)]))


if __name__ == "__main__":
    unittest.main()
