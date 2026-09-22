import unittest

from discovery_v3 import natural_search_seed, observed_pain_candidates, query_relevance, structured_job_relevance


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

    def test_paid_market_rejects_single_generic_alias_token(self):
        meta={
            "role":"paid_market",
            "search_alias_used":"spreadsheet process automation",
        }
        r=query_relevance(
            "Senior Shopify Developer",
            "Hiring developer for ecommerce automation and storefront work.",
            "spreadsheet process automation freelance hiring budget",
            meta,
        )
        self.assertFalse(r["relevant"])
        self.assertEqual(r["min_overlap"],2)

    def test_paid_market_accepts_specific_alias_overlap(self):
        meta={
            "role":"paid_market",
            "search_alias_used":"spreadsheet process automation",
        }
        r=query_relevance(
            "Spreadsheet Automation Specialist",
            "Hiring contractor to automate a recurring spreadsheet process.",
            "spreadsheet process automation freelance hiring budget",
            meta,
        )
        self.assertTrue(r["relevant"])
        self.assertGreaterEqual(len(r["overlap"]),2)

    def test_structured_job_rejects_description_only_overlap(self):
        meta={"role":"paid_market","search_alias_used":"management report automation"}
        r=structured_job_relevance(
            "Oracle Fusion Cloud Lead — Logistics & Supply Chain Management",
            "Own automation, dashboards, reports and management workflows for enterprise systems.",
            "management report automation freelance hiring budget",
            meta,
        )
        self.assertFalse(r["relevant"])
        self.assertLess(len(r["title_overlap"]),2)

    def test_structured_job_accepts_specific_title_overlap(self):
        meta={"role":"paid_market","search_alias_used":"weekly client reporting"}
        r=structured_job_relevance(
            "Client Reporting Analyst",
            "Hiring contractor to prepare recurring weekly client reports.",
            "weekly client reporting freelance hiring budget",
            meta,
        )
        self.assertTrue(r["relevant"])
        self.assertGreaterEqual(len(r["title_overlap"]),2)

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
        self.assertEqual(rows[0]["hypothesis_schema_v"],5)

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

    def test_generic_job_listing_is_not_observed_pain(self):
        q="DevOps workflow freelance hiring budget"
        meta={
            q.lower():{
                "family":"ai_tools",
                "role":"paid_market",
                "search_alias_used":"DevOps workflow",
            }
        }
        groups=[{
            "query":q,
            "results":[{
                "title":"Senior Data Scientist",
                "url":"https://remotive.com/remote-jobs/data/senior-data-scientist-2091129",
                "snippet":"Hiring Senior Data Scientist at Lemon.io Category: Data and Analytics Job type: full_time. Are you a talented Senior Data Scientist looking for a remote job that lets you show your skills and get decent compensation?",
            }],
        }]
        self.assertEqual(observed_pain_candidates(groups,meta,limit=5),[])

    def test_job_listing_availability_hours_is_not_observed_pain(self):
        q="frontend web application developer freelance hiring budget"
        meta={
            q.lower():{
                "family":"ai_tools",
                "role":"paid_market",
                "search_alias_used":"frontend web application developer",
            }
        }
        groups=[{
            "query":q,
            "results":[{
                "title":"Frontend Web Application Developer",
                "url":"https://remotive.com/remote-jobs/design/frontend-web-application-developer-2091141",
                "snippet":"Hiring Frontend Web Application Developer at KoboToolbox Category: Design Job type: full_time Compensation: $90k - $105k Location: Remote Availability: 35-40 hours per week Reporting to: Lead developer.",
            }],
        }]
        self.assertEqual(observed_pain_candidates(groups,meta,limit=5),[])

    def test_interview_article_no_hire_is_not_observed_pain(self):
        q="Google Sheets reporting automation need help manual workaround"
        meta={
            q.lower():{
                "family":"spreadsheet_process",
                "role":"buyer",
                "search_alias_used":"Google Sheets reporting automation",
            }
        }
        groups=[{
            "query":q,
            "results":[{
                "title":"Why Senior Engineers Fail \"Google SRE\" Interviews (2026 Analysis)",
                "url":"https://news.ycombinator.com/item?id=46314406",
                "snippet":"Interviewers are looking for evidence of Google Sheets reporting automation reasoning. The outcome is still a No Hire.",
            }],
        }]
        self.assertEqual(observed_pain_candidates(groups,meta,limit=5),[])

    def test_job_listing_with_explicit_operational_pain_can_be_kept(self):
        q="DevOps workflow freelance hiring budget"
        meta={
            q.lower():{
                "family":"developer_tools",
                "role":"paid_market",
                "search_alias_used":"DevOps workflow",
            }
        }
        groups=[{
            "query":q,
            "results":[{
                "title":"DevOps Engineer",
                "url":"https://example.com/jobs/devops",
                "snippet":"Job type: full time. We are hiring because deployments are manually repeated across environments, take hours per week, and are error-prone.",
            }],
        }]
        rows=observed_pain_candidates(groups,meta,limit=5)
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]["hypothesis_schema_v"],5)


if __name__ == "__main__":
    unittest.main()
