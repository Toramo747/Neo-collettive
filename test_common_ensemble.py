import unittest

from tools import common_ensemble as ce


class Evaluate(unittest.TestCase):
    def test_ensemble_escalates_only_on_disagreement(self):
        rows = [{"n": 0, "label": "unsupported"}, {"n": 1, "label": "supported"}, {"n": 2, "label": "unsupported"}]
        a, b = ce.SMALL
        res = [{"n": 0, "big": "unsupported", "big_s": 4, "small_wall_s": 2, a: "unsupported", b: "unsupported"},
               {"n": 1, "big": "unsupported", "big_s": 4, "small_wall_s": 2, a: "supported", b: "supported"},
               {"n": 2, "big": "unsupported", "big_s": 4, "small_wall_s": 2, a: "supported", b: "unsupported"}]
        m = ce.evaluate(rows, res)
        self.assertEqual(m["single_14b"]["false_alarms"], 1)
        self.assertEqual(m["ensemble"]["caught"], 2)
        self.assertEqual(m["ensemble"]["false_alarms"], 0)
        self.assertEqual(m["ensemble"]["escalated_to_14b"], 1)
        self.assertEqual(m["ensemble"]["seconds"], 10.0)
        self.assertEqual(m["single_14b"]["seconds"], 12.0)


if __name__ == "__main__":
    unittest.main()


class EvidenceRule(unittest.TestCase):
    def test_claim_needs_an_exact_quote_we_can_find(self):
        src = "Our rule for a checkable claim was adopted on Common: one public link plus the exact sentence."
        self.assertEqual(ce.evidence_verdict({"kind": "claim", "evidence": "rule for a checkable claim was adopted"}, "x", src), "supported")
        self.assertEqual(ce.evidence_verdict({"kind": "claim", "evidence": "we check every lead verbatim always"}, "x", src), "unsupported")
        self.assertEqual(ce.evidence_verdict({"kind": "claim", "evidence": "adopted"}, "x", src), "unsupported")
        self.assertEqual(ce.evidence_verdict({"kind": "promise", "evidence": ""}, "x", src), "unsupported")
        self.assertEqual(ce.evidence_verdict({"kind": "greeting", "evidence": ""}, "x", src), "supported")
