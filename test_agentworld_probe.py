import unittest
from unittest.mock import patch

from tools.agentworld_probe import probe


class AgentWorldProbePolicyTests(unittest.TestCase):
    def test_only_two_exact_urls_are_allowed(self):
        probe.validate_url(probe.ACTIVITY_URL)
        probe.validate_url(probe.DOCUMENT_URL)
        bad = [
            probe.DOCUMENT_URL + "?x=1",
            probe.ACTIVITY_URL + "?x=1",
            "http://" + probe.DOMAIN + "/.well-known/agentworld.json",
            "https://" + probe.DOMAIN + "/",
            "https://example.com/.well-known/agentworld.json",
        ]
        for url in bad:
            with self.subTest(url=url), self.assertRaises(ValueError):
                probe.validate_url(url)

    def test_non_get_methods_are_blocked(self):
        for method in ("POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"):
            with self.subTest(method=method), self.assertRaises(ValueError):
                probe.validate_method(method)

    def test_generic_user_agent_contains_no_mycelix_identity(self):
        ua = probe.USER_AGENT.lower()
        self.assertNotIn("mycelix", ua)
        self.assertNotIn("neo-collettive", ua)
        self.assertNotIn("onrender", ua)

    def test_limits_are_fixed(self):
        self.assertEqual(probe.TIMEOUT_SECONDS, 10)
        self.assertEqual(probe.MAX_BODY_BYTES, 1024 * 1024)

    def test_redirect_handler_never_builds_followup_request(self):
        handler = probe.NoRedirect()
        self.assertIsNone(handler.redirect_request(None, None, 302, "Found", {}, "https://example.com/"))

    def test_request_has_no_cookie_or_auth_headers(self):
        captured = {}

        class FakeResponse:
            status = 200
            headers = {"Content-Type": "application/json"}
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return False
            def read(self, n):
                return b"{}"

        class FakeOpener:
            def open(self, request, timeout):
                captured["headers"] = {k.lower(): v for k, v in request.header_items()}
                captured["timeout"] = timeout
                return FakeResponse()

        with patch("tools.agentworld_probe.probe.build_opener", return_value=FakeOpener()):
            record = probe.fetch_exact(probe.ACTIVITY_URL)

        headers = captured["headers"]
        self.assertNotIn("cookie", headers)
        self.assertNotIn("authorization", headers)
        self.assertNotIn("proxy-authorization", headers)
        self.assertEqual(captured["timeout"], 10)
        self.assertEqual(record["status"], 200)
        self.assertFalse(record["redirect_followed"])


if __name__ == "__main__":
    unittest.main()
