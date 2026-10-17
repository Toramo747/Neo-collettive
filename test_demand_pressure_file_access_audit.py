import importlib.util
import unittest
from pathlib import Path
p=Path("experiments/demand-pressure/file_access_audit.py")
s=importlib.util.spec_from_file_location("ipd_file_audit",p)
m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
class FileAccessAuditTests(unittest.TestCase):
 def test_plan(self):
  self.assertEqual(len(m.protocol()),4)
  self.assertEqual(m.protocol()[0]["week"],0)
 def test_incomplete_provider(self):
  x=m.analyze([{"ok":False,"hits":[]}]*4,secret=b"x"*32)
  self.assertEqual(x["status"],"INCONCLUSIVE_PROVIDER_FAILURE")
 def test_no_data_is_not_human_validated(self):
  x=m.analyze([{"ok":True,"hits":[]}]*4,secret=b"x"*32)
  self.assertEqual(x["candidate_counts"]["candidate_threads"],0)
  self.assertFalse(x["replayed_exact_original_cases"])
  self.assertEqual(x["human_reviewed_cases"],0)
 def test_duplicated_same_thread(self):
  window=m.protocol()[0]
  txt="I need help with file access permissions. I manually request access to files and need a tool."
  h={"objectID":"1","story_id":"same","created_at_i":window["end"]-200,"title":"File access permissions", "comment_text":txt,"author":"person"}
  b=[{"ok":True,"hits":[h,{**h,"objectID":"2"}]}]+[{"ok":True,"hits":[]}]*3
  x=m.analyze(b,secret=b"x"*32)
  self.assertLessEqual(x["candidate_counts"]["candidate_threads"],1)
  self.assertEqual(x["human_reviewed_cases"],0)
 def test_refuse_bad_hit_volume(self):
  with self.assertRaises(ValueError):
   m.analyze([{"ok":True,"hits":[{}]*31}]+[{"ok":True,"hits":[]}]*3,secret=b"x"*32)
if __name__=="__main__":unittest.main()
