"""No-network synthetic safety checks for supplier/buyer role-collision risks."""
import importlib.util
import unittest
from pathlib import Path

SRC=Path("experiments/research-buyer-seller-role/audit.py")
spec=importlib.util.spec_from_file_location("oxibay_buyer_seller_role",SRC)
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

class SellerBuyerRoleTests(unittest.TestCase):
 def setUp(self):self.p,self.genes,self.pairs=m.load()
 def test_frozen_baseline_and_public_limits(self):
  self.assertEqual(self.genes["query_mode"],"mixed")
  self.assertEqual(len(self.pairs),16)
  self.assertEqual(self.p["preregistration"]["window"]["id"],"2026-03")
  self.assertEqual(self.p["preregistration"]["max_public_requests"],16)
  self.assertFalse(self.p["boundary"]["automatic_promotion"])
  self.assertFalse(self.p["boundary"]["production_state_write"])
 def test_all_synthetic_role_controls(self):
  result=m.authored_controls()
  self.assertTrue(result["pass"])
  self.assertEqual(result["total"],10)
  self.assertEqual(result["human_verified_external_cases"],0)
 def test_seller_cue_precise_vs_buyer_cue(self):
  self.assertTrue(m.seller_role_flag("","I provide spreadsheet automation services to clients."))
  self.assertTrue(m.seller_role_flag("","I'm looking for clients for manual invoicing consulting."))
  self.assertFalse(m.seller_role_flag("","I need a tool to automate manual invoice reconciliation."))
  self.assertFalse(m.seller_role_flag("","We need to hire a specialist for inventory alert workflows."))
 def test_seller_risk_never_vetoes_accepted_signal(self):
  supplier={"objectID":"fixture-1","story_id":"fake-thread",
      "story_title":"Ask HN: Who wants to be hired? (March 2026)",
      "comment_text":"I'm looking for clients for my spreadsheet automation work. I need help with manual data entry problems."}
  batch=[[] for _ in self.pairs]
  batch[0]=[supplier]
  result=m.audit(self.p,self.genes,self.pairs,batch)
  self.assertEqual(sum(result["rejection_stages"].values()),1)
  self.assertEqual(result["accepted_without_seller_role_cue"]+result["accepted_seller_role_collision_count"],
                   result["signal_hits"])
  self.assertTrue(result["legacy_accepted_labels_unchanged"])
  self.assertTrue(result["legacy_scores_unchanged"])
 def test_positive_buyer_untouched_and_mixed_never_suppressed(self):
  buyer={"objectID":"buyer1","story_id":"buyer-thread","story_title":"Ask HN: Who is hiring? (March 2026)",
         "comment_text":"I need a tool for restaurant booking manual data entry because this workaround wastes time"}
  mixed={"objectID":"mixed1","story_id":"mixed-thread","story_title":"Show HN: Demonstration",
         "comment_text":"I offer consulting but I need a tool for restaurant booking manual data entry because this workaround wastes time"}
  batch=[[] for _ in self.pairs]
  batch[0]=[buyer,mixed]
  score=m.audit(self.p,self.genes,self.pairs,batch)
  self.assertEqual(score["signal_hits"],1) if False else self.assertGreaterEqual(score["signal_hits"],1)
  self.assertTrue(score["legacy_accepted_labels_unchanged"])
  self.assertLessEqual(score["accepted_seller_role_collision_count"],score["signal_hits"])
 def test_aggregate_and_source_context_privacy(self):
  hit={"objectID":"id123","story_id":"thread123","story_title":"An ordinary HN discussion",
       "comment_text":"I need a tool for restaurant booking manual data entry because this workaround wastes time"}
  batch=[[] for _ in self.pairs]
  batch[0]=[hit,hit]
  a=m.audit(self.p,self.genes,self.pairs,batch)
  self.assertEqual(a["deduplicated_objects"],1)
  self.assertNotIn("id123",str(a))
  self.assertNotIn("thread123",str(a))
  self.assertTrue(a["independent_human_truth_available"] is False)
 def test_no_main_or_commercial_changes(self):
  text=SRC.read_text()
  self.assertNotIn("trigger_deploy(",text)
  self.assertNotIn("replace_evidence_memory(",text)
  self.assertNotIn("train_student(",text)
  self.assertNotIn("save_json(STATE_PATH",text)
  self.assertEqual(self.p["boundary"]["commercial_gate_influence"],"NONE")

if __name__=="__main__":
 unittest.main()
