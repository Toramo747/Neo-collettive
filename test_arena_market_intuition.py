import json
import random
import unittest

import arena_market_intuition as a


def fake_getter(url):
    if "algolia" in url:
        return {"hits": [
            {"objectID": "1", "story_id": "9", "author": "alice", "created_at": "2026-10-01T00:00:00Z",
             "comment_text": "I spend hours every week reconciling invoices manually, I would pay for a fix"},
            {"objectID": "2", "story_id": "9", "author": "bob", "created_at": "2026-09-01T00:00:00Z",
             "comment_text": "We waste a day each month on invoices reconciliation, is there a tool?"},
            {"objectID": "3", "story_id": "8", "author": "carol", "created_at": "2026-08-01T00:00:00Z",
             "comment_text": "Our team struggles with invoices reconciliation every close"},
            {"objectID": "4", "story_id": "7", "author": "vendor", "created_at": "2026-10-01T00:00:00Z",
             "title": "Show HN: we built an invoices bot", "story_text": "Sign up today"},
        ]}
    return {"items": [{"question_id": 5, "link": "https://softwarerecs.stackexchange.com/q/5",
                       "title": "Is there a tool to merge invoices?", "body": "<p>I need to merge invoices</p>",
                       "creation_date": 1790000000, "owner": {"user_id": 77}}]}


class ArenaTests(unittest.TestCase):
    def test_generation_runs_offline_and_learns(self):
        state, summary, disc = a.run_generation({}, getter=fake_getter, seed=1)
        self.assertEqual(state["generation"], 1)
        self.assertEqual(len(state["population"]), a.POPULATION)
        self.assertGreater(summary["demand_hits"], 0)
        self.assertGreater(summary["novel_people"], 0)
        self.assertIn("invoices", state["vocabulary"])
        self.assertTrue(all("vendor" not in d["excerpt"].lower() for d in disc))
        # novelty: same people again earn no novel credit
        state2, summary2, disc2 = a.run_generation(state, getter=fake_getter, seed=2)
        self.assertEqual(summary2["novel_people"], 0)
        self.assertEqual(disc2, [])

    def test_people_are_hashed_and_public_summary_has_no_text(self):
        state, summary, _ = a.run_generation({}, getter=fake_getter, seed=3)
        blob = json.dumps(summary)
        for leak in ("alice", "bob", "news.ycombinator.com/item", "reconciling"):
            self.assertNotIn(leak, blob)
        self.assertTrue(all(":" in p and "alice" not in p for p in state["archive"]))
        self.assertEqual(state["boundary"]["production_state_write"], False)

    def test_self_adaptive_mutation_stays_bounded(self):
        rng = random.Random(0)
        g = a.random_genome(rng, {"x": 1.0}, "g")
        for i in range(200):
            g = a.mutate(g, rng, {"x": 1.0, "y": 2.0}, f"g{i}")
            self.assertTrue(0.05 <= g["mutation_rate"] <= 0.6)
            self.assertTrue(14 <= g["recency_days"] <= 365)

    def test_stack_exchange_quota_respected(self):
        calls = []
        def getter(url):
            calls.append(url)
            return fake_getter(url)
        st = {"population": [a.clamp({"id": f"x{i}", "phrases": ["tired of"], "terms": ["tax"],
                                      "sources": ["se_softwarerecs", "se_superuser"]}) for i in range(8)]}
        a.run_generation(st, getter=getter, seed=4)
        self.assertLessEqual(sum(1 for u in calls if "stackexchange" in u), a.SE_QUERY_CAP)

    def test_errors_do_not_crash(self):
        def bad(url):
            raise TimeoutError("x")
        state, summary, _ = a.run_generation({}, getter=bad, seed=5)
        self.assertGreater(sum(summary["errors"].values()), 0)
        self.assertEqual(state["generation"], 1)


if __name__ == "__main__":
    unittest.main()
