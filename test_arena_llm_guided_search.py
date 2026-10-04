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

if __name__=="__main__":
    unittest.main()
