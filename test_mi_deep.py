import json
import tempfile
import unittest
from pathlib import Path

import arena_market_intuition as a
import importlib.util

_spec = importlib.util.spec_from_file_location("mi_deep", Path(__file__).with_name("tools") / "mi_deep.py")
mi_deep = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mi_deep)


class DeepMindTests(unittest.TestCase):
    def test_apply_deep_overrides_merges_and_learns(self):
        state = {"generation": 12, "market_map": {
            "invoice reconcile": {"people": 2, "pay": 0, "persons": ["p1", "p2"]},
            "reconciling invoices": {"people": 1, "pay": 0, "persons": ["p3"]},
            "noise thing": {"people": 1, "pay": 0, "persons": ["p4"]}},
            "deep_queue": [{"person": "p4", "need": "x"}, {"person": "p5", "need": "y"}],
            "vocabulary": {"crm": 1.0}}
        inbox = {"run_id": "r1", "model": "m", "minutes": 30, "verdicts": [
            {"person": "p4", "real_need": False, "problem": "", "would_pay": "no"},
            {"person": "p5", "real_need": True, "problem": "invoice reconcile", "would_pay": "yes"}],
            "thought": {"observation": "o", "hypothesis": "h", "merges": [{"from": "reconciling invoices", "into": "invoice reconcile"}],
                        "next_terms": ["bank feeds"], "abandon_terms": ["crm"], "next_phrases": ["we do it by hand"]}}
        st = a.apply_deep(state, inbox)
        self.assertNotIn("noise thing", st["market_map"])
        self.assertNotIn("reconciling invoices", st["market_map"])
        self.assertEqual(st["market_map"]["invoice reconcile"]["people"], 4)
        self.assertEqual(st["market_map"]["invoice reconcile"]["pay"], 1)
        self.assertEqual(st["deep_queue"], [])
        self.assertIn("p5", st["deep_judged"])
        self.assertEqual(st["vocabulary"]["bank feeds"], 4.0)
        self.assertLess(st["vocabulary"]["crm"], 1.0)
        self.assertTrue(st["diary"][-1].startswith("DEEP gen 12"))
        self.assertEqual(st["deep_log"][-1]["real"], 1)

    def test_build_collect_quota(self):
        with tempfile.TemporaryDirectory() as d:
            base = Path(d) / "market-intuition"
            base.mkdir()
            (base / "state.json").write_text(json.dumps({"deep_queue": [{"person": "p1", "need": "I need X"}],
                                                         "market_map": {"x": {"people": 1, "pay": 0, "persons": ["p1"]}}}))
            k = Path(d) / "kernel"
            self.assertEqual(mi_deep.build(d, str(k), "user"), 0)
            meta = json.loads((k / "kernel-metadata.json").read_text())
            self.assertTrue(meta["is_private"] and meta["enable_gpu"])
            src = (k / "mind.py").read_text()
            self.assertNotIn("persons", src)   # only counts of the map travel, not people lists
            compile(src, "mind.py", "exec")
            out = Path(d) / "deep.json"
            out.write_text(json.dumps({"verdicts": [{"person": "p1", "real_need": True}], "thought": {}}))
            self.assertEqual(mi_deep.collect(d, str(out), "31"), 0)
            self.assertEqual(len(list((base / "deep_inbox").glob("*.json"))), 1)
            self.assertEqual(mi_deep.quota(d), 0)
            usage = json.loads((base / "deep_usage.json").read_text())
            usage[list(usage)[0]] = 25 * 60
            (base / "deep_usage.json").write_text(json.dumps(usage))
            self.assertEqual(mi_deep.quota(d), 1)

    def test_empty_queue_skips(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "market-intuition").mkdir()
            (Path(d) / "market-intuition" / "state.json").write_text("{}")
            self.assertEqual(mi_deep.build(d, str(Path(d) / "k"), "u"), 3)


if __name__ == "__main__":
    unittest.main()
