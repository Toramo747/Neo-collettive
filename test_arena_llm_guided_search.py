import unittest
import arena_llm_guided_search as m

class LLMGuidedSearchTests(unittest.TestCase):
    def test_rejects_llm_urls(self):
        self.assertEqual(m.valid_query("https://example.com/buyer"),"")
        self.assertEqual(m.valid_query("http://example.com"),"")

    def test_keeps_search_queries(self):
        q=m.valid_query('invoice reconciliation "we spend hours"')
        self.assertIn("invoice reconciliation",q)

    def test_prompt_forbids_evidence_urls(self):
        p=m.make_prompt("manual data entry").lower()
        self.assertIn("not supplying evidence or urls",p)
        self.assertIn("do not invent links",p)

    def test_prompt_population_has_diverse_genomes(self):
        self.assertGreaterEqual(len(m.PROMPT_GENOMES),5)
        prompts={m.make_prompt("invoice reconciliation",name) for name in m.PROMPT_GENOMES}
        self.assertEqual(len(prompts),len(m.PROMPT_GENOMES))

    def test_mutation_population_is_bounded(self):
        self.assertGreaterEqual(len(m.MUTATION_GENOMES),4)
        p=m.make_mutation_prompt("invoice reconciliation","invoice reconcile pay for","first_person_pain").lower()
        self.assertIn("mutating an existing search query",p)
        self.assertIn("do not add urls",p)

    def test_acceptance_requires_absolute_evidence_gain(self):
        src=open("arena_llm_guided_search.py",encoding="utf-8").read()
        self.assertIn("absolute_evidence_gain=bool(",src)
        self.assertIn('metrics["signal_hits"]>current_metrics["signal_hits"]',src)
        self.assertIn('metrics["unique_signal_threads"]>current_metrics["unique_signal_threads"]',src)
        self.assertIn("and absolute_evidence_gain",src)

if __name__=="__main__":
    unittest.main()
