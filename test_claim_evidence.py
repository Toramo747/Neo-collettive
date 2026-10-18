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


    def test_five_consecutive_source_words_remain_mandatory_for_claims(self):
        source = "The quiet beacon records seven distinct signals before sunrise."
        for evidence in ("records seven distinct signals", "records seven invented distinct signals"):
            self.assertEqual(ce.evidence_verdict({"kind": "claim", "evidence": evidence},
                                               "A paraphrase of the observation.", source), "unsupported")
        self.assertEqual(ce.evidence_verdict({"kind": "claim", "evidence": "beacon records seven distinct signals"},
                                           "A paraphrase of the observation.", source), "supported")

    def test_a_source_promise_does_not_authorize_a_reply_promise(self):
        source = "I will publish the complete public result tomorrow morning."
        self.assertEqual(ce.evidence_verdict({"kind": "promise", "evidence": source}, source, source), "unsupported")

    def test_normalized_typography_does_not_change_evidence_words(self):
        source = "The observer’s notebook says “check the original source” before sharing."
        copied = "observer's notebook says \"check the original source\""
        self.assertEqual(ce.evidence_verdict({"kind": "claim", "evidence": copied}, "A supported paraphrase.", source), "supported")


if __name__ == "__main__":
    unittest.main()
