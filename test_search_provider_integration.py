import os
import unittest
from unittest.mock import patch

import search_providers as sp


class SearchProviderFallbackTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.env_patch=patch.dict(os.environ,{},clear=True)
        self.env_patch.start()

    def tearDown(self):
        self.env_patch.stop()

    async def test_without_configured_key_uses_bing(self):
        calls=[]
        async def bing(query,limit):
            calls.append((query,limit))
            return {
                "ok":True,"query":query,
                "results":[{"title":"B","url":"https://example.com","snippet":"s","source":"bing-rss-free"}],
                "count":1,"provider":"bing",
            }
        result,state=await sp.search_with_fallback(
            "x",2,bing_search=bing,state=sp.new_search_state()
        )
        self.assertEqual(result["provider"],"bing")
        self.assertEqual(result["results"][0]["source"],"bing-rss-free")
        self.assertEqual(calls,[("x",2)])

    async def test_configured_provider_result_does_not_call_bing(self):
        os.environ["BRAVE_SEARCH_API_KEY"]="secret"
        calls=[]
        async def bing(query,limit):
            calls.append((query,limit))
            return {"ok":True,"query":query,"results":[],"count":0,"provider":"bing"}
        async def http_get(url,**kwargs):
            return {
                "status":200,
                "json":{"web":{"results":[{
                    "title":"P","url":"https://example.com/p","description":"buyer pain"
                }]}}
            }
        result,state=await sp.search_with_fallback(
            "x",2,bing_search=bing,state=sp.new_search_state(),http_get=http_get
        )
        self.assertEqual(result["provider"],"brave")
        self.assertEqual(result["results"][0]["source"],"brave-search")
        self.assertEqual(calls,[])

    async def test_provider_401_or_429_falls_back_to_bing(self):
        os.environ["BRAVE_SEARCH_API_KEY"]="secret"
        for status in (401,429):
            calls=[]
            async def bing(query,limit):
                calls.append((query,limit))
                return {"ok":True,"query":query,"results":[],"count":0,"provider":"bing"}
            async def http_get(url,**kwargs):
                return {"status":status,"json":{}}
            result,state=await sp.search_with_fallback(
                "x",2,bing_search=bing,state=sp.new_search_state(),http_get=http_get
            )
            self.assertEqual(result["provider"],"bing")
            self.assertEqual(result["provider_fallback_from"],"brave")
            self.assertEqual(result["provider_fallback_reason"],"HTTPStatusError:"+str(status))
            self.assertEqual(calls,[("x",2)])

    async def test_429_opens_cycle_circuit_breaker_after_three_consecutive_errors(self):
        os.environ["BRAVE_SEARCH_API_KEY"]="secret"
        http_calls=[]
        bing_calls=[]
        async def http_get(url,**kwargs):
            http_calls.append(url)
            return {"status":429,"json":{}}
        async def bing(query,limit):
            bing_calls.append((query,limit))
            return {"ok":True,"query":query,"results":[],"count":0,"provider":"bing"}
        state=sp.begin_cycle(sp.new_search_state(),123)
        results=[]
        for query in ("one","two","three","four"):
            result,state=await sp.search_with_fallback(
                query,2,bing_search=bing,state=state,http_get=http_get
            )
            results.append(result)
        self.assertEqual(len(http_calls),3)
        self.assertTrue(state["provider_throttled"])
        self.assertEqual([x["provider_fallback_reason"] for x in results[:3]],["HTTPStatusError:429"]*3)
        self.assertEqual(results[3]["provider_fallback_reason"],"provider_throttled")
        self.assertEqual(state["fallback_reasons"]["HTTPStatusError:429"],3)
        self.assertEqual(state["fallback_reasons"]["provider_throttled"],1)
        self.assertEqual(len(bing_calls),4)

    async def test_budget_exhaustion_falls_back_to_bing_without_http_call(self):
        os.environ["BRAVE_SEARCH_API_KEY"]="secret"
        http_calls=[]
        bing_calls=[]
        async def http_get(url,**kwargs):
            http_calls.append(url)
            return {"status":200,"json":{"web":{"results":[]}}}
        async def bing(query,limit):
            bing_calls.append((query,limit))
            return {"ok":True,"query":query,"results":[],"count":0,"provider":"bing"}
        state=sp.new_search_state()
        state["calls_cycle"]=10
        result,state=await sp.search_with_fallback(
            "x",2,
            bing_search=bing,
            state=state,
            max_calls_cycle=10,
            max_calls_day=150,
            http_get=http_get,
        )
        self.assertEqual(http_calls,[])
        self.assertEqual(bing_calls,[("x",2)])
        self.assertEqual(result["provider_fallback_reason"],"budget_exhausted")


if __name__=="__main__":
    unittest.main()
