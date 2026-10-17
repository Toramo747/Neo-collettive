import unittest

import cloud_mcp


class CouncilHistoryBound(unittest.TestCase):
    def test_only_newest_entries_keep_full_text(self):
        big = [{"generated_at_utc": str(i), "top5": [{"tool_name": "t", "blob": "x" * 5000}],
                "transcripts": [{"opportunity": "t", "decision": "go", "debate": "y" * 20000}]} for i in range(20)]
        out = cloud_mcp._bound_council_history(big)
        self.assertEqual(len(out), 20)
        self.assertEqual(out[-1], big[-1])
        self.assertEqual(out[-3], big[-3])
        self.assertTrue(out[0]["summarized"])
        self.assertEqual(out[0]["transcripts"][0]["decision"], "go")
        self.assertNotIn("debate", out[0]["transcripts"][0])
        self.assertEqual(cloud_mcp._bound_council_history(out), out)  # idempotent


if __name__ == "__main__":
    unittest.main()
