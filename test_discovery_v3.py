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

    def test_launch_post_self_report_is_not_promoted_as_customer_problem(self):
        q="AI assistant SaaS need help manual workaround"
        meta={
            q.lower():{
                "family":"ai_tools",
                "role":"buyer",
                "search_alias_used":"AI assistant SaaS",
            }
        }
        groups=[{
            "query":q,
            "results":[{
                "title":"Show HN: Mwe-MCP – self-hosted memory for AI agents that knows who may know what",
                "url":"https://github.com/Fr4nZ82/mwe-mcp",
                "snippet":"The repo is mostly vibe-coded. I've been a developer since the last millennium and I would never have managed to finish it in a reasonable time; it is in production and I have been using it for months, fixing the problems as they come.",
            }],
        }]
        self.assertEqual(observed_pain_candidates(groups,meta,limit=5),[])

    def test_observed_problem_uses_human_job_not_article_title(self):
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
                "title":"Show HN: Inbox helper for small support teams",
                "url":"https://example.com/problem",
                "snippet":"Our support team manually copies customer emails into the CRM and needs help because the process is repetitive and time consuming.",
            }],
        }]
        rows=observed_pain_candidates(groups,meta,limit=5)
        self.assertEqual(len(rows),1)
        self.assertNotIn("Show HN",rows[0]["job"])
        self.assertIn("customer emails",rows[0]["job"].lower())
        self.assertEqual(rows[0]["hypothesis_schema_v"],2)

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
