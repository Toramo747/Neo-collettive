import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

_spec = importlib.util.spec_from_file_location("mi_distill", Path(__file__).with_name("tools") / "mi_distill.py")
md = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(md)


def getter(url):
    return {"hits": [
        {"objectID": "1", "story_id": "9", "author": "a", "created_at": "2026-10-01T00:00:00Z",
         "comment_text": "I spend hours every week reconciling invoices manually, is there a tool for invoices?"},
        {"objectID": "2", "story_id": "9", "author": "b", "created_at": "2026-10-01T00:00:00Z",
         "comment_text": "Our team struggles with invoices every month."}]}


class DistillTests(unittest.TestCase):
    def test_harvest_label_collect_split_by_person(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "market-intuition").mkdir()
            (Path(d) / "market-intuition" / "state.json").write_text(json.dumps({"vocabulary": {"invoices": 2.0}}))
            self.assertEqual(md.harvest(d, max_queries=1000, getter=getter), 0)
            cands = [json.loads(l) for l in (Path(d) / "market-intuition/distill/candidates.jsonl").read_text().splitlines()]
            self.assertEqual(len({c["person"] for c in cands}), len(cands))
            self.assertGreaterEqual(len(cands), 1)
            k = Path(d) / "k"
            self.assertEqual(md.label_build(d, str(k), "u"), 0)
            compile((k / "main.py").read_text(), "main.py", "exec")
            self.assertTrue(json.loads((k / "kernel-metadata.json").read_text())["is_private"])
            out = Path(d) / "labels.json"
            out.write_text(json.dumps({"labels": [{"id": c["id"], "judged": True, "real_need": True, "problem": "x y",
                                                   "would_pay": "unknown"} for c in cands]}))
            self.assertEqual(md.label_collect(d, str(out)), 0)
            tr = (Path(d) / "market-intuition/distill/train.jsonl").read_text().splitlines()
            ho = (Path(d) / "market-intuition/distill/holdout.jsonl").read_text().splitlines()
            self.assertEqual(len(tr) + len(ho), len(cands))
            ptr = {json.loads(l)["person"] for l in tr}
            pho = {json.loads(l)["person"] for l in ho}
            self.assertFalse(ptr & pho)


if __name__ == "__main__":
    unittest.main()
