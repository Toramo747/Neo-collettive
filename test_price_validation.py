import unittest

from price_validation import (
    buyer_voice_counts,
    extract_price,
    marketplace_identity,
    price_validation_plan,
    product_pricing_page,
    compact_price_evidence,
    persisted_price_groups,
    summarize_validation,
    validate_pricing_result,
)
from tool_opportunity import CATEGORY_CONFIGS, analyze_tool_opportunities


class PriceValidationTests(unittest.TestCase):
    def test_deterministic_price_parser_requires_currency_amount_and_period(self):
        self.assertEqual(
            extract_price("Pro plan $29/month"),
            {"currency":"USD","amount":29.0,"period":"month","raw":"$29"},
        )
        self.assertEqual(extract_price("Annual EUR 199 per year")["period"],"year")
        self.assertIsNone(extract_price("Contact sales for pricing"))
        self.assertIsNone(extract_price("Only $29 with no billing period"))

    def test_product_page_rejects_articles_and_accepts_marketplaces(self):
        self.assertTrue(product_pricing_page("https://vendor.example/pricing","Plans","$29/month"))
        self.assertTrue(product_pricing_page("https://marketplace.visualstudio.com/items/foo","Foo","$9/month"))
        self.assertFalse(product_pricing_page("https://vendor.example/blog/best-tools","Best 10 tools","$29/month"))
        self.assertFalse(product_pricing_page("https://review.example/top-10-tools","Top 10","$29/month"))

    def test_valid_competitor_requires_product_page_and_verified_price(self):
        valid=validate_pricing_result({
            "title":"AgentPro pricing",
            "url":"https://agentpro.example/pricing",
            "snippet":"Pro plan $29/month",
        })
        self.assertEqual(valid["domain"],"agentpro.example")
        self.assertEqual(valid["price"]["amount"],29.0)
        self.assertIsNone(validate_pricing_result({
            "title":"AgentPro review",
            "url":"https://reviews.example/blog/agentpro",
            "snippet":"AgentPro costs $29/month",
        }))

    def test_plan_rotates_only_families_with_buyer_voice(self):
        evidence=[
            {"family":"ai_tools","gate_eligible":True,"signal_types":["BUY_INTENT"]},
            {"family":"developer_tools","gate_eligible":True,"signal_types":["PAIN"]},
            {"family":"analytics_tools","gate_eligible":False,"signal_types":["PAIN"]},
        ]
        self.assertEqual(buyer_voice_counts(evidence),{"ai_tools":1,"developer_tools":1})
        a=price_validation_plan(evidence,cycle=0,category_configs=CATEGORY_CONFIGS,budget=4)
        b=price_validation_plan(evidence,cycle=1,category_configs=CATEGORY_CONFIGS,budget=4)
        self.assertEqual(len(a),4)
        self.assertEqual(len(b),4)
        self.assertNotEqual(a[0]["family"],b[0]["family"])
        self.assertTrue(all(x["role"]=="price_validation" for x in a+b))

    def test_validation_telemetry_counts_distinct_competitor_domains(self):
        plan=[
            {"query":"q1","family":"ai_tools"},
            {"query":"q2","family":"ai_tools"},
        ]
        groups=[
            {"query":"q1","results":[
                {"title":"Agent A plans","url":"https://a.example/pricing","snippet":"$10/month"},
                {"title":"Agent A pro","url":"https://a.example/pricing/pro","snippet":"$20/month"},
            ]},
            {"query":"q2","results":[
                {"title":"Agent B plans","url":"https://b.example/pricing","snippet":"EUR 15 per month"},
                {"title":"Roundup","url":"https://reviews.example/blog/best","snippet":"$99/month"},
            ]},
        ]
        t=summarize_validation(plan,groups)["ai_tools"]
        self.assertEqual(t["validation_queries"],2)
        self.assertEqual(t["pricing_pages_found"],3)
        self.assertEqual(t["prices_extracted"],3)
        self.assertEqual(t["competitors_with_price"],2)

    def test_marketplace_identity_counts_apps_not_host(self):
        a=marketplace_identity("https://apps.shopify.com/app-a/pricing")
        a2=marketplace_identity("https://apps.shopify.com/app-a/reviews")
        b=marketplace_identity("https://apps.shopify.com/app-b")
        self.assertEqual(a,a2)
        self.assertNotEqual(a,b)
        self.assertEqual(len({a,a2,b}),2)

    def test_query_rotation_covers_all_nine_surfaces_in_three_cycles(self):
        evidence=[{"family":"ai_tools","gate_eligible":True,"signal_types":["BUY_INTENT"]}]
        executed=set()
        for cycle in range(3):
            plan=price_validation_plan(evidence,cycle=cycle,category_configs=CATEGORY_CONFIGS,budget=4)
            executed.update(row["query"] for row in plan)
        self.assertGreaterEqual(len(executed),9)

    def test_fetched_page_price_is_strict_telemetry_and_source_counted(self):
        plan=[{"query":"q","family":"ai_tools"}]
        groups=[{"query":"q","results":[{
            "title":"Agent A pricing",
            "url":"https://a.example/pricing",
            "snippet":"Plans for teams",
            "page_fetched":True,
            "page_text":"Pro plan USD 29 per month",
        }]}]
        row=validate_pricing_result(groups[0]["results"][0])
        self.assertTrue(row["strict_price_verified"])
        self.assertEqual(row["price_source"],"page")
        stats=summarize_validation(plan,groups)["ai_tools"]
        self.assertEqual(stats["pages_fetched"],1)
        self.assertEqual(stats["prices_from_page"],1)
        self.assertEqual(stats["prices_from_snippet"],0)
        self.assertEqual(stats["strict_prices"],1)

    def test_fetched_page_legacy_number_without_strict_period_cannot_enter_gate(self):
        query='"developer tool" pricing subscription'
        meta={query.lower():{"family":"developer_tools","role":"tool_pricing"}}
        groups=[{"query":query,"results":[
            {
                "title":"Dev One pricing",
                "url":"https://devone.example/pricing",
                "snippet":"Developer testing plans",
                "page_text":"Professional tier costs $29 with flexible billing",
            },
            {
                "title":"Dev Two pricing",
                "url":"https://devtwo.example/pricing",
                "snippet":"Developer testing plans",
                "page_text":"Professional tier costs $19 with flexible billing",
            },
            {
                "title":"Developer pain",
                "url":"https://third.example/issues/1",
                "snippet":"Developer testing is too expensive and missing a needed feature.",
            },
        ]}]
        result=analyze_tool_opportunities(groups,[],[],meta,"2026-10-06T12:00:00+00:00")
        row=next(x for x in result["top5"] if x["family"]=="developer_tools")
        self.assertFalse(row["gate_pass"])
        self.assertIn("two_competitors_with_real_price",row["missing"])

    def test_strict_price_evidence_is_compact_and_replayable(self):
        plan=[{"query":"q","family":"developer_tools"}]
        groups=[{"query":"q","results":[{
            "title":"DevPro pricing",
            "url":"https://devpro.example/pricing",
            "snippet":"Plans",
            "page_fetched":True,
            "page_text":"Team plan USD 29 per month with support",
        }]}]
        compact=compact_price_evidence(plan,groups)
        self.assertEqual(len(compact),1)
        self.assertNotIn("page_text",compact[0])
        self.assertNotIn("snippet",compact[0])
        self.assertLessEqual(len(compact[0]["price_context"]),160)
        replay=persisted_price_groups(compact)
        self.assertEqual(len(replay),1)
        self.assertTrue(replay[0]["results"][0]["page_fetched"])
        self.assertEqual(validate_pricing_result(replay[0]["results"][0])["price"]["amount"],29.0)

    def test_query_telemetry_is_numeric_and_classifies_rejections(self):
        plan=[{"query":"q","family":"ai_tools"}]
        groups=[{"query":"q","results":[
            {"title":"Top 10 AI tools","url":"https://x.example/blog/best-tools","snippet":"$10/month"},
            {"title":"AI company","url":"https://x.example/about","snippet":"No product page"},
            {"title":"Agent pricing","url":"https://agent.example/pricing","snippet":"USD 20 per month"},
        ]}]
        stats=summarize_validation(plan,groups)
        q=stats["_query_telemetry"][0]
        self.assertEqual(q["results_received"],3)
        self.assertEqual(q["discarded_article"],1)
        self.assertEqual(q["discarded_non_product"],1)
        self.assertEqual(q["accepted"],1)
        self.assertTrue(all(isinstance(q[k],int) for k in q))

    def test_pre_177_gate_price_semantics_are_restored(self):
        # Pre-#177 accepted recognized numeric price text on the covered pricing
        # surface; the strict parser is now telemetry-only.
        query='"ai agent tool" pricing subscription'
        meta={query.lower():{"family":"ai_tools","role":"tool_pricing"}}
        groups=[{"query":query,"results":[
            {"title":"AI AgentPro pricing $29","url":"https://agentpro.example/pricing","snippet":"AI agent subscription pricing"},
            {"title":"AI AgentCloud pricing $19","url":"https://agentcloud.example/pricing","snippet":"AI agent paid plan"},
            {"title":"AI agent export limitation","url":"https://third.example/issues/1","snippet":"AI agent tool is too expensive and missing feature; looking for alternative."},
        ]}]
        result=analyze_tool_opportunities(groups,[],[],meta,"2026-09-26T12:00:00+00:00")
        row=next(x for x in result["top5"] if x["family"]=="ai_tools")
        self.assertTrue(row["gate_pass"])
        self.assertEqual(len(row["existing_tools"]),2)
        self.assertTrue(all(not x.get("strict_price_verified",False) for x in row["payment_signals"]))


    def test_gate_boolean_regression_price_requirement_only_changes_code(self):
        query='"ai agent tool" pricing subscription'
        meta={query.lower():{"family":"ai_tools","role":"tool_pricing"}}
        groups=[{"query":query,"results":[
            {"title":"AgentPro pricing","url":"https://agentpro.example/pricing","snippet":"Pro $29/month"},
        ]}]
        result=analyze_tool_opportunities(groups,[],[],meta,"2026-10-06T00:00:00+00:00")
        row=next(x for x in result["top5"] if x["family"]=="ai_tools")
        self.assertFalse(row["gate_pass"])
        self.assertIn("two_competitors_with_real_price",row["missing"])
        self.assertNotIn("two_independent_real_price_competitors",row["missing"])
        self.assertNotIn("two_existing_paid_tools",row["missing"])


if __name__ == "__main__":
    unittest.main()
