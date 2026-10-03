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

    def test_parse_mutation_accepts_only_bounded_genes(self):
        mutation = ara.parse_mutation({
            "mutation": {
                "query_mode": "buyer",
                "query_count": 99,
                "recency_days": 1,
                "min_relevance_tokens": 9,
                "forbidden": "ignored",
            }
        })
        self.assertEqual(mutation["query_mode"], "buyer")
        self.assertEqual(mutation["query_count"], 4)
        self.assertEqual(mutation["recency_days"], 7)
        self.assertEqual(mutation["min_relevance_tokens"], 3)
        self.assertNotIn("forbidden", mutation)

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

    def test_genome_fitness_has_no_consensus_component(self):
        src = Path("arena_research_algorithm.py").read_text(encoding="utf-8")
        self.assertNotIn("agree_count", src.lower())
        self.assertNotIn("consensus", src.lower())


if __name__ == "__main__":
    unittest.main()
