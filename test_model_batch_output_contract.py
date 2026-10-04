# SPDX-License-Identifier: BUSL-1.1
import json
import unittest
from tools.model_shadow_batch import llm_judge

class FakeLLM:
    def __init__(self, data): self.data=data
    def create_chat_completion(self, **kwargs):
        return {"choices":[{"message":{"content":json.dumps(self.data)}}]}

class OutputContractTests(unittest.TestCase):
    def test_invalid_confidence_abstains(self):
        for value in ("high", "90%", None, {}, [], True, float("nan"), float("inf"), -1, 2):
            with self.subTest(value=value):
                vote,_=llm_judge(FakeLLM({"proposed_label":"buyer_tool_search", "confidence":value}),"synthetic",{})
                self.assertEqual(vote["confidence"],0)
    def test_valid_confidence_preserved(self):
        vote,_=llm_judge(FakeLLM({"proposed_label":"buyer_tool_search", "confidence":0.95}),"synthetic",{})
        self.assertEqual(vote["confidence"],0.95)
    def test_non_object_json_abstains(self):
        for value in ([], None, "high"):
            vote,_=llm_judge(FakeLLM(value),"synthetic",{})
            self.assertEqual(vote["confidence"],0)
