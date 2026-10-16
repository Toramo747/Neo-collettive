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


    def test_train_build_compiles_and_eval_rule(self):
        with tempfile.TemporaryDirectory() as d:
            dd = Path(d) / "market-intuition" / "distill"
            dd.mkdir(parents=True)
            rows = [{"person": f"p{i}", "need": f"I need tool {i}", "label": {"real_need": i % 2 == 0, "problem": "aa bb", "would_pay": "unknown"}} for i in range(12)]
            (dd / "train.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
            (dd / "holdout.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows[:6]))
            k = Path(d) / "k"
            self.assertEqual(md.train_build(d, str(k), "u"), 0)
            src = (k / "main.py").read_text()
            compile(src, "main.py", "exec")
            header = src.split("\nimport json, os, random", 1)[0]
            ns = {}
            exec(header, ns)            # booleans in labels must load (v1 wrote JSON 'false' as Python)
            self.assertIs(ns["INPUT"]["train"][1]["label"]["real_need"], False)
            self.assertIn("You review sentences people wrote online", src)
            spec = importlib.util.spec_from_file_location("ev", Path(__file__).with_name("tools") / "mi_distill_eval.py")
            ev = importlib.util.module_from_spec(spec); spec.loader.exec_module(ev)
            def gen(model, prompt, schema):
                n = len(prompt.split("\n\n")[-1].splitlines())
                real = model == "student"
                return {"verdicts": [{"i": i, "real_need": real and i % 2 == 0, "problem": "aa bb", "would_pay": "unknown"} for i in range(n)]}
            out = ev.run(d, "base", "student", gen=gen)
            self.assertEqual(out["student"]["f1"], 1.0)
            self.assertTrue(out["decision"]["machine_pass"])
            self.assertTrue((dd / "spot_check_for_andrea.jsonl").exists())

    def test_v2_archives_v1_reuses_it_for_training_only(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "market-intuition").mkdir()
            (Path(d) / "market-intuition" / "state.json").write_text(json.dumps({"vocabulary": {"invoices": 2.0}}))
            dd = Path(d) / "market-intuition" / "distill"
            dd.mkdir()
            v1 = [{"id": f"o{i}", "person": f"old{i}", "need": "n", "label": {"real_need": True}} for i in range(5)]
            (dd / "candidates.jsonl").write_text("x\n")
            (dd / "train.jsonl").write_text("".join(json.dumps(r) + "\n" for r in v1[:4]))
            (dd / "holdout.jsonl").write_text(json.dumps(v1[4]) + "\n")
            self.assertEqual(md.harvest(d, max_queries=1000, getter=getter), 0)
            self.assertTrue((dd / "v1" / "train.jsonl").exists())
            cands = [json.loads(l) for l in (dd / "candidates.jsonl").read_text().splitlines()]
            out = Path(d) / "labels.json"
            out.write_text(json.dumps({"labels": [{"id": c["id"], "judged": True, "real_need": True} for c in cands]}))
            md.label_collect(d, str(out))
            tr = [json.loads(l) for l in (dd / "train.jsonl").read_text().splitlines()]
            ho = [json.loads(l) for l in (dd / "holdout.jsonl").read_text().splitlines() if l.strip()]
            self.assertEqual(sum(1 for r in tr if r["person"].startswith("old")), 5)
            self.assertFalse(any(r["person"].startswith("old") for r in ho))

    def test_v2_rule_needs_fpr_cut_and_kept_recall(self):
        spec = importlib.util.spec_from_file_location("ev2", Path(__file__).with_name("tools") / "mi_distill_eval.py")
        ev = importlib.util.module_from_spec(spec); spec.loader.exec_module(ev)
        base = {"fpr": 0.254, "recall": 0.742, "f1": 0.616}
        v1_student = {"fpr": 0.145, "recall": 0.621, "f1": 0.621}
        self.assertFalse(ev.decide(base, v1_student)["machine_pass"])
        good = {"fpr": 0.14, "recall": 0.70, "f1": 0.63}
        self.assertTrue(ev.decide(base, good)["machine_pass"])


if __name__ == "__main__":
    unittest.main()
