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

    def test_job_ads_and_abstract_topics_are_not_needs(self):
        q = {"term": "crm", "phrase": "we need"}
        base = {"url": "https://news.ycombinator.com/item?id=2", "domain": "news.ycombinator.com", "title": "", "signal_types": []}
        ad = dict(base, excerpt="Acme | Full-time | Remote. We need a CRM engineer, we're hiring now.")
        pol = dict(base, excerpt="We need a CRM for climate change politics and the election.")
        ok = dict(base, excerpt="We need a CRM that imports email threads without manual copy paste.")
        self.assertEqual(a.need_sentence(ad, q), "")
        self.assertEqual(a.need_sentence(pol, q), "")
        self.assertIn("CRM", a.need_sentence(ok, q))



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
        st2 = a.apply_deep({"market_map": {"db cost": {"people": 1, "pay": 0, "persons": ["b"], "payers": []}},
                            "deep_queue": [{"person": "a", "need": "We would pay for anything that cuts our db cost"}]}, inbox)
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


    def test_truncated_and_abstract_labels(self):
        import arena_mind as m
        self.assertEqual(m.problem_label("email address retrieval via c"), "email address retrieval")
        self.assertEqual(m.problem_label("climate mitigation strategies"), "")

    def test_similar_problems_merge_with_union_of_people(self):
        import arena_mind as m
        mm = {"metadata monitoring service subscription": {"people": 3, "persons": ["a", "b", "c"], "payers": ["a", "b"]},
              "metadata monitoring services": {"people": 2, "persons": ["c", "d"], "payers": ["d"]},
              "monitor metadata": {"people": 1, "persons": ["e"], "payers": []},
              "security domain ip monitoring": {"people": 3, "persons": ["x", "y", "z"], "payers": []}}
        out, n = m.merge_similar(mm)
        self.assertEqual(n, 2)
        e = out["metadata monitoring service subscription"]
        self.assertEqual((e["people"], e["pay"]), (5, 3))
        self.assertIn("monitor metadata", e["aliases"])
        self.assertEqual(out["security domain ip monitoring"]["people"], 3)

    def test_stale_phrase_is_replaced(self):
        empty = lambda u: {"hits": [], "items": []}
        stale = a.PHRASES[0]
        pop = [a.clamp({"id": f"x{i}", "phrases": [stale, a.PHRASES[1]], "terms": ["tax"], "sources": ["hn_comments"]})
               for i in range(a.POPULATION)]
        # a generation where nobody is found does not make phrases staler (2026-10-14)
        st0 = {"population": pop, "phrase_dry": {stale: 1}}
        s0, _, _ = a.run_generation(st0, getter=empty, seed=1)
        self.assertEqual(s0["phrase_dry"].get(stale), 1)
        st = {"population": pop, "phrase_dry": {stale: a.STALE_PHRASE_GENS}}
        state, summary, _ = a.run_generation(st, getter=empty, seed=1)
        self.assertGreaterEqual(summary["stale_phrases"], 1)
        self.assertTrue(all(stale not in g["phrases"] for g in state["population"]))


    def test_strict_pay_and_coherence(self):
        import arena_mind as m
        self.assertFalse(m.strict_pay("Obviously that means I'd pay a lot in terms of memory footprint"))
        self.assertFalse(m.strict_pay("So I would pay $45/month for metadata monitoring on just 5 things?"))
        self.assertTrue(m.strict_pay("I would happily pay for a tool that alerts me when quality drops"))
        self.assertFalse(m.coherent("metadata monitoring", "How do you fix Eclipse Metadata breaking between OSes"))
        self.assertTrue(m.coherent("invoice reconciliation", "I spend hours reconciling invoices by hand"))

    def test_rebuild_map_drops_incoherent_people_and_fake_payers(self):
        import arena_mind as m
        mm = {"metadata monitoring": {"people": 3, "pay": 2, "persons": ["a", "b", "c"], "payers": ["a", "b"]}}
        needs = {"a": "Is there metadata monitoring that alerts on schema changes? I would pay for it",
                 "b": "Eclipse metadata breaks when I switch OS, I'd pay a lot in terms of time",
                 "c": "We need monitoring of dataset metadata drift"}
        out, stats = m.rebuild_map(mm, needs)
        e = out["metadata monitoring"]
        self.assertEqual((e["people"], e["pay"]), (2, 1))
        self.assertEqual(stats["persons_before"], 3)


if __name__ == "__main__":
    unittest.main()


class StrictPayFirstPersonOnly(unittest.TestCase):
    def test_false_payers_of_17_october_are_rejected(self):
        import arena_mind as m
        for s in ("execs and overworked infra teams will be willing to pay for",
                  "The iOS app started to get annoying with its extra subscription features",
                  "not as aggressive as quizlet in pushing users to get a subscription",
                  "Then I try to override the Ocp-Apim-Subscription-Key",
                  "I was frustrated by two things: $20/mo subscription layers just to wrap basic API access"):
            self.assertFalse(m.strict_pay(s), s)

    def test_first_person_intent_is_kept(self):
        import arena_mind as m
        for s in ("I would happily pay $10/month for a tool that does this",
                  "We're willing to pay for a hosted version", "We pay for Datadog but it misses this",
                  "We have budget for this next quarter"):
            self.assertTrue(m.strict_pay(s), s)

    def test_distinct_payers_counts_a_person_once(self):
        import arena_mind as m
        mm = {"a": {"payers": ["p1"]}, "b": {"payers": ["p1", "p2"]}}
        self.assertEqual(m.distinct_payers(mm), ["p1", "p2"])


class MapCapTests(unittest.TestCase):
    def test_new_single_person_problem_survives_the_cap(self):
        import arena_market_intuition as ami
        mm = {f"old{i}": {"people": 1, "last_gen": 100} for i in range(5)}
        mm["two"] = {"people": 2, "last_gen": 50}
        mm["fresh"] = {"people": 1, "last_gen": 286}
        out = ami.bounded_map(mm, cap=3)
        self.assertEqual(list(out), ["two", "fresh", "old0"])
