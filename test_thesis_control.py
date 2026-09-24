import unittest
from thesis_control import exhausted_seed_blocked


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


if __name__=="__main__":
    unittest.main()
