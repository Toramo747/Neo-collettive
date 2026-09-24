import unittest
from thesis_control import exhausted_seed_blocked, finalize_exhausted_thesis


class ThesisControlTests(unittest.TestCase):
    def test_exhausted_seed_is_blocked_inside_cooldown(self):
        history=[{"status":"EXHAUSTED","seed_problem_key":"manual_data_entry:x","closed_at_cycle":100}]
        self.assertTrue(exhausted_seed_blocked(history,"manual_data_entry:x",105,12))

    def test_exhausted_seed_reopens_after_cooldown(self):
        history=[{"status":"EXHAUSTED","seed_problem_key":"manual_data_entry:x","closed_at_cycle":100}]
        self.assertFalse(exhausted_seed_blocked(history,"manual_data_entry:x",112,12))

    def test_other_seed_not_blocked(self):
        history=[{"status":"EXHAUSTED","seed_problem_key":"manual_data_entry:x","closed_at_cycle":100}]
        self.assertFalse(exhausted_seed_blocked(history,"integration_api:y",101,12))

    def test_non_exhausted_history_does_not_block(self):
        history=[{"status":"COMPLETE","seed_problem_key":"manual_data_entry:x","closed_at_cycle":100}]
        self.assertFalse(exhausted_seed_blocked(history,"manual_data_entry:x",101,12))

    def test_mechanical_buyer_prefix_drift_is_blocked(self):
        history=[{
            "status":"EXHAUSTED",
            "seed_problem_key":"manual_data_entry:buyers:manual_data_entry",
            "closed_at_cycle":290,
        }]
        self.assertTrue(
            exhausted_seed_blocked(
                history,
                "manual_data_entry:buyers:buyers_manual_data_entry",
                292,
                12,
            )
        )

    def test_finalize_closes_exactly_at_budget(self):
        active={"status":"ACTIVE","cycles_used":4,"budget_cycles":4,"thesis_id":"t1"}
        result=finalize_exhausted_thesis(active,quality_gate=False,closed_at_cycle=299)
        self.assertTrue(result["closed"])
        self.assertIsNone(result["active"])
        self.assertEqual(result["finished"]["status"],"EXHAUSTED")
        self.assertEqual(result["finished"]["closed_at_cycle"],299)

    def test_finalize_does_not_close_before_budget(self):
        active={"status":"ACTIVE","cycles_used":3,"budget_cycles":4,"thesis_id":"t1"}
        result=finalize_exhausted_thesis(active,quality_gate=False,closed_at_cycle=299)
        self.assertFalse(result["closed"])

    def test_finalize_never_exhausts_passed_gate(self):
        active={"status":"ACTIVE","cycles_used":4,"budget_cycles":4,"thesis_id":"t1"}
        result=finalize_exhausted_thesis(active,quality_gate=True,closed_at_cycle=299)
        self.assertFalse(result["closed"])

    def test_real_different_problem_is_not_blocked(self):
        history=[{
            "status":"EXHAUSTED",
            "seed_problem_key":"manual_data_entry:buyers:manual_data_entry",
            "closed_at_cycle":290,
        }]
        self.assertFalse(
            exhausted_seed_blocked(
                history,
                "manual_data_entry:buyers:invoice_reconciliation",
                292,
                12,
            )
        )


if __name__=="__main__":
    unittest.main()
