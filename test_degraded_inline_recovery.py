import unittest

import cloud_mcp


class DegradedInlineRecovery(unittest.TestCase):
    def test_guard_block_with_inline_store_is_recoverable(self):
        st = {"evidence_store_degraded": True,
              "evidence_store_status": {"status": "degraded", "reason": "stale_generation_write_blocked"}}
        self.assertTrue(cloud_mcp._guard_block_degraded_is_recoverable(st, None))

    def test_external_store_degraded_is_not_touched(self):
        st = {"evidence_store_degraded": True,
              "evidence_store_status": {"reason": "stale_generation_write_blocked"}}
        ext = {"external_store": "render_env", "generation": "abc", "chunks": 1, "evidence_count": 3, "sha256": "x"}
        if cloud_mcp.is_external_reference(ext):
            self.assertFalse(cloud_mcp._guard_block_degraded_is_recoverable(st, ext))

    def test_other_degraded_reasons_are_not_touched(self):
        st = {"evidence_store_degraded": True, "evidence_store_status": {"reason": "external_store_read_failed"}}
        self.assertFalse(cloud_mcp._guard_block_degraded_is_recoverable(st, None))
        self.assertFalse(cloud_mcp._guard_block_degraded_is_recoverable({"evidence_store_degraded": False,
                         "evidence_store_status": {"reason": "stale_generation_write_blocked"}}, None))


if __name__ == "__main__":
    unittest.main()
