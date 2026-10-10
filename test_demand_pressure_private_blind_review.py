import importlib.util
import tempfile
import unittest
from pathlib import Path
s=importlib.util.spec_from_file_location("ipd_private_review",Path("experiments/demand-pressure/private_blind_review.py"))
m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
class PrivateIPDReviewTests(unittest.TestCase):
 def test_empty_cases_private_packet(self):
  with tempfile.TemporaryDirectory() as d:
   target=str(Path(d)/"new")
   cases,mapping=m.prepare_cases([{"ok":True,"hits":[]}]*4,secret=b"x"*32)
   self.assertEqual(cases,[])
   result=m.write_packet(target,cases,mapping)
   self.assertEqual(result["independent_human_reviews_completed"],0)
   self.assertTrue((Path(target)/m.CASE_FILE).exists())
   self.assertEqual(m.aggregate(target)["status"],"INSUFFICIENT_CASES")
 def test_no_public_source_persistence_or_auto_learning(self):
  t=Path("experiments/demand-pressure/private_blind_review.py").read_text()
  self.assertNotIn("AUTOPILOT_STATE",t)
  self.assertNotIn("trigger_deploy(",t)
  self.assertNotIn("train_student(",t)
  self.assertNotIn("commercial_evidence_memory",t)
 def test_label_validation(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/"review.csv"
   p.write_text("case_id,label,explicit_solution_request,theme,reason\na,bad,yes,other,\n")
   with self.assertRaises(ValueError): m._review_file(p,{"a"})
 def test_dir_inside_repo_rejected(self):
  with self.assertRaises(ValueError):
   m._private_dir(str(Path.cwd()/".private-test"),create=True)
 def test_provider_partial_prevents_packet(self):
  with self.assertRaises(ValueError):
   m.prepare_cases([{"ok":False,"hits":[]}]*4,secret=b"x"*32)
if __name__=="__main__":unittest.main()
