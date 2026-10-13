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
        p=m.make_mutation_prompt("invoice reconciliation","invoice reconcile pay for","pain_swap").lower()
        self.assertIn("mutating an existing search query",p)
        self.assertIn("do not add urls",p)

    def test_acceptance_requires_absolute_evidence_gain(self):
        src=open("arena_llm_guided_search.py",encoding="utf-8").read()
        self.assertIn("absolute_evidence_gain=bool(",src)
        self.assertIn('metrics["signal_hits"]>current_metrics["signal_hits"]',src)
        self.assertIn('metrics["unique_signal_threads"]>current_metrics["unique_signal_threads"]',src)
        self.assertIn("and absolute_evidence_gain",src)

    def test_substitution_guard_rejects_longer_queries(self):
        before=dict(m.MUTATION_STATS)
        self.assertEqual(m.accept_mutation("problem invoice reconcile","problem invoice reconcile every week takes hours"),"")
        self.assertEqual(m.MUTATION_STATS["rejected_too_long"],before["rejected_too_long"]+1)

    def test_substitution_guard_accepts_swaps_and_drops(self):
        self.assertEqual(m.accept_mutation("problem invoice reconcile","hate invoice reconcile"),"hate invoice reconcile")
        self.assertEqual(m.accept_mutation("pay for invoice reconcile","pay invoice reconcile"),"pay invoice reconcile")

    def test_substitution_guard_rejects_drift_and_noop(self):
        self.assertEqual(m.accept_mutation("problem invoice reconcile","crm software"),"")
        self.assertEqual(m.accept_mutation("problem invoice reconcile","problem invoice reconcile"),"")

    def test_prompt_forbids_adding_words(self):
        p=m.make_mutation_prompt("invoice reconciliation","problem invoice reconcile","pain_swap").lower()
        self.assertIn("do not add words",p)

if __name__=="__main__":
    unittest.main()
