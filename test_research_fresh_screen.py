import importlib.util,unittest
from pathlib import Path
p=Path("experiments/research-fresh-screen/screen.py")
s=importlib.util.spec_from_file_location("research_gametes_fresh_screen",p)
m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
class GameteFreshScreenTests(unittest.TestCase):
 def test_fixed_budget_and_training_exclusion(self):
  policy=m.load();arms=m.plan(policy)
  self.assertEqual(len(arms),9)
  self.assertEqual(len({a["id"] for a in arms}),9)
  self.assertEqual(policy["screen_month"],"2026-08")
  self.assertNotIn("2026-08",policy["training_months"])
  for a in arms:self.assertEqual(len(m.make_pairs(policy,a["search_genes"])),16)
  self.assertFalse(policy["boundaries"]["production_state_write"])
 def test_fail_closed_and_no_auto_promotion(self):
  policy=m.load()
  def fixture(threads,precision,relevant,topics,ok=16,intact=True):
   return {"ok":ok,"integrity":intact,"score":{"score":{"unique_signal_threads":threads,"precision":precision,"relevant_hits":relevant,"topic_coverage":topics}}}
  a=fixture(0,0,16,0);b=fixture(3,.18,16,2)
  self.assertEqual(m.verdict(a,b,policy),"SCREEN_POSITIVE_NOT_VALIDATED")
  self.assertEqual(m.verdict(a,fixture(0,0,16,0),policy),"NO_DEMONSTRATED_GAIN")
  self.assertEqual(m.verdict(a,fixture(3,.18,16,2,intact=False),policy),"INCONCLUSIVE_METRIC_DISAGREEMENT")
  self.assertEqual(m.verdict(a,fixture(3,.18,16,2,ok=15),policy),"INCONCLUSIVE_PROVIDER_FAILURE")
  self.assertFalse(policy["boundaries"]["automatic_promotion"])
 def test_no_live_code_mutation(self):
  src=p.read_text()
  self.assertNotIn("trigger_deploy(",src)
  self.assertNotIn("replace_evidence_memory(",src)
  self.assertIn('"development_screen_only":True',src)
  self.assertIn('"validated_independent_rounds":0',src)
