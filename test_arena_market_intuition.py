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



class NeedSentenceTests(unittest.TestCase):
    def test_term_and_need_must_share_a_sentence(self):
        q = {"term": "crm", "phrase": "i wish there was"}
        base = {"url": "https://news.ycombinator.com/item?id=1", "domain": "news.ycombinator.com", "title": "", "signal_types": []}
        off = dict(base, excerpt="I wish there was a follow button on HN. Unrelated: our crm is fine.")
        on = dict(base, excerpt="Honestly I wish there was a CRM that did not need a consultant to set up.")
        self.assertEqual(a.need_sentence(off, q), "")
        self.assertIn("CRM", a.need_sentence(on, q))



class MindTests(unittest.TestCase):
    def fake_mind(self, model, prompt, schema):
        if "verdicts" in json.dumps(schema):
            n = prompt.count("\n") - prompt.split("\n\n")[-1].count("\n") if False else len(prompt.split("\n\n")[-1].splitlines())
            return {"verdicts": [{"i": i, "real_need": True, "problem": "Invoice Reconciliation!",
                                  "would_pay": "yes" if i == 0 else "unknown"} for i in range(n)]}
        return {"observation": "invoices recur", "hypothesis": "small firms reconcile by hand",
                "assign": [{"i": 0, "problem": "invoice reconciliation"}],
                "next_terms": ["invoice matching", "http://evil", "x" * 90],
                "next_phrases": ["we still do this by hand"], "abandon_terms": ["crm"]}

    POP = {"population": [a.clamp({"id": f"p{i}", "phrases": ["is there a tool", "tired of"],
                                   "terms": ["invoices", "tax"], "sources": ["hn_comments", "hn_stories"]})
                           for i in range(8)]}

    def test_mind_judges_maps_and_proposes(self):
        state, summary, disc = a.run_generation(dict(self.POP), getter=fake_getter, seed=7,
                                                mind_model="fake", mind_gen=self.fake_mind)
        self.assertTrue(summary["mind"]["used"])
        self.assertIn("invoice reconciliation", state["market_map"])
        self.assertGreaterEqual(state["market_map"]["invoice reconciliation"]["people"], 3)
        self.assertIn("invoice matching", state["vocabulary"])
        self.assertNotIn("http://evil", json.dumps(state))
        self.assertIn("we still do this by hand", state["learned_phrases"])
        self.assertTrue(any(g.get("origin") == "mind" for g in state["population"]))
        self.assertTrue(state["diary"][-1].startswith("gen 1"))
        self.assertTrue(any(d["problem"] == "invoice reconciliation" for d in disc))
        self.assertGreater(summary["money_people"], 0)
        # next generation: the idea genome's outcome is logged, learned phrase is usable
        state2, _, _ = a.run_generation(state, getter=fake_getter, seed=8, mind_model="fake", mind_gen=self.fake_mind)
        self.assertTrue(state2["idea_log"])

    def test_mind_rejection_removes_demand(self):
        def reject(model, prompt, schema):
            if "verdicts" in json.dumps(schema):
                return {"verdicts": [{"i": i, "real_need": False, "problem": "", "would_pay": "no"} for i in range(6)]}
            return {}
        state, summary, disc = a.run_generation(dict(self.POP), getter=fake_getter, seed=9, mind_model="fake", mind_gen=reject)
        self.assertEqual(summary["demand_hits"], 0)
        self.assertEqual(disc, [])



class FixesTests(unittest.TestCase):
    def test_pay_counts_distinct_people_and_migrates(self):
        st = {"market_map": {"db cost": {"people": 3, "pay": 6, "persons": ["a", "b", "c"]}}}
        state, _, _ = a.run_generation(st, getter=lambda u: {"hits": [], "items": []}, seed=1,
                                       mind_model="fake", mind_gen=lambda m, p, s: {})
        self.assertLessEqual(state["market_map"]["db cost"]["pay"], state["market_map"]["db cost"]["people"])
        inbox = {"verdicts": [{"person": "a", "real_need": True, "problem": "db cost", "would_pay": "yes"}] * 2}
        st2 = a.apply_deep({"market_map": {"db cost": {"people": 1, "pay": 0, "persons": ["b"], "payers": []}}}, inbox)
        self.assertEqual(st2["market_map"]["db cost"]["pay"], 1)
        self.assertEqual(st2["market_map"]["db cost"]["people"], 2)

    def test_focus_terms_present_every_generation(self):
        state, _, _ = a.run_generation({}, getter=fake_getter, seed=3)
        focus = [g for g in state["population"] if g.get("origin") == "focus"]
        self.assertEqual(len(focus), a.FOCUS_SLOTS)
        self.assertTrue(all(g["terms"][0] in a.FOCUS_TERMS for g in focus))

    def test_discoveries_have_one_row_per_person(self):
        st = {"population": [a.clamp({"id": f"p{i}", "phrases": ["is there a tool", "tired of"],
                                      "terms": ["invoices", "tax"], "sources": ["hn_comments", "hn_stories"]}) for i in range(8)]}
        _, _, disc = a.run_generation(st, getter=fake_getter, seed=4)
        people = [d["person"] for d in disc]
        self.assertEqual(len(people), len(set(people)))



class LabelHygieneTests(unittest.TestCase):
    def test_problem_labels(self):
        import arena_mind as m
        self.assertEqual(m.problem_label("gen 45"), "")
        self.assertEqual(m.problem_label("automation"), "")
        self.assertEqual(m.problem_label("automation management"), "")
        self.assertEqual(m.problem_label("log-in-saas-apps-from-spreadsheets"), "log in saas apps from spreadsheets")
        self.assertEqual(m.problem_label("metadata monitoring service"), "metadata monitoring service")

    def test_snap_to_existing(self):
        import arena_mind as m
        existing = ["metadata monitoring", "security domain ip monitoring"]
        self.assertEqual(m.snap_problem("metadata monitoring service", existing), "metadata monitoring")
        self.assertEqual(m.snap_problem("metadata monitoring services", existing), "metadata monitoring")
        self.assertEqual(m.snap_problem("invoice reconciliation", existing), "invoice reconciliation")

    def test_bad_names_dropped_at_load(self):
        st = {"market_map": {"gen 45": {"people": 3, "persons": ["a", "b", "c"]}, "db cost monitoring": {"people": 1, "persons": ["d"]}}}
        state, _, _ = a.run_generation(st, getter=lambda u: {"hits": [], "items": []}, seed=1, mind_model="fake", mind_gen=lambda m, p, s: {})
        self.assertNotIn("gen 45", state["market_map"])
        self.assertIn("db cost monitoring", state["market_map"])


if __name__ == "__main__":
    unittest.main()
