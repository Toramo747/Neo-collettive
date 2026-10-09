# SPDX-License-Identifier: BUSL-1.1
"""Non-network smoke tests for gamete-to-native-evaluator wiring."""
import json
import unittest
from pathlib import Path
from unittest.mock import patch
from scripts.evaluate_arena_gametes import evaluate_pack, require_isolation, DATA_DIR, PACK_PATH

class ArenaGameteOfflineEvaluationTests(unittest.TestCase):
    def test_all_ten_are_assessed_without_side_effects(self):
        paths = sorted(str(p) for p in DATA_DIR.rglob("*.json"))
        before = {p: Path(p).read_bytes() for p in paths}
        with patch("socket.socket.connect", side_effect=AssertionError("network disallowed")), patch(
            "socket.socket.connect_ex", side_effect=AssertionError("network disallowed")
        ):
            result = evaluate_pack()
        self.assertEqual(10, result["gametes_total"])
        self.assertEqual(0, result["measured_live_provider_rounds"])
        self.assertFalse(result["production_promoted"])
        self.assertEqual([], result["automatic_winners"])
        self.assertEqual("NONE", result["commercial_gate_influence"])
        self.assertEqual(10, len({r["id"] for r in result["results"]}))
        self.assertEqual(before, {p: Path(p).read_bytes() for p in paths})

    def test_guards_fail_closed(self):
        source = json.loads(PACK_PATH.read_text(encoding="utf-8"))
        source["boundary"]["network_calls"] = True
        with self.assertRaises(ValueError):
            require_isolation(source)

    def test_read_only_results_are_distinct_from_real_qualification(self):
        report = evaluate_pack()
        by_id = {r["id"]: r for r in report["results"]}
        self.assertTrue(by_id["CM-03"]["status"].startswith("HOLD"))
        self.assertEqual("HOLD_INSUFFICIENT_PROPOSALS", by_id["CM-04"]["status"])
        for name in ("LLM-01","LLM-02","LLM-03"):
            self.assertEqual("PROMPT_COMPILED_UNMEASURED", by_id[name]["status"])
        for name in ("WARP-01","WARP-02"):
            self.assertEqual("HEURISTIC_ONLY", by_id[name]["status"])
            self.assertFalse(by_id[name]["physical_feasibility_established"])
        self.assertEqual("QUERY_COMPILED_UNMEASURED", by_id["ALG-01"]["status"])
        self.assertFalse(any(r.get("production_promoted") for r in report["results"]))

if __name__ == "__main__":
    unittest.main()
