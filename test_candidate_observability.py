import hashlib
import unittest

from candidate_observability import build_candidate_telemetry
from gate_stability import apply_gate_hysteresis, opportunity_identity


class CandidateObservabilityTests(unittest.TestCase):
    def _row(self, tool="Invoice X", title="Invoice automation", sources=None):
        return {
            "family":"finance_ops",
            "tool_name":tool,
            "title":title,
            "target_user":"ops",
            "problem":"manual reconciliation",
            "gate_pass":True,
            "monetization_score":90,
            "missing":[],
            "trend":"Generated summary A",
            "sources":sources or [
                {"domain":"a.example","signal_types":["PAID_DEMAND"],"real_price":True},
                {"domain":"b.example","signal_types":["PAIN"],"real_price":True},
            ],
        }

    def _telemetry(self, row, secret="unit-test-secret", key_version="v1"):
        state,rows=apply_gate_hysteresis(
            {},
            [row],
            version="0.99.50",
            commit="0123456789abcdef0123456789abcdef01234567",
            observed_at_utc="2026-10-04T10:00:00Z",
        )
        return build_candidate_telemetry(
            rows,
            state,
            secret=secret,
            cycle=2000,
            commit="0123456789abcdef0123456789abcdef01234567",
            tagger_version="3",
            observed_at_utc="2026-10-04T10:00:10Z",
            first_cycle_after_deploy=True,
            id_key_version=key_version,
        )[0]

    def test_same_candidate_keeps_id_when_source_order_title_and_generated_text_change(self):
        a=self._row()
        b=self._row(
            title="A completely different generated title",
            sources=list(reversed(a["sources"])),
        )
        b["trend"]="Generated summary B"
        ta=self._telemetry(a)
        tb=self._telemetry(b)
        self.assertEqual(ta["candidate_id"],tb["candidate_id"])
        self.assertEqual(ta["evidence_fingerprint"],tb["evidence_fingerprint"])

    def test_two_candidates_same_family_get_different_ids(self):
        a=self._telemetry(self._row(tool="Invoice X"))
        b=self._telemetry(self._row(tool="Invoice Y"))
        self.assertNotEqual(a["candidate_id"],b["candidate_id"])

    def test_candidate_id_is_keyed_not_plain_sha256(self):
        row=self._row()
        telemetry=self._telemetry(row)
        plain=hashlib.sha256(opportunity_identity(row).encode("utf-8")).hexdigest()[:16]
        self.assertNotEqual(telemetry["candidate_id"],plain)

    def test_id_key_version_marks_rotation_and_changes_identifier(self):
        a=self._telemetry(self._row(),key_version="v1")
        b=self._telemetry(self._row(),key_version="v2")
        self.assertEqual(a["id_key_version"],"v1")
        self.assertEqual(b["id_key_version"],"v2")
        self.assertNotEqual(a["candidate_id"],b["candidate_id"])

    def test_only_fixed_missing_codes_are_emitted(self):
        row=self._row()
        row["gate_pass"]=False
        row["missing"]=["documented_gap","https://secret.example/x","free text"]
        telemetry=self._telemetry(row)
        self.assertEqual(telemetry["missing_codes"],["documented_gap"])


if __name__=="__main__":
    unittest.main()
