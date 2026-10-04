from pathlib import Path
import unittest

class A2ADiscoveryStartupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        src=Path("cloud_mcp.py").read_text(encoding="utf-8")
        start=src.index("async def _advertise_public_agent()")
        end=src.index("\n\ndef _tokens",start)
        cls.body=src[start:end]

    def test_policy_state_is_published_before_external_registry_io(self):
        body=self.body
        publish=body.index('AUTOPILOT_STATE["a2a_discovery"]=dict(state)')
        first_io=body.index("httpx.AsyncClient")
        self.assertLess(publish,first_io)
        self.assertIn('"registry_enabled":enabled',body)
        self.assertIn('"registration_in_progress" if enabled else "disabled_by_policy"',body)

    def test_disabled_policy_still_returns_without_registry_io(self):
        body=self.body
        disabled=body.index("if not enabled:")
        first_io=body.index("httpx.AsyncClient")
        self.assertLess(disabled,first_io)
        self.assertIn('"last_registration_ok":False',body)

    def test_arena_champion_uses_concurrent_registry_io_with_three_second_cap(self):
        body=self.body
        self.assertIn("registry_timeout=3.0",body)
        self.assertIn("registry_rows=await asyncio.gather(",body)
        gather=body.index("registry_rows=await asyncio.gather(")
        allagents=body.index("advertise_allagents()",gather)
        community=body.index("advertise_community()",gather)
        global_registry=body.index("advertise_global()",gather)
        self.assertLess(allagents,community)
        self.assertLess(community,global_registry)

    def test_registry_clients_share_bounded_arena_timeout(self):
        body=self.body
        self.assertGreaterEqual(body.count("timeout=registry_timeout"),3)

if __name__=="__main__":
    unittest.main()
