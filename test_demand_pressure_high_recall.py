import importlib.util
import unittest
from pathlib import Path
p=Path("experiments/demand-pressure/file_access_coverage.py")
s=importlib.util.spec_from_file_location("ipd_high_recall",p)
m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
class HighRecallTests(unittest.TestCase):
 def test_empty_complete_provider(self):
  r=m.review([{"ok":True,"nbHits":0,"exhaustiveNbHits":True,"hits":[]} for i in range(4)],key=b'x'*32)
  self.assertTrue(r["all_source_windows_complete"])
  self.assertEqual(r["all_unique_candidate_threads"],0)
  self.assertEqual(r["human_labels"],0)
 def test_truncation_must_not_count_as_complete(self):
  r=m.review([{"ok":True,"nbHits":1000,"exhaustiveNbHits":False,"hits":[]} for i in range(4)],key=b'x'*32)
  self.assertFalse(r["all_source_windows_complete"])
  self.assertEqual(r["status"],"INCONCLUSIVE_SOURCE_CAPPED_OR_APPROXIMATE")
 def test_partial_provider_inconclusive(self):
  r=m.review([{"ok":False}]*4,key=b'x'*32)
  self.assertEqual(r["status"],"INCONCLUSIVE_PROVIDER_FAILURE")
 def test_invalid_count_fails_closed(self):
  with self.assertRaises(ValueError):
   m.review([{"ok":True,"nbHits":False,"exhaustiveNbHits":True,"hits":[]} for i in range(4)],key=b'x'*32)
 def test_source_and_gate_not_written(self):
  t=p.read_text()
  self.assertNotIn("AUTOPILOT_STATE",t)
  self.assertNotIn("trigger_deploy(",t)
  self.assertNotIn("commercial_evidence_memory",t)
if __name__=="__main__":unittest.main()
