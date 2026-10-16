import sys
import unittest

sys.path.insert(0, "tools")
import verify_quotes as v  # noqa: E402

PAGE = "Developer Pankaj Kumar listed the symptoms: faster answers, worse quality, and a suspicion OpenAI 'reduced the compute'."


class QuoteSegmentTests(unittest.TestCase):
    def test_truncated_quote_with_ellipsis_matches(self):
        self.assertTrue(v.quote_in("Developer Pankaj Kumar listed the symptoms: faster answers, worse quality, and a suspicion OpenAI 'reduced the...", PAGE))

    def test_mid_word_cut_is_tolerated(self):
        self.assertTrue(v.quote_in("listed the symptoms: faster answ… worse quality, and a suspicion", PAGE))

    def test_invented_text_still_fails(self):
        self.assertFalse(v.quote_in("faster answers, worse quality... nobody at OpenAI flagged it", PAGE))

    def test_plain_exact_quote(self):
        self.assertTrue(v.quote_in("worse quality, and a suspicion", PAGE))
        self.assertFalse(v.quote_in("better quality", PAGE))


if __name__ == "__main__":
    unittest.main()
