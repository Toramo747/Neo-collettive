"""Offline test of the champion shadow harness (no network)."""
import asyncio
import importlib.util
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
_spec = importlib.util.spec_from_file_location("shadow", Path(__file__).parent / "tools" / "research_champion_shadow.py")
shadow = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(shadow)


class ShadowTests(unittest.TestCase):
    def test_champion_queries_match_arena_builder_on_training(self):
        import arena_research_algorithm as arena
        built = [q for _, q in arena.build_queries(shadow.CHAMPION)]
        mine = [q for t, c in shadow.TRAINING.items() for q in shadow.champion_queries(c)]
        self.assertEqual(built, mine)

    def test_holdout_disjoint_from_training(self):
        self.assertFalse(set(shadow.HOLDOUT) & set(shadow.TRAINING))

    def test_budgets(self):
        self.assertEqual(sum(h for _, _, h in shadow.arm_plan("CHAMP", "x", "x")), 120)
        self.assertEqual(sum(h for _, _, h in shadow.arm_plan("PROD_EQ", "x", "x")), 120)
        self.assertEqual(shadow.arm_plan("PROD", "invoice reconciliation", "c"), [("invoice reconciliation", "story", 3)])

    def test_run_aggregates_without_text(self):
        async def fake(client, query, tag, hits, cutoff):
            return [{"story_id": f"{query}-{i}", "title": "invoice reconciliation is a painful problem, we would pay for a tool",
                     "comment_text": "I hate doing this manually"} for i in range(min(hits, 2))]
        original = shadow.fetch
        shadow.fetch = fake
        try:
            res = asyncio.run(shadow.run())
        finally:
            shadow.fetch = original
        self.assertIn("holdout:CHAMP", res)
        self.assertNotIn("_threads", res["training:CHAMP"])
        self.assertIn("champ_only", res["training:overlap"])


if __name__ == "__main__":
    unittest.main()
