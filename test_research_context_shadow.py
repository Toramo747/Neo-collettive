"""Pure synthetic triage tests; no source records or personal data in repository."""
import importlib.util
import unittest
from pathlib import Path
P=Path("experiments/research-context-shadow/audit.py")
spec=importlib.util.spec_from_file_location("oxibay_context_shadow",P)
m=importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

class ContextShadowTests(unittest.TestCase):
 def setUp(self):self.p=m.load()
 def test_policy(self):
  self.assertEqual(len(self.p["contexts"]),2)
  self.assertEqual(self.p["max_requests"],4)
  self.assertFalse(self.p["boundary"]["source_ids_to_artifact"])
  self.assertFalse(self.p["boundary"]["raw_text_to_artifact"])
  self.assertFalse(self.p["boundary"]["automatic_promotion"])
 def test_employment_supply_confounded_buyer_phrases(self):
  self.assertEqual(m.review_priority("employment_supply",buyer=True,family=True),
                   "SUPPLY_CONTEXT_REVIEW")
  self.assertEqual(m.review_priority("employment_supply",buyer=False,family=False),
                   "LOW_PRIORITY_CONTEXT")
 def test_project_showcase_is_not_blindly_rejected(self):
  self.assertEqual(m.review_priority("project_showcase",buyer=True,family=True),
                   "MIXED_CONTEXT_REVIEW")
  self.assertEqual(m.review_priority("project_showcase",buyer=False,family=False),
                   "MIXED_CONTEXT_NO_ASSUMED_DEMAND")
 def test_source_text_never_returned_in_aggregates(self):
  hits=[
   {"objectID":"synthetic1","title":"I need a spreadsheet tool to automate my work",
    "comment_text":"Manual entry of invoices is frustrating and slow"},
   {"objectID":"synthetic1","title":"repeated item, should be ignored"},
   {"objectID":"synthetic2","title":"Built a new tool for our community",
    "comment_text":"Try this service with a demo"},
  ]
  result=m.analyze_public_records("project_showcase",hits,self.p)
  self.assertEqual(result["examined"],2)
  self.assertEqual(set(result),{"examined","buyer_voice_heuristic",
    "commercial_family_heuristic","vendor_or_supply_heuristic",
    "review_priority_SUPPLY_CONTEXT_REVIEW","review_priority_LOW_PRIORITY_CONTEXT",
    "review_priority_MIXED_CONTEXT_REVIEW",
    "review_priority_MIXED_CONTEXT_NO_ASSUMED_DEMAND"})
  self.assertNotIn("spreadsheet",str(result))
 def test_unknown_context_fails_closed(self):
  with self.assertRaises(ValueError):m.review_priority("unknown",buyer=True)
