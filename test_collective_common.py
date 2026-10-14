import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

sys.path.insert(0, "tools")
import collective_common as c  # noqa: E402


class CollectiveCommonTests(unittest.TestCase):
    def test_post_caps_per_day_and_is_idempotent(self):
        sent = []
        with tempfile.TemporaryDirectory() as d:
            now = datetime(2026, 10, 14, 9, tzinfo=timezone.utc)
            c.post(d, now, sender=lambda p: sent.append(p) or 200)
            c.post(d, now, sender=lambda p: sent.append(p) or 200)
            self.assertEqual(len(sent), c.POSTS_PER_DAY)
            st = json.loads((Path(d) / "collective" / "state.json").read_text())
            self.assertTrue(all(p["job_id"].startswith("post_a2a-neo-job-") for p in st["posted"]))
            self.assertIn("[collective-mind]", sent[0]["params"]["message"]["parts"][0]["text"])
            c.post(d, datetime(2026, 10, 15, 9, tzinfo=timezone.utc), sender=lambda p: sent.append(p) or 200)
            self.assertEqual(len(sent), 2 * c.POSTS_PER_DAY)

    def test_collect_verifies_and_scores(self):
        with tempfile.TemporaryDirectory() as d:
            c.post(d, datetime(2026, 10, 14, 9, tzinfo=timezone.utc), sender=lambda p: 200)
            st = json.loads((Path(d) / "collective" / "state.json").read_text())
            sig = next(p["job_id"] for p in st["posted"] if p["kind"] == "signal")
            entries = {"entries": [
                {"id": "r1", "agent": "a", "supersedes": sig, "relation": "result",
                 "body": 'Item 1: Link: https://example.org/t/1 Exact quote: "our agent got worse and nobody noticed"'},
                {"id": "r2", "agent": "b", "supersedes": "other-job", "relation": "result", "body": "x"}]}
            page = {"kind": "web", "parts": [{"by_opener": None, "text": "Our agent got worse and nobody noticed for weeks"}]}
            with mock.patch.object(c.verify_quotes, "fetch", return_value=page):
                c.collect(d, fetch=lambda url: entries)
                c.collect(d, fetch=lambda url: entries)   # same reply twice: counted once
            trial = json.loads((Path(d) / "collective" / "trial.json").read_text())
            self.assertEqual(trial["verified_items"], 1)
            self.assertEqual(trial["agents"], ["a"])


if __name__ == "__main__":
    unittest.main()
