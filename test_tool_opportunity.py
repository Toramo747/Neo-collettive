# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Andrea Gava
import unittest

from tool_opportunity import analyze_tool_opportunities, seti_market_catalog


class ToolOpportunityTests(unittest.TestCase):
    def _group(self, query, rows):
        return {"query":query,"results":rows}

    def test_gate_requires_two_independent_payment_domains(self):
        meta={
            '"ai agent tool" pricing subscription':{
                "family":"ai_tools","role":"tool_pricing"
            }
        }
        rows=[
            self._group('"ai agent tool" pricing subscription',[
                {
                    "title":"AgentPro pricing $29/month",
                    "url":"https://agentpro.example/pricing",
                    "snippet":"Pro plan $29/month. Missing export feature remains a limitation.",
                    "source":"web",
                },
                {
                    "title":"AgentPro enterprise pricing $99/month",
                    "url":"https://agentpro.example/enterprise",
                    "snippet":"Enterprise subscription $99/month.",
                    "source":"web",
                },
                {
                    "title":"Users request cheaper alternative",
                    "url":"https://github.com/example/agentpro/issues/22",
                    "snippet":"Too expensive and missing feature for team export.",
                    "source":"github-issues",
                },
            ])
        ]
        result=analyze_tool_opportunities(rows,[],[],meta,"2026-09-26T12:00:00+00:00")
        ai=next(x for x in result["top5"] if x["family"]=="ai_tools")
        self.assertFalse(ai["gate_pass"])
        self.assertIn("two_independent_real_price_competitors",ai["missing"])

    def test_gate_passes_only_with_url_grounded_market_evidence(self):
        meta={
            '"ai agent tool" pricing subscription':{
                "family":"ai_tools","role":"tool_pricing"
            },
            'site:producthunt.com "ai agent tool"':{
                "family":"ai_tools","role":"product_hunt"
            },
        }
        groups=[
            self._group('"ai agent tool" pricing subscription',[
                {
                    "title":"AgentPro pricing $29/month",
                    "url":"https://agentpro.example/pricing",
                    "snippet":"Pro subscription $29/month.",
                    "source":"web",
                },
                {
                    "title":"AgentCloud pricing $19/month",
                    "url":"https://agentcloud.example/pricing",
                    "snippet":"Paid plan starts at $19/month.",
                    "source":"web",
                },
                {
                    "title":"Feature request: lower price and export support",
                    "url":"https://github.com/example/agent-tool/issues/42",
                    "snippet":"The current tool is too expensive and does not support export; looking for alternative.",
                    "source":"github-issues",
                },
            ]),
            self._group('site:producthunt.com "ai agent tool"',[
                {
                    "title":"Launch: focused AI agent utility",
                    "url":"https://www.producthunt.com/products/example-agent",
                    "snippet":"New release for agent workflow automation.",
                    "source":"web",
                },
            ]),
        ]
        result=analyze_tool_opportunities(groups,[],[],meta,"2026-09-26T12:00:00+00:00")
        ai=next(x for x in result["top5"] if x["family"]=="ai_tools")
        self.assertTrue(ai["gate_pass"])
        self.assertGreaterEqual(ai["monetization_score"],60)
        self.assertGreaterEqual(len({x["domain"] for x in ai["payment_signals"]}),2)
        for source in ai["sources"]:
            self.assertTrue(source["url"].startswith(("http://","https://")))
            self.assertTrue(source["date"])

    def test_counter_signal_reduces_monetization_score(self):
        meta={'"developer tool" pricing subscription':{"family":"developer_tools","role":"tool_pricing"}}
        base=[
            {
                "title":"DevPro pricing $20/month",
                "url":"https://devpro.example/pricing",
                "snippet":"Pro subscription $20/month.",
                "source":"web",
            },
            {
                "title":"CodeFlow pricing $15/month",
                "url":"https://codeflow.example/pricing",
                "snippet":"Paid plan $15/month.",
                "source":"web",
            },
            {
                "title":"Feature request",
                "url":"https://github.com/example/dev/issues/1",
                "snippet":"Too expensive and missing feature for code review.",
                "source":"github-issues",
            },
        ]
        no_counter=analyze_tool_opportunities(
            [self._group('"developer tool" pricing subscription',base)],[],[],meta,
            "2026-09-26T12:00:00+00:00"
        )
        with_counter=analyze_tool_opportunities(
            [self._group('"developer tool" pricing subscription',base+[{
                "title":"Open source developer tool alternative",
                "url":"https://opensource.example/devtool",
                "snippet":"Completely free open source developer code review alternative.",
                "source":"web",
            }])],[],[],meta,"2026-09-26T12:00:00+00:00"
        )
        a=next(x for x in no_counter["top5"] if x["family"]=="developer_tools")
        b=next(x for x in with_counter["top5"] if x["family"]=="developer_tools")
        self.assertLess(b["monetization_score"],a["monetization_score"])

    def test_seti_payment_required_is_market_signal_without_payment(self):
        candidates={
            "959e9e41abcdef":{
                "agent_card_url":"https://peer.example/.well-known/agent-card.json",
                "title":"Commercial A2A capability",
                "description":"Agent automation capability",
            }
        }
        interviews={
            "959e9e41abcdef":{
                "followup_state":"PAYMENT_BLOCKED",
                "peer_class":"PAYMENT_REQUIRED",
                "last_attempt_utc":"2026-09-26T09:58:15+00:00",
                "http_status":200,
            }
        }
        rows=seti_market_catalog(candidates,interviews)
        self.assertEqual(rows[0]["candidate"],"SETI-959e9e41")
        self.assertEqual(rows[0]["pricing_model"],"PAYMENT_REQUIRED")
        self.assertFalse(rows[0]["payment_performed"])


    def test_seti_historical_payment_peer_survives_candidate_pruning(self):
        rows=seti_market_catalog({},{
            "959e9e41deadbeef":{
                "endpoint":"https://paid-peer.example/a2a",
                "followup_state":"PAYMENT_BLOCKED",
                "peer_class":"PAYMENT_REQUIRED",
                "last_attempt_utc":"2026-09-26T09:58:15+00:00",
                "http_status":200,
                "response_excerpt":"Payment required for this capability.",
            }
        })
        self.assertEqual(rows[0]["candidate"],"SETI-959e9e41")
        self.assertEqual(rows[0]["pricing_model"],"PAYMENT_REQUIRED")
        self.assertTrue(rows[0]["historical_interview_only"])
        self.assertFalse(rows[0]["payment_performed"])



    def test_free_or_unpriced_seti_is_not_payment_signal(self):
        candidates={
            "freepeer1234":{
                "agent_card_url":"https://free.example/.well-known/agent-card.json",
                "title":"Free peer",
            }
        }
        interviews={
            "freepeer1234":{
                "endpoint":"https://free.example/a2a",
                "http_status":200,
                "response_excerpt":"Public capability with no commercial terms.",
                "last_attempt_utc":"2026-09-26T10:00:00+00:00",
            }
        }
        catalog=seti_market_catalog(candidates,interviews)
        self.assertEqual(catalog[0]["pricing_model"],"FREE_OR_UNPRICED")
        result=analyze_tool_opportunities([],[],catalog,{}, "2026-09-26T12:00:00+00:00")
        ai=next(x for x in result["top5"] if x["family"]=="ai_tools")
        self.assertEqual(ai["payment_signals"],[])

    def test_indexed_github_issue_without_agent_endpoint_is_not_seti_market_catalog(self):
        rows=seti_market_catalog({
            "issue1234":{
                "url":"https://github.com/example/repo/issues/1",
                "title":"A2A feature request",
            }
        },{})
        self.assertEqual(rows,[])

    def test_explicit_usd_prefix_is_payment_evidence(self):
        catalog=[{
            "candidate":"SETI-paid1234",
            "url":"https://paid.example/a2a",
            "observed_at_utc":"2026-09-26T10:00:00+00:00",
            "category":"ai_tools",
            "capabilities":["Diagnostic starts at USD 49 and repair pilot USD 149."],
            "pricing_model":"FREE_OR_UNPRICED",
            "http_status":200,
            "payment_performed":False,
        }]
        result=analyze_tool_opportunities([],[],catalog,{},"2026-09-26T12:00:00+00:00")
        ai=next(x for x in result["top5"] if x["family"]=="ai_tools")
        self.assertEqual(len(ai["payment_signals"]),1)
        self.assertEqual(ai["payment_signals"][0]["domain"],"paid.example")



    def test_seti_payment_required_is_one_signal_not_real_price_competitor(self):
        catalog=[{
            "candidate":"SETI-959e9e41",
            "url":"https://aion-agent-core-live.onrender.com/a2a/v1",
            "observed_at_utc":"2026-09-26T09:58:15+00:00",
            "category":"ai_tools",
            "capabilities":["Commercial capability requires payment before execution."],
            "pricing_model":"PAYMENT_REQUIRED",
            "http_status":200,
            "payment_performed":False,
        }]
        result=analyze_tool_opportunities([],[],catalog,{},"2026-09-26T12:00:00+00:00")
        ai=next(x for x in result["top5"] if x["family"]=="ai_tools")
        self.assertEqual(len(ai["payment_signals"]),1)
        self.assertEqual(ai["payment_signals"][0]["price"],"PAYMENT_REQUIRED")
        self.assertEqual(ai["existing_tools"],[])
        self.assertFalse(ai["gate_pass"])
        self.assertIn("two_competitors_with_real_price",ai["missing"])

    def test_same_host_multiple_agent_cards_count_as_one_payment_seller(self):
        catalog=[
            {
                "candidate":"SETI-a",
                "url":"https://vendor.example/a2a/one",
                "observed_at_utc":"2026-09-26T10:00:00+00:00",
                "category":"ai_tools",
                "capabilities":["Diagnostic starts at USD 49."],
                "pricing_model":"FREE_OR_UNPRICED",
                "http_status":200,
                "payment_performed":False,
            },
            {
                "candidate":"SETI-b",
                "url":"https://vendor.example/a2a/two",
                "observed_at_utc":"2026-09-26T10:01:00+00:00",
                "category":"ai_tools",
                "capabilities":["Repair starts at USD 99."],
                "pricing_model":"FREE_OR_UNPRICED",
                "http_status":200,
                "payment_performed":False,
            },
        ]
        result=analyze_tool_opportunities([],[],catalog,{},"2026-09-26T12:00:00+00:00")
        ai=next(x for x in result["top5"] if x["family"]=="ai_tools")
        self.assertEqual(len(ai["existing_tools"]),0)
        self.assertFalse(ai["gate_pass"])
        self.assertIn("two_independent_real_price_competitors",ai["missing"])

    def test_github_bounty_price_is_not_a_paid_competitor(self):
        meta={'"analytics saas" pricing subscription':{"family":"analytics_tools","role":"tool_pricing"}}
        groups=[self._group('"analytics SaaS" pricing subscription',[
            {
                "title":"AnalyticsPro pricing $29/month",
                "url":"https://analyticspro.example/pricing",
                "snippet":"Analytics dashboard subscription $29/month.",
                "source":"web",
            },
            {
                "title":"[BOUNTY $75] write a SaaS template",
                "url":"https://github.com/example/repo/issues/9",
                "snippet":"Bounty $75 for a Next.js template.",
                "source":"github-issues",
            },
        ])]
        result=analyze_tool_opportunities(groups,[],[],meta,"2026-09-26T12:00:00+00:00")
        row=next(x for x in result["top5"] if x["family"]=="analytics_tools")
        self.assertEqual(len(row["existing_tools"]),1)
        self.assertFalse(row["gate_pass"])

    def test_thesis_is_specific_and_has_target_user_build_days(self):
        result=analyze_tool_opportunities([],[],[],{},"2026-09-26T12:00:00+00:00")
        for thesis in result["top5"]:
            self.assertTrue(thesis["tool_name"])
            self.assertTrue(thesis["target_user"])
            self.assertGreaterEqual(thesis["feasibility"]["estimated_build_days"],1)
            self.assertNotIn(thesis["title"],{"AI / agent utility","Developer workflow tool","API / integration tool"})

    def test_source_coverage_reports_zero_and_errors(self):
        result=analyze_tool_opportunities(
            [],[],[],{},"2026-09-26T12:00:00+00:00",
            source_diagnostics={"mcp_registry":{"errors":["http_503:test"]}}
        )
        coverage=result["source_coverage"]
        self.assertEqual(coverage["mcp_registry"]["records_read"],0)
        self.assertEqual(coverage["mcp_registry"]["errors"],["http_503:test"])
        self.assertEqual(coverage["seti"]["records_read"],0)


if __name__=="__main__":
    unittest.main()
