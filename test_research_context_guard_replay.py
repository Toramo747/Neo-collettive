"""Strictly synthetic, no-network regression tests of content guard replay."""
import importlib.util
import unittest
from pathlib import Path

SRC=Path("experiments/research-context-guard-replay/check.py")
spec=importlib.util.spec_from_file_location("research_context_guard_replay",SRC)
m=importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

class GuardReplayTests(unittest.TestCase):
 def setUp(self):
  self.p,self.previous=m.load()
 def test_policy_and_isolation(self):
  self.assertEqual(self.p["public_requests_ceiling"],5)
  self.assertEqual(len(self.p["contexts"]),3)
  self.assertFalse(self.p["boundaries"]["full_production_score_emulated"])
  self.assertFalse(self.p["boundaries"]["automatic_promotion"])
  self.assertFalse(self.p["boundaries"]["production_write"])
  self.assertEqual(self.p["boundaries"]["commercial_gate_influence"],"NONE")
 def test_gate_fixture_known_positive(self):
  good={"objectID":"syn-good","story_id":"syn-story",
        "comment_text":m.v2.POSITIVE_TEXT}
  result=m.legacy_content_stage(good)
  self.assertEqual(result["stage"],"passes_content_only")
  self.assertTrue(result["positives"])
 def test_negative_fixture_is_not_positive(self):
  bad={"objectID":"syn-bad","title":"A documentation release was published",
       "comment_text":"This page lists features of a tool"}
  result=m.legacy_content_stage(bad)
  self.assertNotEqual(result["stage"],"passes_content_only")
 def test_shadow_cannot_change_existing_decisions(self):
  for context in self.p["contexts"]:
   for fixture in (
    {"objectID":"s1","comment_text":m.v2.POSITIVE_TEXT},
    {"objectID":"s2","title":"New release notes and features"},
   ):
    old=m.legacy_content_stage(fixture)
    shadow=m.context_overlay(context,old)
    self.assertFalse(shadow["changed"])
    self.assertEqual(shadow["stage"],old["stage"])
 def test_aggregates_have_no_individual_payload(self):
  items=[
   {"objectID":"fake1","story_id":"t1","comment_text":m.v2.POSITIVE_TEXT},
   {"objectID":"fake1","story_id":"t1","comment_text":m.v2.POSITIVE_TEXT},
   {"objectID":"fake2","story_id":"t2","comment_text":"New release notes about spreadsheet apps"}
  ]
  for context in self.p["contexts"]:
   result=m.compare_rows(context,items)
   self.assertEqual(result["examined"],2)
   self.assertEqual(set(result),set(m.OUT_KEYS))
   self.assertEqual(result["passes_content_only"],1)
   self.assertEqual(result["family_and_buyer"],1)
   self.assertEqual(result["review_flags"],1)
   self.assertEqual(sum(result[k] for k in m.STAGES),2)
 def test_external_source_unavailability_not_a_zero_win(self):
  x=m.compare_rows("show_hn_projects",[])
  self.assertEqual(x["examined"],0)
  self.assertNotIn("inconclusive",m.P.read_text().lower())
 def test_no_network_in_unit_tests_and_no_implicit_write(self):
  source=SRC.read_text()
  self.assertNotIn("trigger_deploy(",source)
  self.assertNotIn("replace_evidence_memory(",source)
  self.assertNotIn("run_pipeline(",source)
  self.assertIn('"strict_topic_relevance_evaluated":False',source)

if __name__=="__main__":
 unittest.main()
