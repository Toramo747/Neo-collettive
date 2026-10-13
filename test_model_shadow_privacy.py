import json
import tempfile
import unittest
from pathlib import Path

from tools.model_shadow_privacy_check import check_file


class ModelShadowPrivacyTests(unittest.TestCase):
    def test_safe_aggregate_student_and_cluster_outputs_pass(self):
        safe={
            "mode":"shadow",
            "cases":12,
            "agreement_rate_ppm":800000,
            "student_public_accuracy_ppm":900000,
            "student_hidden_accuracy_ppm":850000,
            "promotion_eligible":False,
        }
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/"metrics.json"
            p.write_text(json.dumps(safe),encoding="utf-8")
            check_file(p)

    def test_text_url_and_domain_are_rejected(self):
        cases=[
            {"text":"private evidence"},
            {"url":"https://private.example/x"},
            {"domain":"private.example"},
            {"nested":{"normalized_text":"private"}},
        ]
        with tempfile.TemporaryDirectory() as td:
            for i,payload in enumerate(cases):
                p=Path(td)/f"bad-{i}.json"
                p.write_text(json.dumps(payload),encoding="utf-8")
                with self.subTest(payload=payload):
                    with self.assertRaises(ValueError):
                        check_file(p)

    def test_url_like_value_is_rejected_even_under_unknown_key(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/"bad.json"
            p.write_text(json.dumps({"value":"https://private.example/x"}),encoding="utf-8")
            with self.assertRaisesRegex(ValueError,"url_value"):
                check_file(p)


if __name__=="__main__":
    unittest.main()
