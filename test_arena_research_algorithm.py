import json
import unittest
from pathlib import Path

import arena_research_algorithm as ara


class ResearchAlgorithmArenaTests(unittest.TestCase):
    def test_initial_population_is_bounded(self):
        pop = ara.initial_population()
        self.assertEqual(len(pop), ara.POPULATION_SIZE)
        for item in pop:
            genes = item["genes"]
            self.assertIn(genes["query_mode"], ara.QUERY_MODES)
            self.assertGreaterEqual(genes["query_count"], 2)
            self.assertLessEqual(genes["query_count"], ara.MAX_QUERIES_PER_GENOME)
            self.assertGreaterEqual(genes["recency_days"], 7)
            self.assertLessEqual(genes["recency_days"], 45)
            self.assertGreaterEqual(genes["min_relevance_tokens"], 1)
            self.assertLessEqual(genes["min_relevance_tokens"], 3)
            self.assertIn(genes["suffix_family"], ara.SUFFIX_FAMILIES)
            self.assertIn(genes["topic_shape"], ara.TOPIC_SHAPE_MODES)
            self.assertIn(genes["query_frame"], ara.QUERY_FRAMES)
            self.assertIn(genes["term_order"], ara.TERM_ORDERS)
            self.assertIn(genes["source_scope"], ara.SOURCE_SCOPES)

    def test_parse_mutation_accepts_only_bounded_genes(self):
        mutation = ara.parse_mutation({
            "mutation": {
                "query_mode": "buyer",
                "query_count": 99,
                "recency_days": 1,
                "min_relevance_tokens": 9,
                "suffix_family": "ops",
                "topic_shape": "compact",
                "query_frame": "looking_for",
                "term_order": "signal_first",
                "source_scope": "stories",
                "forbidden": "ignored",
            }
        })
        self.assertEqual(mutation["query_mode"], "buyer")
        self.assertEqual(mutation["query_count"], 4)
        self.assertEqual(mutation["recency_days"], 7)
        self.assertEqual(mutation["min_relevance_tokens"], 3)
        self.assertEqual(mutation["suffix_family"], "ops")
        self.assertEqual(mutation["topic_shape"], "compact")
        self.assertEqual(mutation["query_frame"], "looking_for")
        self.assertEqual(mutation["term_order"], "signal_first")
        self.assertEqual(mutation["source_scope"], "stories")
        self.assertNotIn("forbidden", mutation)

    def test_query_genetics_change_query_surface_only(self):
        base={"query_mode":"workaround","query_count":4,"recency_days":42,"min_relevance_tokens":1}
        legacy=ara.clamp_genome(base)
        self.assertEqual(legacy["suffix_family"],"core")
        self.assertEqual(legacy["topic_shape"],"exact")
        q0=ara.build_queries(legacy)
        q1=ara.build_queries({**legacy,"suffix_family":"intent","topic_shape":"compact"})
        self.assertEqual(len(q0),len(q1))
        self.assertNotEqual(q0,q1)
        self.assertEqual({x[0] for x in q0},{x[0] for x in q1})

    def test_new_query_genes_are_backward_compatible(self):
        legacy=ara.clamp_genome({
            "query_mode":"workaround","query_count":4,"recency_days":42,
            "min_relevance_tokens":1,"suffix_family":"core","topic_shape":"compact",
        })
        self.assertEqual(legacy["query_frame"],"plain")
        self.assertEqual(legacy["term_order"],"topic_first")
        self.assertEqual(legacy["source_scope"],"comments")

    def test_query_frame_and_term_order_change_surface(self):
        base=ara.clamp_genome({
            "query_mode":"workaround","query_count":2,"recency_days":42,
            "min_relevance_tokens":1,"suffix_family":"core","topic_shape":"compact",
        })
        plain=ara.build_queries(base)
        framed=ara.build_queries({**base,"query_frame":"need","term_order":"signal_first"})
        self.assertEqual(len(plain),len(framed))
        self.assertNotEqual(plain,framed)
        self.assertTrue(all(q.startswith("need ") for _,q in framed))
        self.assertIn("workaround data entry",framed[0][1])

    def test_source_scope_is_wired_to_hn_fetch(self):
        src=Path("arena_research_algorithm.py").read_text(encoding="utf-8")
        self.assertIn('if source_scope == "comments"',src)
        self.assertIn('elif source_scope == "stories"',src)
        self.assertIn('genes["source_scope"]',src)

    def test_raw_external_text_is_not_part_of_persisted_contract(self):
        src = Path("arena_research_algorithm.py").read_text(encoding="utf-8")
        self.assertIn('"raw_text_persisted": False', src)
        self.assertNotIn('"raw_response":', src)

    def test_production_boundary_is_fail_closed(self):
        b = ara.BOUNDARY
        self.assertIs(b["production_state_write"], False)
        self.assertEqual(b["commercial_gate_influence"], "NONE")
        self.assertEqual(b["qualified_hits_influence"], "NONE")
        self.assertEqual(b["commercial_evidence_influence"], "NONE")
        self.assertEqual(b["search_provider_budget_influence"], "NONE")
        self.assertIs(b["production_variant_promotion"], False)
        self.assertEqual(b["promotion"], "MANUAL_REVIEW_ONLY")

    def test_collaborator_scope_is_task_verified_only(self):
        src = Path("arena_research_algorithm.py").read_text(encoding="utf-8")
        self.assertIn('params={"task_verified": "true", "limit": 20}', src)
        self.assertIn('"external_output_trust": "UNTRUSTED_BOUNDED_MUTATION_ONLY"', src)
        self.assertIn("Do not request secrets, tools, code execution, production changes, or external actions.", src)

    def test_support_penalty_blocks_tiny_perfect_sample(self):
        genome={"query_mode":"workaround","query_count":3,"recency_days":14,"min_relevance_tokens":1}
        rows=[{
            "topic":"manual data entry",
            "hits":[{"comment_text":"manual data entry workaround pay for tool","story_id":"1"}],
        }]
        metrics=ara.score_hits(genome,rows)
        self.assertEqual(metrics["precision"],1.0)
        self.assertLess(metrics["support_factor"],1.0)
        self.assertLess(metrics["fitness"],metrics["base_fitness"])

    def test_support_factor_reaches_full_credit_with_broader_support(self):
        genome={"query_mode":"workaround","query_count":3,"recency_days":14,"min_relevance_tokens":1}
        hits=[
            {"comment_text":"manual data entry workaround pay","story_id":"1"},
            {"comment_text":"manual data entry spreadsheet pay","story_id":"2"},
            {"comment_text":"manual data entry script cost","story_id":"3"},
            {"comment_text":"manual data entry csv workaround","story_id":"4"},
        ]
        metrics=ara.score_hits(genome,[{"topic":"manual data entry","hits":hits}])
        self.assertEqual(metrics["support_factor"],1.0)

    def test_diversity_helpers_are_bounded_and_distinct(self):
        import random
        parent={"genome_id":"p","genes":{"query_mode":"workaround","query_count":4,"recency_days":42,"min_relevance_tokens":1}}
        rng=random.Random(7)
        child=ara.diversify_mutation(parent,rng,8,"x")
        self.assertIn(child["genes"]["query_mode"],ara.QUERY_MODES)
        self.assertGreaterEqual(child["genes"]["recency_days"],7)
        self.assertLessEqual(child["genes"]["recency_days"],45)
        immigrant=ara.random_immigrant(random.Random(8),8,"i")
        self.assertIn(immigrant["genes"]["query_mode"],ara.QUERY_MODES)
        self.assertEqual(immigrant["origin"],"random_immigrant")

    def test_stagnation_detection(self):
        history=[
            {"champion_fitness":64.381},
            {"champion_fitness":64.381},
            {"champion_fitness":64.381},
        ]
        self.assertTrue(ara.stagnating(history))
        history[-1]["champion_fitness"]=65.0
        self.assertFalse(ara.stagnating(history))

    def test_genome_fitness_has_no_consensus_component(self):
        src = Path("arena_research_algorithm.py").read_text(encoding="utf-8")
        self.assertNotIn("agree_count", src.lower())
        self.assertNotIn("consensus", src.lower())


if __name__ == "__main__":
    unittest.main()
