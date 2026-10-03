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

if __name__=="__main__":
    unittest.main()
