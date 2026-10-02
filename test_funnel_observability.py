import os
import unittest
from unittest.mock import patch

import search_providers as sp
from ingestion_diagnostics import IngestionDiagnostics, routed_search_diagnostics
from public_snapshot import sanitize_public_snapshot


class FunnelObservabilityIntegrationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.env_patch=patch.dict(os.environ,{"BRAVE_SEARCH_API_KEY":"test-secret","NEO_SEARCH_PROVIDER":"brave"},clear=True)
        self.env_patch.start()

    def tearDown(self):
        self.env_patch.stop()

    @staticmethod
    def relevance(_title,_snippet,_query,_meta):
        return {"relevant":True}

    def projected(self, ingestion):
        raw={
            "snapshot_schema":7,
            "neo_version":"0.99.43",
            "autopilot":{"cycles_completed":1},
            "latest_result":{
                "status":"SELECT",
                "evidence_quality":{
                    "ingestion_diagnostics":ingestion,
                    "qualified_problem_keys":[],
                    "problem_clusters":{},
                    "rejected_current_results":[],
                },
                "tool_opportunities":{
                    "candidate_counts":{
                        "configured_categories":5,
                        "evidenced_candidates":1,
                        "gate_eligible_candidates":1,
                        "qualified_candidates":0,
                    },
                    "top5":[],
                },
            },
        }
        return sanitize_public_snapshot(raw)["autopilot"]["select_diagnostics"]

    async def test_three_provider_rows_reach_public_select_diagnostics(self):
        async def http_get(url,**kwargs):
            return {
                "status":200,
                "json":{"web":{"results":[
                    {"title":"A","url":"https://a.example/1","description":"pain"},
                    {"title":"B","url":"https://b.example/2","description":"pain"},
                    {"title":"C","url":"https://c.example/3","description":"pain"},
                ]}},
            }
        async def bing_search(query,limit):
            self.fail("fallback should not be used")
        result,state=await sp.search_with_fallback(
            "manual reporting",3,
            bing_search=bing_search,
            state=sp.begin_cycle(sp.new_search_state(),1),
            http_get=http_get,
            provider_mode="brave",
        )
        routed=routed_search_diagnostics(
            [result],"manual reporting",{"class":"explore"},self.relevance,["web"]
        )
        d=IngestionDiagnostics(True)
        d.set_queries_planned(1)
        d.merge_web_research([{"ingestion_diagnostics":routed}])
        provider=sp.provider_diagnostics(state,"brave")
        provider.update({
            "configured_provider":"brave",
            "provider_key_present":True,
            "fallback_used":False,
        })
        d.set_search_provider(provider)
        diag=self.projected(d.snapshot())
        self.assertGreater(diag["raw_results"],0)
        self.assertTrue(diag["search_sources"])
        self.assertEqual(diag["funnel"]["queries_planned"],1)
        self.assertEqual(diag["funnel"]["queries_executed"],1)
        self.assertEqual(diag["funnel"]["raw_received"],3)
        self.assertEqual(diag["funnel"]["deduped"],3)
        self.assertEqual(diag["funnel"]["query_relevant"],3)

    async def test_provider_exception_is_counted_and_fallback_invoked(self):
        fallback_calls=[]
        async def http_get(url,**kwargs):
            raise TimeoutError("simulated")
        async def bing_search(query,limit):
            fallback_calls.append(query)
            return {
                "ok":True,
                "query":query,
                "results":[{"title":"fallback","url":"https://fallback.example/1","snippet":"pain","source":"bing-rss-free"}],
                "count":1,
                "provider":"bing",
            }
        result,state=await sp.search_with_fallback(
            "workflow",2,
            bing_search=bing_search,
            state=sp.begin_cycle(sp.new_search_state(),1),
            http_get=http_get,
            provider_mode="brave",
        )
        self.assertEqual(fallback_calls,["workflow"])
        self.assertEqual(result["provider_fallback_from"],"brave")
        routed=routed_search_diagnostics(
            [result],"workflow",{"class":"explore"},self.relevance,["web"]
        )
        d=IngestionDiagnostics(True)
        d.set_queries_planned(1)
        d.merge_web_research([{"ingestion_diagnostics":routed}])
        diag=self.projected(d.snapshot())
        self.assertEqual(diag["funnel"]["errors_by_source"]["web"]["TimeoutError"],1)
        self.assertGreaterEqual(state["fallbacks"],1)

    async def test_empty_primary_provider_invokes_bing_fallback(self):
        fallback_calls=[]
        async def http_get(url,**kwargs):
            return {"status":200,"json":{"web":{"results":[]}}}
        async def bing_search(query,limit):
            fallback_calls.append(query)
            return {
                "ok":True,
                "query":query,
                "results":[],
                "count":0,
                "provider":"bing",
            }
        result,state=await sp.search_with_fallback(
            "workflow",2,
            bing_search=bing_search,
            state=sp.begin_cycle(sp.new_search_state(),1),
            http_get=http_get,
            provider_mode="brave",
        )
        self.assertEqual(fallback_calls,["workflow"])
        self.assertEqual(result["provider_fallback_from"],"brave")
        self.assertEqual(result["provider_fallback_reason"],"empty_primary_result")
        self.assertGreaterEqual(state["fallbacks"],1)


if __name__=="__main__":
    unittest.main()
