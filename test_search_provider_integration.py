import os
import unittest
from unittest.mock import AsyncMock, patch

import cloud_mcp


class SearchProviderIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        cloud_mcp.AUTOPILOT_STATE["search_provider_state"]={}

    async def test_without_configured_key_uses_bing(self):
        bing={"ok":True,"query":"x","results":[{"title":"B","url":"https://example.com","snippet":"s","source":"bing-rss-free"}],"count":1,"provider":"bing"}
        with patch.object(cloud_mcp,"provider_search",AsyncMock(return_value=(
            [],{} ,{"provider":"bing","fallback":True,"reason":"provider_unconfigured_or_bing"}
        ))), patch.object(cloud_mcp,"_bing_rss_search",AsyncMock(return_value=dict(bing))) as fb:
            result=await cloud_mcp.free_web_search("x",2)
        self.assertEqual(result["provider"],"bing")
        self.assertEqual(result["results"][0]["source"],"bing-rss-free")
        fb.assert_awaited_once()

    async def test_configured_provider_result_does_not_call_bing(self):
        rows=[{"title":"P","url":"https://example.com/p","snippet":"buyer pain","source":"brave-search"}]
        with patch.object(cloud_mcp,"provider_search",AsyncMock(return_value=(
            rows,{"last_provider":"brave","calls_cycle":1,"calls_day":1},
            {"provider":"brave","fallback":False,"reason":"ok"}
        ))), patch.object(cloud_mcp,"_bing_rss_search",AsyncMock()) as fb:
            result=await cloud_mcp.free_web_search("x",2)
        self.assertEqual(result["provider"],"brave")
        self.assertEqual(result["results"][0]["source"],"brave-search")
        fb.assert_not_awaited()

    async def test_provider_401_or_429_falls_back_to_bing(self):
        for status in (401,429):
            bing={"ok":True,"query":"x","results":[],"count":0,"provider":"bing"}
            with patch.object(cloud_mcp,"provider_search",AsyncMock(return_value=(
                [],
                {"last_provider":"brave","calls_cycle":1,"calls_day":1,"errors":1,"fallbacks":1},
                {"provider":"brave","fallback":True,"reason":"HTTPStatusError:"+str(status)}
            ))), patch.object(cloud_mcp,"_bing_rss_search",AsyncMock(return_value=dict(bing))) as fb:
                result=await cloud_mcp.free_web_search("x",2)
            self.assertEqual(result["provider"],"bing")
            self.assertEqual(result["provider_fallback_from"],"brave")
            self.assertEqual(result["provider_fallback_reason"],"HTTPStatusError:"+str(status))
            fb.assert_awaited_once()

    def test_state_payload_never_contains_search_secret(self):
        secret="NEVER-PERSIST-THIS-SECRET"
        with patch.dict(os.environ,{"BRAVE_SEARCH_API_KEY":secret},clear=False):
            payload=cloud_mcp._state_payload()
        self.assertNotIn(secret,repr(payload))
        self.assertNotIn("BRAVE_SEARCH_API_KEY",repr(payload))


if __name__=="__main__":
    unittest.main()
