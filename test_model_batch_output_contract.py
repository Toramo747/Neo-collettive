# SPDX-License-Identifier: BUSL-1.1
import json
import unittest
from tools.model_shadow_batch import llm_judge

class FakeLLM:
    def __init__(self, responses):
        self.responses=list(responses if isinstance(responses,list) else [responses])
        self.calls=0
    def create_chat_completion(self, **kwargs):
        idx=min(self.calls,len(self.responses)-1)
        self.calls+=1
        return {"choices":[{"message":{"content":json.dumps(self.responses[idx])}}]}

class OutputContractTests(unittest.TestCase):
    def test_dual_prompt_agreement_supplies_llm_vote(self):
        llm=FakeLLM([
            {"proposed_label":"buyer_tool_search","confidence":0.01},
            {"proposed_label":"buyer_tool_search","confidence":0.99},
        ])
        vote,_=llm_judge(llm,"synthetic",{})
        self.assertEqual(vote["label"],"buyer_tool_search")
        self.assertEqual(vote["confidence"],1.0)
        self.assertEqual(llm.calls,2)

    def test_self_declared_confidence_is_ignored(self):
        llm=FakeLLM([
            {"proposed_label":"buyer_tool_search","confidence":0.99},
            {"proposed_label":"vendor_offer","confidence":0.99},
        ])
        vote,_=llm_judge(llm,"synthetic",{})
        self.assertEqual(vote["confidence"],0.0)

    def test_invalid_or_non_object_second_response_abstains(self):
        for second in ([],None,"high",{"proposed_label":"unknown"}):
            with self.subTest(second=second):
                llm=FakeLLM([
                    {"proposed_label":"buyer_tool_search","confidence":0.99},
                    second,
                ])
                vote,_=llm_judge(llm,"synthetic",{})
                self.assertEqual(vote["confidence"],0.0)

    def test_non_object_first_response_abstains(self):
        llm=FakeLLM([[],{"proposed_label":"other"}])
        vote,_=llm_judge(llm,"synthetic",{})
        self.assertEqual(vote["confidence"],0.0)

if __name__=="__main__":
    unittest.main()
