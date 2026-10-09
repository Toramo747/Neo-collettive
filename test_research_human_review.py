"""Pure synthetic, no HN requests, no source data in repository."""
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

SOURCE=Path("experiments/research-human-review/review.py")
s=importlib.util.spec_from_file_location("oxibay_blind_review",SOURCE)
m=importlib.util.module_from_spec(s);s.loader.exec_module(m)

class BlindReviewTests(unittest.TestCase):
 def setUp(self):self.p=m.policy()
 def test_safety_and_budget(self):
  self.assertEqual(self.p["max_query_count"],16)
  self.assertEqual(self.p["max_cases"],30)
  self.assertFalse(self.p["boundary"]["production_state_write"])
  self.assertFalse(self.p["boundary"]["auto_promotion"])
  self.assertFalse(self.p["boundary"]["raw_data_to_github"])
 def test_real_classifier_synthetic_examples(self):
  genes=m.screen.plan(m.screen.load())[0]["search_genes"]
  topic="manual data entry";query="manual data entry workaround"
  good={"objectID":"12","story_id":"12","comment_text":m.v2.POSITIVE_TEXT}
  bad={"objectID":"13","story_id":"13","comment_text":"A release note was published"}
  self.assertEqual(m.stage(topic,query,good,genes),"valid_signal")
  self.assertNotEqual(m.stage(topic,query,bad,genes),"valid_signal")
 def test_blind_packet_hides_prediction_and_deduplicates_threads(self):
  items=[{"stage":tag,"object_id":tag+str(i),"thread_id":tag+str(i//2)}
         for tag in self.p["stages"] for i in range(10)]
  selected=m.select(items,self.p,"synthetic-salt")
  self.assertLessEqual(len(selected),30)
  self.assertEqual(len({x["thread_id"] for x in selected}),len(selected))
  packet=m.visible({"case_id":"abc","topic":"topic","title":"title","body":"body",
    "hn_url":"https://news.ycombinator.com/item?id=123","stage":"irrelevant"})
  self.assertNotIn("stage",json.dumps(packet))
 def test_directory_rejects_repo_and_relative_paths(self):
  with self.assertRaises(ValueError):m.private_path("relative")
  with self.assertRaises(ValueError):m.private_path(str(m.ROOT/"private"))
 def test_incomplete_review_is_not_success(self):
  with tempfile.TemporaryDirectory(prefix="oxibay-private-") as parent:
   dest=str(Path(parent)/"review")
   case={"case_id":"synthetic-one","stage":"valid_signal","topic":"task",
     "title":"title","body":"body","hn_url":"https://news.ycombinator.com/item?id=1"}
   m.write_packet(dest,[case],self.p)
   file=Path(dest)/m.ONE
   file.write_text(m.labels_template(["synthetic-one"]).replace("synthetic-one,,,","synthetic-one,real_demand,,"),encoding="utf-8")
   m.aggregate(dest)
   report=json.loads((Path(dest)/m.REPORT).read_text())
   self.assertEqual(report["status"],"INCOMPLETE_REVIEW")
   self.assertFalse(report["commercial_proof"])
 def test_two_completed_synthetic_reviews_are_only_descriptive(self):
  with tempfile.TemporaryDirectory(prefix="oxibay-private-") as parent:
   dest=str(Path(parent)/"review")
   case={"case_id":"synthetic-two","stage":"no_buyer_voice","topic":"task",
      "title":"title","body":"body","hn_url":"https://news.ycombinator.com/item?id=2"}
   m.write_packet(dest,[case],self.p)
   for fname in (m.ONE,m.TWO):
    file=Path(dest)/fname
    file.write_text(m.labels_template(["synthetic-two"]).replace("synthetic-two,,,","synthetic-two,real_demand,,"),encoding="utf-8")
   m.aggregate(dest)
   report=json.loads((Path(dest)/m.REPORT).read_text())
   self.assertEqual(report["status"],"INSUFFICIENT_CASES")
   self.assertEqual(report["agreed_false_negatives"],1)
   self.assertFalse(report["representative_error_rates"])
   self.assertFalse(report["independent_reviewer_identity_verified"])
 def test_no_auto_train_deploy_or_upload(self):
  source=SOURCE.read_text(encoding="utf-8")
  self.assertNotIn("trigger_deploy(",source)
  self.assertNotIn("replace_evidence_memory(",source)
  self.assertNotIn("upload_artifact(",source)
  self.assertIn("development_only",source)
