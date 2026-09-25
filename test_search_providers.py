import os
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

import search_providers as sp

try:
    import httpx
except ImportError:
    httpx=None


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


    async def test_fallback_reason_is_counted_without_secret(self):
        secret="BRAVE-DO-NOT-LEAK"
        os.environ["BRAVE_SEARCH_API_KEY"]=secret
        async def http_get(url,**kwargs):
            return {"status":429,"json":{}}
        rows,state,meta=await sp.search(
            "workflow",2,state=sp.new_search_state(),http_get=http_get
        )
        self.assertEqual(state["fallback_reasons"],{"HTTPStatusError:429":1})
        self.assertEqual(sp.provider_diagnostics(state)["fallback_reasons"],{"HTTPStatusError:429":1})
        self.assertNotIn(secret,repr((state,meta,rows)))

    async def test_minimum_interval_between_provider_calls(self):
        os.environ["BRAVE_SEARCH_API_KEY"]="secret"
        clock=[100.0]
        sleeps=[]
        async def http_get(url,**kwargs):
            return {"status":200,"json":{"web":{"results":[]}}}
        async def sleep_fn(seconds):
            sleeps.append(seconds)
            clock[0]+=seconds
        def monotonic_fn():
            return clock[0]

        state=sp.new_search_state()
        _,state,_=await sp.search(
            "one",2,state=state,http_get=http_get,min_interval_ms=1100,
            sleep_fn=sleep_fn,monotonic_fn=monotonic_fn,
        )
        clock[0]+=0.1
        _,state,_=await sp.search(
            "two",2,state=state,http_get=http_get,min_interval_ms=1100,
            sleep_fn=sleep_fn,monotonic_fn=monotonic_fn,
        )
        self.assertEqual(len(sleeps),1)
        self.assertAlmostEqual(sleeps[0],1.0,places=3)

    async def test_secret_never_appears_in_state_metadata_or_exception(self):
        secret="SECRET-API-VALUE-123"
        os.environ["BRAVE_SEARCH_API_KEY"]=secret
        async def http_get(url,**kwargs):
            raise RuntimeError("transport failed")
        rows,state,meta=await sp.search("test",2,state=sp.new_search_state(),http_get=http_get)
        combined=repr({"rows":rows,"state":state,"meta":meta})
        self.assertNotIn(secret,combined)
        self.assertNotIn("BRAVE_SEARCH_API_KEY",combined)


    @unittest.skipIf(httpx is None,"httpx not installed")
    async def test_google_mocktransport_log_never_contains_key_or_cx(self):
        key="FAKE_SECRET_123"
        cx="FAKE_CX_456"
        os.environ["GOOGLE_PSE_KEY"]=key
        os.environ["GOOGLE_PSE_CX"]=cx
        sp.configure_http_client_logging()

        async def handler(request):
            return httpx.Response(
                200,
                request=request,
                json={"items":[{"title":"x","link":"https://example.com","snippet":"y"}]},
            )

        transport=httpx.MockTransport(handler)
        logger=__import__("logging").getLogger("httpx")
        old_level=logger.level
        logger.setLevel(__import__("logging").INFO)
        try:
            with self.assertLogs("httpx",level="INFO") as captured:
                async with httpx.AsyncClient(transport=transport) as client:
                    await client.get(
                        sp.GOOGLE_ENDPOINT,
                        params={"key":key,"cx":cx,"q":"workflow","num":1},
                    )
        finally:
            logger.setLevel(old_level)
        output="\n".join(captured.output)
        self.assertNotIn(key,output)
        self.assertNotIn(cx,output)
        self.assertNotIn("key="+key,output)
        self.assertNotIn("cx="+cx,output)

    @unittest.skipIf(httpx is None,"httpx not installed")
    async def test_brave_mocktransport_log_never_contains_header_secret(self):
        secret="FAKE_BRAVE_SECRET_789"
        os.environ["BRAVE_SEARCH_API_KEY"]=secret
        sp.configure_http_client_logging()

        async def handler(request):
            return httpx.Response(
                200,
                request=request,
                json={"web":{"results":[]}},
            )

        transport=httpx.MockTransport(handler)
        logger=__import__("logging").getLogger("httpx")
        old_level=logger.level
        logger.setLevel(__import__("logging").INFO)
        try:
            with self.assertLogs("httpx",level="INFO") as captured:
                async with httpx.AsyncClient(transport=transport) as client:
                    await client.get(
                        sp.BRAVE_ENDPOINT,
                        params={"q":"workflow","count":1},
                        headers={"X-Subscription-Token":secret},
                    )
        finally:
            logger.setLevel(old_level)
        output="\n".join(captured.output)
        self.assertNotIn(secret,output)
        self.assertNotIn("X-Subscription-Token",output)


if __name__=="__main__":
    unittest.main()
