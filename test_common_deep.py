import unittest

from tools import common_deep as cd


class Guard(unittest.TestCase):
    def d(self, body, cat="factual", agent="hermes", reply=True):
        return {"agent": agent, "body": body, "category": cat, "should_reply": reply}

    def test_clean_draft_passes(self):
        self.assertEqual(cd.guard(self.d("@hermes Thanks, we verified it: 5 of 7 quotes are real."), ""), [])

    def test_blocks_secrets_money_code_urls_commitments(self):
        self.assertIn("secret_like", cd.guard(self.d("@hermes here is our api key"), ""))
        self.assertIn("money", cd.guard(self.d("@hermes we can pay $50 for it"), ""))
        self.assertIn("code", cd.guard(self.d("@hermes run curl http://x"), ""))
        self.assertIn("url_not_allowed", cd.guard(self.d("@hermes see https://evil.example/x"), ""))
        self.assertIn("commitment_needs_andrea", cd.guard(self.d("@hermes we will ship by Monday", cat="commitment"), ""))
        self.assertIn("not_addressed", cd.guard(self.d("Thanks!"), ""))

    def test_urls_from_source_or_allowlist_are_ok(self):
        src = "see https://github.com/a/b/pull/84"
        self.assertEqual(cd.guard(self.d("@hermes verified https://github.com/a/b/pull/84 and https://commons.dooza.ai/notes/38"), src), [])

    def test_skip_needs_no_checks(self):
        self.assertEqual(cd.guard(self.d("", reply=False), ""), [])


if __name__ == "__main__":
    unittest.main()
