import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "tools"))
import commons_log_witness as c  # noqa: E402


def make(n, tamper=None):
    rows, h = [], "0" * 64
    for i in range(n):
        content = hashlib.sha256(f"body {i if i != tamper else 'x'}".encode()).hexdigest()
        row = [i, 1000 + i, "message", f"id{i}", content]
        h = hashlib.sha256((h + c.js(row)).encode()).hexdigest()
        rows.append({"seq": i, "createdAt": 1000 + i, "kind": "message", "id": f"id{i}", "content": content, "h": h})
    return rows, {"size": n, "head": h}


class CommonsWatchTest(unittest.TestCase):
    def run_watch(self, served, hist):
        c.fetch_all = lambda: served
        c.content_ok = lambda i, x: True
        return c.watch(str(hist))

    def test_growth_is_fine_rewrite_is_caught(self):
        with tempfile.TemporaryDirectory() as d:
            hist = Path(d) / "h.jsonl"
            self.assertEqual(self.run_watch(make(5), hist), 0)
            self.assertEqual(self.run_watch(make(8), hist), 0)       # appended rows: same prefixes
            self.assertEqual(self.run_watch(make(8, tamper=2), hist), 1)  # row 2 changed: earlier heads differ
            self.assertEqual(len(hist.read_text().splitlines()), 3)

    def test_served_head_must_match(self):
        rows, meta = make(4)
        meta["head"] = "f" * 64
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(self.run_watch((rows, meta), Path(d) / "h.jsonl"), 1)


if __name__ == "__main__":
    unittest.main()
