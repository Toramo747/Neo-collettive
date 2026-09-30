from __future__ import annotations

import pathlib
import unittest


class JarvisAuthSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source=pathlib.Path("jarvis_service/app.py").read_text(encoding="utf-8")

    def test_ask_auth_is_fail_closed_and_constant_time(self):
        self.assertIn('if not JARVIS_SHARED_SECRET:',self.source)
        self.assertIn('status_code=503',self.source)
        self.assertIn('hmac.compare_digest',self.source)

    def test_ask_get_and_post_are_authenticated(self):
        self.assertIn('@app.get("/ask")',self.source)
        self.assertIn('@app.post("/ask")',self.source)
        self.assertGreaterEqual(self.source.count('authorize(authorization)'),2)

    def test_ask_has_rate_limit(self):
        self.assertIn('_ASK_RATE_LIMIT = 30',self.source)
        self.assertIn('_rate_limit_ask(request)',self.source)
        self.assertIn('status_code=429',self.source)


if __name__=="__main__":
    unittest.main()
