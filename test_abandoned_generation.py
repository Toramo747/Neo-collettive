import unittest
from datetime import datetime, timedelta, timezone

from state_generation_guard import check_write_allowed

NOW = datetime(2026, 10, 14, 2, 0, tzinfo=timezone.utc)


def saved(gen, age_s, writer="other"):
    return {"state_generation": gen, "state_writer_id": writer,
            "last_checkpoint": {"checkpoint_utc": (NOW - timedelta(seconds=age_s)).isoformat()}}


def run(loaded, payload, writer="me"):
    return check_write_allowed(loaded, "x", lambda _v: payload, writer, now=NOW)


class AbandonedGenerationTests(unittest.TestCase):
    def test_recent_newer_writer_still_blocks(self):
        g = run(10, saved(12, 60))
        self.assertFalse(g["allowed"])
        self.assertEqual(g["status"], "stale_generation_write_blocked")

    def test_old_newer_writer_stays_blocked(self):
        g = run(10, saved(12, 24 * 3600))
        self.assertFalse(g["allowed"])
        self.assertEqual(g["status"], "stale_generation_write_blocked")
        self.assertEqual(g["loaded_generation"], 10)

    def test_missing_timestamp_stays_blocked(self):
        g = run(10, {"state_generation": 12, "state_writer_id": "other"})
        self.assertFalse(g["allowed"])

    def test_own_write_and_equal_generation_unchanged(self):
        self.assertEqual(run(10, saved(12, 5, writer="me"))["status"], "own_write_adopted")
        self.assertEqual(run(12, saved(12, 5))["status"], "ok")


if __name__ == "__main__":
    unittest.main()
