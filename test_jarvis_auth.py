from __future__ import annotations

import unittest
from types import SimpleNamespace

import jarvis_service.app as jarvis


class JarvisAuthTests(unittest.TestCase):
    def setUp(self):
        self.old_secret=jarvis.JARVIS_SHARED_SECRET
        jarvis._ASK_CALLS.clear()

    def tearDown(self):
        jarvis.JARVIS_SHARED_SECRET=self.old_secret
        jarvis._ASK_CALLS.clear()

    def test_missing_secret_fails_closed(self):
        jarvis.JARVIS_SHARED_SECRET=""
        with self.assertRaises(Exception) as ctx:
            jarvis.authorize(None)
        self.assertEqual(getattr(ctx.exception,"status_code",None),503)

    def test_bearer_secret_is_required(self):
        jarvis.JARVIS_SHARED_SECRET="synthetic-secret"
        jarvis.authorize("Bearer synthetic-secret")
        with self.assertRaises(Exception) as ctx:
            jarvis.authorize("Bearer wrong")
        self.assertEqual(getattr(ctx.exception,"status_code",None),401)

    def test_ask_rate_limit_is_per_origin(self):
        req=SimpleNamespace(client=SimpleNamespace(host="198.51.100.25"))
        for _ in range(jarvis._ASK_RATE_LIMIT):
            jarvis._rate_limit_ask(req)
        with self.assertRaises(Exception) as ctx:
            jarvis._rate_limit_ask(req)
        self.assertEqual(getattr(ctx.exception,"status_code",None),429)


if __name__=="__main__":
    unittest.main()
