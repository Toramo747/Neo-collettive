import unittest

from discovery_v3 import build_evidence_contract, natural_search_seed, observed_pain_candidates, query_relevance, structured_job_relevance, validate_observed_candidate


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
        self.assertEqual(rows[0]["hypothesis_schema_v"],7)

    def test_evidence_contract_separates_fact_from_inference(self):
        contract=build_evidence_contract(
            "Customer email management is taking hours",
            "Our support team manually copies customer emails into the CRM every day and the process is error-prone.",
            "customer email management need help manual workaround",
            "customer_support",
            "buyer",
            "customer support teams",
            "triage and respond to customer emails",
        )
        self.assertEqual(contract["schema_v"],1)
        self.assertTrue(contract["skeptic"]["passed"])
        self.assertTrue(contract["source_fact"])
        self.assertNotEqual(contract["source_fact"],contract["inference"])
        self.assertIn("every day",contract["frequency"])
        self.assertIn("error-prone",contract["cost_or_impact"])

    def test_evidence_contract_rejects_buyer_words_without_operational_pain(self):
        contract=build_evidence_contract(
            "Why Senior Engineers Fail Google SRE Interviews",
            "Interviewers are looking for evidence. The outcome is still a No Hire.",
            "Google Sheets reporting automation need help manual workaround",
            "spreadsheet_process",
            "buyer",
            "development teams",
            "operate Google Sheets reporting automation reliably",
        )
        self.assertFalse(contract["skeptic"]["passed"])
        self.assertIn("no_explicit_operational_pain",contract["skeptic"]["reasons"])
        self.assertEqual(contract["context_type"],"recruiting_interview")

    def test_known_false_positive_benchmark_stays_blocked(self):
        cases=[
            (
                "Frontend Web Application Developer",
                "Hiring at KoboToolBox. Job type: full time. Compensation: $90k-$105k. Availability: 35-40 hours per week.",
                "frontend web application developer freelance hiring budget",
                "ai_tools","paid_market","customer support teams","operate AI-assisted business workflow reliably",
            ),
            (
                "Junior Payroll Assistant",
                "Hiring Junior Payroll Assistant. Excel, accounting, customer support and operations skills required.",
                "spreadsheet process automation freelance hiring budget",
                "ai_tools","paid_market","customer support teams","clean and automate recurring spreadsheet work",
            ),
            (
                "Why Senior Engineers Fail Google SRE Interviews",
                "Interviewers are looking for evidence. The outcome is still a No Hire.",
                "Google Sheets reporting automation need help manual workaround",
                "spreadsheet_process","buyer","development teams","operate Google Sheets reporting automation reliably",
            ),
        ]
        for title,body,query,family,role,customer,job in cases:
            with self.subTest(title=title):
                contract=build_evidence_contract(title,body,query,family,role,customer,job)
                self.assertFalse(contract["skeptic"]["passed"])

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
        self.assertEqual(rows[0]["hypothesis_schema_v"],7)
    def test_control_plane_text_is_not_observed_commercial_pain(self):
        q="DevOps workflow need help manual workaround"
        meta={
            q.lower():{
                "family":"spreadsheet_process",
                "role":"buyer",
                "search_alias_used":"DevOps workflow",
            }
        }
        groups=[{
            "query":q,
            "results":[{
                "title":"Complete Google Form automation",
                "url":"https://github.com/x-boundaries/automation/issues/155",
                "snippet":"Historical terminal vocabulary retained for chronology only: G4_PASS G4_AMEND manual CI rerun or duplicate dispatch while exact-head CI is already in flight.",
            }],
        }]
        self.assertEqual(observed_pain_candidates(groups,meta,limit=5),[])


    def test_observed_pain_rejects_own_repository(self):
        q="content repurposing tool need help manual workaround"
        meta={q.lower():{"family":"content_tools","role":"discovery","search_alias_used":"content repurposing tool"}}
        groups=[{"query":q,"results":[{
            "title":"Define and falsify the paid-service differentiator before outreach",
            "url":"https://github.com/Toramo747/Neo-collettive/issues/18",
            "source":"github-issues-routed",
            "snippet":"We need help because this manual content workflow is repetitive and time consuming.",
        }]}]
        self.assertEqual(
            observed_pain_candidates(
                groups,meta,limit=5,reject_self_contamination=True,require_family_in_pain=True
            ),
            [],
        )

    def test_observed_pain_rejects_mirrored_neo_text(self):
        q="content repurposing tool need help manual workaround"
        meta={q.lower():{"family":"content_tools","role":"discovery","search_alias_used":"content repurposing tool"}}
        groups=[{"query":q,"results":[{
            "title":"Define and falsify the paid-service differentiator before outreach",
            "url":"https://github.com/example/external-repo/issues/18",
            "source":"github-issues-routed",
            "snippet":"Attempt to falsify one market-facing differentiator for the first paid AI-assisted content-operation offer before manual customer acquisition.",
        }]}]
        self.assertEqual(
            observed_pain_candidates(groups,meta,limit=5,reject_self_contamination=True),
            [],
        )

    def test_observed_pain_rejects_a2a_peer_text(self):
        q="customer support repetitive workflow problem"
        meta={q.lower():{"family":"customer_support","role":"discovery","search_alias_used":"customer support"}}
        groups=[{"query":q,"results":[{
            "title":"Peer report",
            "url":"https://example.com/peer",
            "source":"peer-a2a",
            "snippet":"Need help with manual customer support ticket workflow because it is repetitive.",
        }]}]
        self.assertEqual(
            observed_pain_candidates(groups,meta,limit=5,reject_self_contamination=True),
            [],
        )

    def test_observed_pain_requires_family_term_in_pain(self):
        q="HR workflow automation need help manual workaround"
        meta={q.lower():{"family":"hr_tools","role":"discovery","search_alias_used":"HR workflow automation"}}
        groups=[{"query":q,"results":[{
            "title":"Windows UI automation",
            "url":"https://stackoverflow.com/questions/80005249/windows-ui-automation",
            "source":"stackexchange-routed",
            "snippet":"I am specifically looking for a general Windows UI Automation approach rather than a workaround for one particular website.",
        }]}]
        self.assertEqual(
            observed_pain_candidates(groups,meta,limit=5,require_family_in_pain=True),
            [],
        )

    def test_product_launch_feature_copy_is_not_observed_customer_pain(self):
        q="spreadsheet process automation need help manual workaround"
        meta={
            q.lower():{
                "family":"spreadsheet_process",
                "role":"buyer",
                "search_alias_used":"spreadsheet process automation",
            }
        }
        groups=[{
            "query":q,
            "results":[{
                "title":"Show HN: Analyst Agent by Fabi.ai – Build and share specialized AI data agents",
                "url":"https://www.fabi.ai/product/analyst-agent",
                "snippet":"Universal data connectivity connects spreadsheets to warehouses. Built-in validation lets agents check their own work. Our product automates manual spreadsheet workflows for marketing teams.",
            }],
        }]
        self.assertEqual(observed_pain_candidates(groups,meta,limit=5),[])

    def test_customer_hint_is_grounded_in_pain_context_not_unrelated_copy(self):
        q="spreadsheet process automation need help manual workaround"
        meta={
            q.lower():{
                "family":"spreadsheet_process",
                "role":"buyer",
                "search_alias_used":"spreadsheet process automation",
            }
        }
        groups=[{
            "query":q,
            "results":[{
                "title":"Analytics workflow notes",
                "url":"https://example.com/ops-pain",
                "snippet":"Marketing teams can view the dashboards. Our operations team manually copies spreadsheet rows every week and the process is error-prone.",
            }],
        }]
        rows=observed_pain_candidates(groups,meta,limit=5)
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]["customer"],"operations teams")
        self.assertIn("spreadsheet",rows[0]["job"].lower())

    def test_evidence_contract_rejects_process_inferred_outside_pain_fact(self):
        contract=build_evidence_contract(
            "Customer support workflow",
            "Our support team manually triages customer emails every day and the process is error-prone.",
            "spreadsheet process automation need help manual workaround",
            "spreadsheet_process",
            "buyer",
            "customer support teams",
            "clean and automate recurring spreadsheet work",
        )
        self.assertFalse(contract["skeptic"]["passed"])
        self.assertIn("process_not_grounded_in_source_fact",contract["skeptic"]["reasons"])


    def test_cycle_338_persisted_candidates_all_purge_under_v09910(self):
        candidates=[
            {
                "family":"hr_tools",
                "pain":"I am specifically looking for a general Windows UI Automation approach rather than a workaround for one particular website.",
                "source_url":"https://stackoverflow.com/questions/80005249/windows-ui-automation",
                "source_title":"Windows UI automation",
                "source_role":"discovery",
            },
            {
                "family":"it_hygiene",
                "pain":"Mapping from ExcelInventoryItem into InventoryItem, check each field for value change, but that would be manual and tedious.",
                "source_url":"https://stackoverflow.com/questions/77586043/example",
                "source_title":"In Java/Spring Boot/JPA/Hibernate, is there a simple mechanism to track entity changes to generate a change report?",
                "source_role":"discovery",
            },
            {
                "family":"developer_tools",
                "pain":"My biggest pain point is this: When frontend developers build slick UX in React or Flutter, the real-world plumbing becomes difficult.",
                "source_url":"https://stackoverflow.com/questions/79899153/example",
                "source_title":"WordPress as backend -> Flutter or React as the frontend",
                "source_role":"discovery",
            },
            {
                "family":"workflow_automation",
                "pain":"Show HN: Automation ROI calculator for repetitive admin workflows",
                "source_url":"https://tinyopsstudio.com/automation-roi-calculator",
                "source_title":"Show HN: Automation ROI calculator for repetitive admin workflows",
                "source_role":"discovery",
            },
            {
                "family":"document_processing",
                "pain":"But with repetitive tasks, it became annoying for me to switch tabs and navigate to ChatGPT, leaving the Excel document behind.",
                "source_url":"https://sidenotepro.com",
                "source_title":"Show HN: SideNote Pro - Native Windows 11 AI beside your work",
                "source_role":"discovery",
            },
        ]
        results=[
            validate_observed_candidate(
                row,
                reject_self_contamination=True,
                require_family_in_pain=True,
                reject_launch=True,
            )
            for row in candidates
        ]
        self.assertEqual([ok for ok,_ in results],[False]*5)
        self.assertEqual(
            [reason for _,reason in results],
            [
                "family_term_missing_in_pain",
                "family_term_missing_in_pain",
                "family_term_missing_in_pain",
                "seller_launch",
                "seller_launch",
            ],
        )

    def test_ask_hn_explicit_buyer_pain_stays_valid(self):
        candidate={
            "family":"workflow_automation",
            "pain":"Our operations team has a manual workflow every week and we waste time copying orders between systems.",
            "source_url":"https://news.ycombinator.com/item?id=123",
            "source_title":"Ask HN: How are you automating repetitive back-office work?",
            "source_role":"buyer",
        }
        ok,reason=validate_observed_candidate(
            candidate,
            reject_self_contamination=True,
            require_family_in_pain=True,
            reject_launch=True,
        )
        self.assertTrue(ok)
        self.assertEqual(reason,"valid")

    def test_new_observed_launch_is_never_promoted_when_guard_enabled(self):
        q="small business admin automation need help manual workaround"
        meta={q.lower():{"family":"workflow_automation","role":"buyer","search_alias_used":"admin automation"}}
        groups=[{"query":q,"results":[{
            "title":"Show HN: Automation ROI calculator for repetitive admin workflows",
            "url":"https://tinyopsstudio.com/automation-roi-calculator",
            "snippet":"Show HN: Automation ROI calculator for repetitive admin workflows",
        }]}]
        self.assertEqual(
            observed_pain_candidates(
                groups,meta,limit=5,
                reject_self_contamination=True,
                require_family_in_pain=True,
                reject_seller_launch=True,
            ),
            [],
        )


if __name__ == "__main__":
    unittest.main()
