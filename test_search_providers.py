import os
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

import search_providers as sp


class SearchProviderTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.env_patch=patch.dict(os.environ,{},clear=True)
        self.env_patch.start()

    def tearDown(self):
        self.env_patch.stop()

    async def test_without_key_requests_bing_fallback(self):
        rows,state,meta=await sp.search("manual workflow",5,state=sp.new_search_state())
        self.assertEqual(rows,[])
        self.assertTrue(meta["fallback"])
        self.assertEqual(meta["provider"],"bing")
        self.assertEqual(state["calls_cycle"],0)
        self.assertEqual(state["calls_day"],0)

    async def test_brave_key_uses_official_contract(self):
        os.environ["BRAVE_SEARCH_API_KEY"]="super-secret-brave"
        calls=[]
        async def http_get(url,**kwargs):
            calls.append((url,kwargs))
            return {
                "status":200,
                "json":{"web":{"results":[{
                    "title":"Need help automating reports",
                    "url":"https://example.org/problem",
                    "description":"Manual reporting takes hours every week.",
                }]}}
            }
        rows,state,meta=await sp.search(
            "manual reporting",4,state=sp.new_search_state(),http_get=http_get
        )
        self.assertFalse(meta["fallback"])
        self.assertEqual(meta["provider"],"brave")
        self.assertEqual(rows[0]["source"],"brave-search")
        url,kwargs=calls[0]
        self.assertEqual(url,sp.BRAVE_ENDPOINT)
        self.assertEqual(kwargs["params"],{"q":"manual reporting","count":4})
        self.assertEqual(kwargs["headers"]["X-Subscription-Token"],"super-secret-brave")
        self.assertEqual(state["calls_cycle"],1)
        self.assertEqual(state["calls_day"],1)

    async def test_google_key_and_cx_use_official_contract(self):
        os.environ["NEO_SEARCH_PROVIDER"]="google"
        os.environ["GOOGLE_PSE_KEY"]="super-secret-google"
        os.environ["GOOGLE_PSE_CX"]="cx-secret"
        calls=[]
        async def http_get(url,**kwargs):
            calls.append((url,kwargs))
            return {
                "status":200,
                "json":{"items":[{
                    "title":"Buyer asks for automation",
                    "link":"https://example.net/buyer",
                    "snippet":"Looking for help with a repetitive workflow.",
                }]}
            }
        rows,state,meta=await sp.search(
            "workflow",3,state=sp.new_search_state(),http_get=http_get
        )
        self.assertFalse(meta["fallback"])
        self.assertEqual(meta["provider"],"google")
        self.assertEqual(rows[0]["source"],"google-pse")
        url,kwargs=calls[0]
        self.assertEqual(url,sp.GOOGLE_ENDPOINT)
        self.assertEqual(
            kwargs["params"],
            {"key":"super-secret-google","cx":"cx-secret","q":"workflow","num":3},
        )

    async def test_401_and_429_are_sanitized_fallbacks(self):
        secret="DO-NOT-LEAK-THIS"
        os.environ["BRAVE_SEARCH_API_KEY"]=secret
        for status in (401,429):
            async def http_get(url,**kwargs):
                return {"status":status,"json":{}}
            rows,state,meta=await sp.search(
                "workflow",3,state=sp.new_search_state(),http_get=http_get
            )
            self.assertEqual(rows,[])
            self.assertTrue(meta["fallback"])
            self.assertEqual(meta["reason"],"HTTPStatusError:"+str(status))
            self.assertNotIn(secret,repr((state,meta,rows)))

    async def test_cycle_limit_is_respected(self):
        os.environ["BRAVE_SEARCH_API_KEY"]="secret"
        async def http_get(url,**kwargs):
            return {"status":200,"json":{"web":{"results":[]}}}
        state=sp.new_search_state()
        _,state,_=await sp.search("one",2,state=state,max_calls_cycle=1,max_calls_day=10,http_get=http_get)
        _,state,meta=await sp.search("two",2,state=state,max_calls_cycle=1,max_calls_day=10,http_get=http_get)
        self.assertTrue(meta["fallback"])
        self.assertEqual(meta["reason"],"budget_exhausted")
        self.assertEqual(state["calls_cycle"],1)
        self.assertEqual(state["calls_day"],1)

    async def test_day_limit_is_respected(self):
        os.environ["BRAVE_SEARCH_API_KEY"]="secret"
        state=sp.new_search_state()
        state.update({"calls_day":2,"calls_cycle":0})
        rows,state,meta=await sp.search(
            "workflow",2,state=state,max_calls_cycle=10,max_calls_day=2,
            http_get=lambda *a,**k: None,
        )
        self.assertEqual(rows,[])
        self.assertTrue(meta["fallback"])
        self.assertEqual(meta["reason"],"budget_exhausted")
        self.assertEqual(state["calls_day"],2)

    def test_day_counter_survives_cycle_reset_and_resets_next_day(self):
        state={
            "day_utc":"2026-09-25",
            "calls_day":37,
            "cycle_id":347,
            "calls_cycle":8,
            "errors":2,
            "fallbacks":3,
            "last_provider":"brave",
        }
        same=sp.begin_cycle(state,348,datetime(2026,9,25,18,0,tzinfo=timezone.utc))
        self.assertEqual(same["calls_day"],37)
        self.assertEqual(same["calls_cycle"],0)
        self.assertEqual(same["errors"],0)
        self.assertEqual(same["fallbacks"],0)
        next_day=sp.begin_cycle(same,349,datetime(2026,9,26,1,0,tzinfo=timezone.utc))
        self.assertEqual(next_day["calls_day"],0)

    async def test_secret_never_appears_in_state_metadata_or_exception(self):
        secret="SECRET-API-VALUE-123"
        os.environ["BRAVE_SEARCH_API_KEY"]=secret
        async def http_get(url,**kwargs):
            raise RuntimeError("transport failed")
        rows,state,meta=await sp.search("test",2,state=sp.new_search_state(),http_get=http_get)
        combined=repr({"rows":rows,"state":state,"meta":meta})
        self.assertNotIn(secret,combined)
        self.assertNotIn("BRAVE_SEARCH_API_KEY",combined)


if __name__=="__main__":
    unittest.main()
