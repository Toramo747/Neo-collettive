import unittest
import asyncio
from demand_research_coverage import assess_public_hn_coverage,probe_public_hn_coverage
def h(n, text="Need help with file access permissions"):
 return {"objectID":str(n),"story_id":str(n),"title":"File access","comment_text":text}
class CoverageTests(unittest.TestCase):
 def test_truncation_and_more_relevance(self):
  data={"hits":[h(i) for i in range(6)],"nbHits":120,"exhaustiveNbHits":False}
  z=assess_public_hn_coverage(data,"file access",sample_cap=6,baseline_cap=3)
  self.assertEqual(z["relevant_first_baseline"],3)
  self.assertEqual(z["additional_relevant_in_sample"],3)
  self.assertFalse(z["source_complete"])
  self.assertEqual(z["commercial_gate_influence"],"NONE")
 def test_no_exhaustive_is_not_full_coverage(self):
  z=assess_public_hn_coverage({"hits":[h(1)],"nbHits":1,"exhaustiveNbHits":False},"file access")
  self.assertEqual(z["status"],"OBSERVED_INCOMPLETE")
 def test_exact_provider_can_be_complete(self):
  z=assess_public_hn_coverage({"hits":[h(1)],"nbHits":1,"exhaustiveNbHits":True},"file access")
  self.assertTrue(z["source_complete"])
 def test_duplicate_comments_collapse_by_thread(self):
  a=h(1);b={**h(2),"story_id":"1"}
  z=assess_public_hn_coverage({"hits":[a,b],"nbHits":2,"exhaustiveNbHits":True},"file access",baseline_cap=1)
  self.assertEqual(z["relevant_in_sample"],1)
  self.assertEqual(z["additional_relevant_in_sample"],0)
 def test_invalid_payload_no_demand_claim(self):
  z=assess_public_hn_coverage({"hits":[{"objectID":"1"}],"nbHits":True},"file access")
  self.assertIsNone(z["provider_reported_matches"])
  self.assertFalse(z["source_complete"])
 def test_one_request_and_no_raw_output(self):
  calls=[]
  async def mock(url,params):
   calls.append((url,params))
   return {"hits":[h(1)],"nbHits":1,"exhaustiveNbHits":False}
  z=asyncio.run(probe_public_hn_coverage("file access",http_get=mock))
  self.assertEqual(len(calls),1)
  self.assertEqual(calls[0][1]["hitsPerPage"],60)
  self.assertNotIn("story_id",str(z))
  self.assertFalse(z["raw_content_persisted"])
 def test_failure_closed(self):
  async def fail(url,params): raise ValueError("failure")
  z=asyncio.run(probe_public_hn_coverage("file access",http_get=fail))
  self.assertEqual(z["status"],"PROVIDER_ERROR")
if __name__=="__main__":unittest.main()
