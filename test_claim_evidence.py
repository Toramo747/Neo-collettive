import unittest

import claim_evidence as ce


class ClaimEvidence(unittest.TestCase):
    def test_split_keeps_greetings_and_chinese(self):
        self.assertEqual(ce.split_sentences("@hermes Thanks! We do X. 我们已经记录了。"),
                         ["@hermes Thanks!", "We do X.", "我们已经记录了。"])

    def test_verdicts(self):
        src = "verify_quote is free and has no key. Our rule for a checkable claim was adopted on Common."
        self.assertEqual(ce.evidence_verdict({"kind": "claim", "evidence": "rule for a checkable claim was adopted"}, "", src), "supported")
        self.assertEqual(ce.evidence_verdict({"kind": "claim", "evidence": "we check every lead before evidence"}, "", src), "unsupported")
        self.assertEqual(ce.evidence_verdict({"kind": "promise", "evidence": ""}, "", src), "unsupported")
        self.assertEqual(ce.evidence_verdict({"kind": "request", "evidence": ""}, "", src), "supported")


if __name__ == "__main__":
    unittest.main()
