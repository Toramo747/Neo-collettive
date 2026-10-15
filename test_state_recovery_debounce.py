import unittest
from unittest import mock

import cloud_mcp


class LocalStateDebounceTests(unittest.TestCase):
    def setUp(self):
        self.saved = cloud_mcp._LAST_LOCAL_STATE_SAVE
        cloud_mcp._LAST_LOCAL_STATE_SAVE = 0.0

    def tearDown(self):
        cloud_mcp._LAST_LOCAL_STATE_SAVE = self.saved

    def test_repeated_saves_within_interval_write_once(self):
        with mock.patch.object(cloud_mcp, "_write_local_state") as write:
            for _ in range(5):
                cloud_mcp._save_local_state()
        self.assertEqual(write.call_count, 1)

    def test_forced_save_always_writes(self):
        with mock.patch.object(cloud_mcp, "_write_local_state") as write:
            cloud_mcp._save_local_state()
            cloud_mcp._save_local_state(force=True)
        self.assertEqual(write.call_count, 2)

    def test_save_after_interval_writes_again(self):
        with mock.patch.object(cloud_mcp, "_write_local_state") as write, \
             mock.patch.object(cloud_mcp.time, "monotonic", side_effect=[1000.0, 1000.0 + cloud_mcp.LOCAL_STATE_MIN_INTERVAL_SECONDS + 1]):
            cloud_mcp._save_local_state()
            cloud_mcp._save_local_state()
        self.assertEqual(write.call_count, 2)

    def test_cycle_end_forces_local_save(self):
        src = open("cloud_mcp.py", encoding="utf-8").read()
        self.assertIn("_save_local_state(force=True)\n            AUTOPILOT_STATE[\"last_checkpoint\"]", src)


if __name__ == "__main__":
    unittest.main()
