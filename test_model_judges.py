import json
import re
import unittest

from model_judges import choose_automatic_label, challenge_semantic_review
from model_shadow import validate_hidden_origins, validate_split_separation


class ModelJudgeContractTests(unittest.TestCase):
    def test_model_registry_is_pinned_and_commercially_licensed(self):
        registry=json.load(open("model_shadow_registry.json",encoding="utf-8"))
        allowed={"MIT","Apache-2.0"}
        for name in ("nli","local_llm","embedding"):
            row=registry["judges"][name]
            self.assertTrue(row["commercial_use_allowed"],name)
            self.assertIn(row["license"],allowed,name)
            self.assertRegex(row["revision"],r"^[0-9a-f]{40}$")
        self.assertRegex(registry["judges"]["local_llm"]["sha256"],r"^[0-9a-f]{64}$")
        self.assertEqual(registry["promotion"],"manual_only")
        self.assertEqual(registry["student"]["render_mode"],"shadow")

    def test_splits_must_be_strictly_disjoint(self):
        result=validate_split_separation({"a","b"},{"c"},{"d"})
        self.assertTrue(result["disjoint"])
        with self.assertRaisesRegex(ValueError,"split_overlap"):
            validate_split_separation({"a"},{"a"},{"d"})

    def test_hidden_never_accepts_auto_label_origin(self):
        validate_hidden_origins([{"label_origin":"human"},{"label_origin":"outcome"}])
        with self.assertRaisesRegex(ValueError,"hidden_label"):
            validate_hidden_origins([{"label_origin":"auto"}])

    def test_three_high_confidence_judges_are_required(self):
        rows=[
            {"judge":"lexicon","label":"buyer_tool_search","confidence":0.9},
            {"judge":"nli","label":"buyer_tool_search","confidence":0.9},
        ]
        result=choose_automatic_label(rows,minimum_judges=3,confidence_threshold=0.7)
        self.assertFalse(result["eligible_for_training"])
        rows.append({"judge":"local_llm","label":"buyer_tool_search","confidence":0.8})
        result=choose_automatic_label(rows,minimum_judges=3,confidence_threshold=0.7)
        self.assertTrue(result["eligible_for_training"])
        self.assertEqual(result["label"],"buyer_tool_search")

    def test_low_confidence_vote_does_not_form_consensus(self):
        rows=[
            {"judge":"lexicon","label":"vendor_offer","confidence":0.99},
            {"judge":"nli","label":"vendor_offer","confidence":0.69},
            {"judge":"local_llm","label":"vendor_offer","confidence":0.95},
            {"judge":"structural","label":"other","confidence":0.95},
        ]
        result=choose_automatic_label(rows,minimum_judges=3,confidence_threshold=0.7)
        self.assertFalse(result["eligible_for_training"])

    def test_outcome_label_overrides_automatic_consensus(self):
        rows=[
            {"judge":"lexicon","label":"vendor_offer","confidence":0.99},
            {"judge":"nli","label":"vendor_offer","confidence":0.99},
            {"judge":"local_llm","label":"vendor_offer","confidence":0.99},
        ]
        result=choose_automatic_label(rows,outcome_label="buyer_tool_search")
        self.assertEqual(result["label"],"buyer_tool_search")
        self.assertEqual(result["origin"],"outcome")

    def test_unknown_feasibility_is_review_required_in_model_shadow(self):
        self.assertEqual(
            challenge_semantic_review({"resolved":False},{"feasibility":"unknown"}),
            "REVIEW_REQUIRED",
        )

    def test_not_planned_is_not_treated_as_resolved_in_shadow(self):
        self.assertEqual(
            challenge_semantic_review(
                {"resolved":True,"close_reason":"not_planned"},
                {"feasibility":"unknown"},
            ),
            "REVIEW_REQUIRED",
        )


if __name__=="__main__":
    unittest.main()
