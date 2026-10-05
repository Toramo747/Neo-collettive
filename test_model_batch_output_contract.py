# SPDX-License-Identifier: BUSL-1.1
import json
import tempfile
import unittest
from pathlib import Path
from tools.model_shadow_batch import llm_judge, _source_bucket, _student_training_selection

class FakeLLM:
    def __init__(self, responses):
        self.responses=list(responses if isinstance(responses,list) else [responses])
        self.calls=0
        self.kwargs=[]
    def create_chat_completion(self, **kwargs):
        idx=min(self.calls,len(self.responses)-1)
        self.kwargs.append(kwargs)
        self.calls+=1
        return {"choices":[{"message":{"content":json.dumps(self.responses[idx])}}]}

class OutputContractTests(unittest.TestCase):
    def test_dual_prompt_agreement_supplies_llm_vote(self):
        llm=FakeLLM([
            {"proposed_label":"buyer_tool_search","confidence":0.01},
            {"proposed_label":"buyer_tool_search","confidence":0.99},
            {"canonical_problem":"","target_user":"","current_workaround":"","quoted_price":"","writer_role":"","failed_attempt":False,"feasibility":"unknown"},
        ])
        vote,_=llm_judge(llm,"synthetic",{})
        self.assertEqual(vote["label"],"buyer_tool_search")
        self.assertEqual(vote["confidence"],1.0)
        self.assertEqual(llm.calls,3)

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

    def test_second_prompt_is_semantically_equivalent_with_reordered_labels(self):
        llm=FakeLLM([
            {"proposed_label":"buyer_tool_search"},
            {"proposed_label":"buyer_tool_search"},
            {},
        ])
        llm_judge(llm,"synthetic",{})
        first=llm.kwargs[0]["messages"][0]["content"]
        second=llm.kwargs[1]["messages"][0]["content"]
        first_order="buyer_tool_search,vendor_offer,manual_recurring_work,job_posting,other"
        second_order="other,job_posting,manual_recurring_work,vendor_offer,buyer_tool_search"
        self.assertIn(first_order,first)
        self.assertIn(second_order,second)
        self.assertEqual(first.replace(first_order,"<ORDER>"),second.replace(second_order,"<ORDER>"))

    def test_source_bucket_reuses_production_canonical_sources(self):
        cases={
            "hn-algolia-routed":"hn",
            "bing-rss-free":"bing-rss",
            "brave-search":"brave",
            "stackexchange":"stackexchange",
            "github":"github",
            "reddit-web":"reddit",
        }
        for source,expected in cases.items():
            with self.subTest(source=source):
                self.assertEqual(_source_bucket({"source":source}),expected)

    def test_training_excludes_classes_below_minimum(self):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)
            rows=[]
            for i in range(5):
                rows.append({"id":"o"+str(i),"final_label":"other","eligible_for_training":True})
            for i in range(3):
                rows.append({"id":"j"+str(i),"final_label":"job_posting","eligible_for_training":True})
            (p/"train_labeled.jsonl").write_text(
                "\n".join(json.dumps(row) for row in rows)+"\n",
                encoding="utf-8",
            )
            selected,metrics=_student_training_selection(p)
            self.assertEqual(len(selected),5)
            self.assertEqual(metrics["training_label_used_other"],5)
            self.assertEqual(metrics["training_label_excluded_job_posting"],3)
            self.assertEqual(metrics["training_classes_used"],1)

if __name__=="__main__":
    unittest.main()
