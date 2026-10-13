import unittest
from pathlib import Path


class A2AEndpointPolicyTests(unittest.TestCase):
    def test_a2a_endpoint_has_no_async_callback_or_http_client(self):
        source=Path("cloud_mcp.py").read_text(encoding="utf-8")
        start=source.index("async def a2a_endpoint")
        end=source.index("\n\nasync def api_trust_evaluate",start)
        body=source[start:end]
        self.assertNotIn("httpx.",body)
        self.assertNotIn("asyncio.create_task",body)
        self.assertIn("pushNotificationConfig",body)
        self.assertIn("push_notification_ignored",body)

    def test_response_generator_is_pure_module_without_network_or_tools(self):
        source=Path("a2a_dialogue.py").read_text(encoding="utf-8")
        self.assertNotIn("httpx",source)
        self.assertNotIn("requests",source)
        self.assertNotIn("subprocess",source)
        self.assertNotIn("socket",source)
        self.assertNotIn("os.environ",source)


if __name__=="__main__":
    unittest.main()
