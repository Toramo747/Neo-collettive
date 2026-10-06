import unittest

from price_validation import (
    buyer_voice_counts,
    extract_price,
    price_validation_plan,
    product_pricing_page,
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
