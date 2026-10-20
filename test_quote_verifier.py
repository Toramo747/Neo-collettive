import asyncio
import unittest
from unittest import mock

import mcp_endpoint_verifier as ev
import quote_verifier as qv

PAGE = """<html><head><script>var x = "Post one specific thing";</script></head>
<body><p>Post one specific thing: say what you have built or done, then ask one concrete question.</p>
<p>The re-count went from 4 of 7 to 5 of 7 real, 1 paraphrase, 1 unverifiable.</p></body></html>"""


class Judge(unittest.TestCase):
    def test_verbatim(self):
        r = qv.judge("Post one specific thing: say what you have built or done, then ask one concrete question", PAGE)
        self.assertEqual(r["outcome"], "verbatim")

    def test_cut_with_ellipsis_is_verbatim(self):
        r = qv.judge("Post one specific thing: say what you have built … then ask one concrete question", PAGE)
        self.assertEqual(r["outcome"], "verbatim")

    def test_paraphrase(self):
        r = qv.judge("Post one specific thing: tell people what you have built or done, then ask one concrete question", PAGE)
        self.assertEqual(r["outcome"], "paraphrase")

    def test_invented_text_is_not_found(self):
        r = qv.judge("Agents must pay a fee before their first post is published here", PAGE)
        self.assertEqual(r["outcome"], "not_found")

    def test_script_text_does_not_count(self):
        r = qv.judge("var x = Post one specific thing", "<script>var x = Post one specific thing</script><p>hello</p>")
        self.assertEqual(r["outcome"], "not_found")


class Verify(unittest.TestCase):
    def setUp(self):
        ev.reset_runtime_state_for_tests()

    def test_rejects_short_and_long_quotes(self):
        self.assertEqual(asyncio.run(qv.verify_quote("https://example.com", "hi"))["error"], "quote_too_short")
        self.assertEqual(asyncio.run(qv.verify_quote("https://example.com", "word " * 200))["error"], "quote_too_long")

    def test_private_targets_are_unreachable_not_fetched(self):
        for url in ("http://example.com/x", "https://127.0.0.1/x", "https://localhost/x", "https://user:pw@example.com/"):
            r = asyncio.run(qv.verify_quote(url, "one two three four"))
            self.assertEqual(r["outcome"], "unreachable", url)

    def test_verbatim_with_mocked_fetch(self):
        async def fake(url):
            return {"final_url": url, "host": "example.com", "status": 200, "bytes": len(PAGE), "text": PAGE}
        with mock.patch.object(qv, "_fetch", fake):
            r = asyncio.run(qv.verify_quote("https://example.com/a", "the re-count went from 4 of 7 to 5 of 7 real"))
        self.assertEqual(r["outcome"], "verbatim")
        self.assertIn("who wrote it", r["note"].lower())


class StitchedQuoteTests(unittest.TestCase):
    """20/10, found by MarxSignal: '…' must not join far-apart or reordered pieces."""
    PAGE = ("The board approved the merger in principle. " + "Unrelated filler text goes here. " * 40
            + "Shareholders will not receive any dividend this year.")

    def test_far_apart_pieces_are_stitched_not_verbatim(self):
        r = qv.judge("The board approved the merger … shareholders will not receive any dividend", self.PAGE)
        self.assertEqual(r["outcome"], "stitched")

    def test_reordered_pieces_are_stitched(self):
        page = "alpha beta gamma delta one. epsilon zeta eta theta two."
        r = qv.judge("epsilon zeta eta theta … alpha beta gamma delta", page)
        self.assertEqual(r["outcome"], "stitched")

    def test_close_cut_in_order_stays_verbatim(self):
        page = "We checked the source carefully before we repeated the claim to anyone."
        r = qv.judge("We checked the source … repeated the claim to anyone", page)
        self.assertEqual(r["outcome"], "verbatim")


if __name__ == "__main__":
    unittest.main()
