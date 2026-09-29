from __future__ import annotations

import json
import random
import tempfile
import unittest
from pathlib import Path

from arena.commercial_signal.evaluate import load_proposal
from arena.commercial_signal.evolve import complexity, mutate
from arena.commercial_signal.judge import marker_ceiling
from arena.commercial_signal.prepare_evolve_train import build_train

ROOT = Path("arena/commercial_signal")


class EvolutionTests(unittest.TestCase):
    def test_initial_holdout_is_stratified_and_large_enough(self):
        rows = [json.loads(x) for x in (ROOT / "holdout_evolve.jsonl").read_text().splitlines() if x.strip()]
        counts = {}
        for row in rows:
            counts[row["proposed_label"]] = counts.get(row["proposed_label"], 0) + 1
        self.assertEqual(counts, {"REAL_DEMAND": 2, "VENDOR_OR_SELLER": 2, "NOISE": 2})
        self.assertGreaterEqual(len(rows) / 12.0, 0.30)

    def test_prepare_train_excludes_fixed_holdout_ids(self):
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "train.jsonl"
            summary = build_train(ROOT / "train_real.jsonl", ROOT / "evolve_holdout_manifest.json", out)
            rows = [json.loads(x) for x in out.read_text().splitlines() if x.strip()]
            held = set(json.loads((ROOT / "evolve_holdout_manifest.json").read_text())["holdout_ids"])
            self.assertFalse(any(r["id"] in held for r in rows))
            self.assertEqual(summary["train_cases"], 6)

    def test_mutation_is_deterministic_and_schema_valid(self):
        baseline = load_proposal(ROOT / "proposals/baseline.json")
        a = mutate(
            baseline,
            random.Random(7),
            baseline["vendor_exclusion"]["markers"],
            baseline["vendor_exclusion"]["source_types"],
            1,
        )
        b = mutate(
            baseline,
            random.Random(7),
            baseline["vendor_exclusion"]["markers"],
            baseline["vendor_exclusion"]["source_types"],
            1,
        )
        self.assertEqual(a, b)
        self.assertGreater(complexity(a), 0)

    def test_marker_ceiling_is_bounded(self):
        rows = [json.loads(x) for x in (ROOT / "holdout_evolve.jsonl").read_text().splitlines() if x.strip()]
        proposals = [load_proposal(p) for p in sorted((ROOT / "proposals").glob("*.json"))]
        value = marker_ceiling(rows, proposals)
        self.assertGreaterEqual(value, 0.0)
        self.assertLessEqual(value, 1.0)


if __name__ == "__main__":
    unittest.main()
