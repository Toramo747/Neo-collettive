import importlib.util, unittest
from datetime import datetime, timezone

spec = importlib.util.spec_from_file_location("mwp", "tools/mcp_watch_pilot.py")
mwp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mwp)


class OneRunPerUtcDay(unittest.TestCase):
    def test_empty_state_runs(self):
        self.assertFalse(mwp.already_ran_today({"days": []}))

    def test_same_utc_date_is_skipped(self):
        now = datetime(2026, 10, 27, 8, 16, tzinfo=timezone.utc)
        state = {"days": [{"day": 2, "utc": "2026-10-27T08:03"}]}
        self.assertTrue(mwp.already_ran_today(state, now))

    def test_next_utc_date_runs(self):
        now = datetime(2026, 10, 28, 0, 5, tzinfo=timezone.utc)
        state = {"days": [{"day": 3, "utc": "2026-10-27T23:50"}]}
        self.assertFalse(mwp.already_ran_today(state, now))


if __name__ == "__main__":
    unittest.main()
