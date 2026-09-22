import unittest

from discovery_v3 import natural_search_seed, observed_pain_candidates, query_relevance


class DiscoveryV3Tests(unittest.TestCase):
    def test_natural_seed_prefers_search_alias(self):
        meta={"search_alias_used":"customer email management"}
        q='site:reddit.com "customer email management" ("small business" OR operations)'
        self.assertEqual(natural_search_seed(q,meta),"customer email management")

    def test_irrelevant_search_result_is_rejected(self):
        meta={"search_alias_used":"customer email management"}
        r=query_relevance(
            "72 DIY Home Decor Ideas For All Budgets",
            "Weekend decorating projects for your house.",
            'customer email management need help manual workaround',
            meta,
        )
        self.assertFalse(r["relevant"])

    def test_relevant_result_is_accepted(self):
        meta={"search_alias_used":"customer email management"}
        r=query_relevance(
            "Customer email management is killing our support workflow",
            "We manually copy customer emails into the CRM and need help automating it.",
            'customer email management need help manual workaround',
            meta,
        )
        self.assertTrue(r["relevant"])
        self.assertIn("email",r["overlap"])

    def test_observed_pain_candidate_requires_source_backed_signal(self):
        q="customer email management need help manual workaround"
        meta={
            q.lower():{
                "family":"ai_tools",
                "role":"buyer",
                "search_alias_used":"customer email management",
            }
        }
        groups=[{
            "query":q,
            "results":[{
                "title":"Customer email management is taking hours",
                "url":"https://example.com/problem",
                "snippet":"Our small business manually copies customer email into CRM. We need help because this is repetitive and time consuming.",
            }],
        }]
        rows=observed_pain_candidates(groups,meta,limit=5)
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]["family"],"ai_tools")
        self.assertEqual(rows[0]["source_url"],"https://example.com/problem")
        self.assertGreaterEqual(rows[0]["priority"],50)

    def test_observed_pain_ignores_irrelevant_noise(self):
        q="customer email management need help manual workaround"
        meta={
            q.lower():{
                "family":"ai_tools",
                "role":"buyer",
                "search_alias_used":"customer email management",
            }
        }
        groups=[{
            "query":q,
            "results":[{
                "title":"DIY home decor ideas",
                "url":"https://example.com/decor",
                "snippet":"Budget-friendly decorating projects.",
            }],
        }]
        self.assertEqual(observed_pain_candidates(groups,meta,limit=5),[])


if __name__ == "__main__":
    unittest.main()
