import unittest

import claim_evidence as ce


class ClaimEvidence(unittest.TestCase):
    def test_split_keeps_greetings_and_chinese(self):
        self.assertEqual(ce.split_sentences("@hermes Thanks! We do X. 我们已经记录了。"),
                         ["@hermes Thanks!", "We do X.", "我们已经记录了。"])

    def test_split_keeps_versions_and_ellipsis(self):
        self.assertEqual(ce.split_sentences('@MarxSignal The rule as of v0.99.68 holds. A quote marked with "..." or … stays whole... Next one.'),
                         ["@MarxSignal The rule as of v0.99.68 holds.", 'A quote marked with "..." or … stays whole... Next one.'])
        self.assertEqual(ce.split_sentences("13/15 words gives 0.83. Done!"), ["13/15 words gives 0.83.", "Done!"])

    def test_verdicts(self):
        src = "verify_quote is free and has no key. Our rule for a checkable claim was adopted on Common."
        self.assertEqual(ce.evidence_verdict({"kind": "claim", "evidence": "rule for a checkable claim was adopted"}, "", src), "supported")
        self.assertEqual(ce.evidence_verdict({"kind": "claim", "evidence": "we check every lead before evidence"}, "", src), "unsupported")
        self.assertEqual(ce.evidence_verdict({"kind": "promise", "evidence": ""}, "", src), "unsupported")


if __name__ == "__main__":
    unittest.main()
