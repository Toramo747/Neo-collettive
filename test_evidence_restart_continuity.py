"""Offline regression tests for cross-restart evidence continuity."""
import unittest

from commercial_evidence_store import encode_external_store, decode_external_store
from evidence_restart_continuity import verify_restart_continuity, preserve_checkpoint_continuity_status


def rows(n):
    return [
        {"evidence_id": f"ev-{i}", "last_seen_epoch": 1800000000 + i,
         "gate_eligible": i % 4 == 0}
        for i in range(n)
    ]


def exercise(previous, current, *, corrupt_previous=False):
    ref_old, chunks = encode_external_store(
        previous, store="render_env_chunks_v2", chunk_bytes=1024
    )
    ref_new, _ = encode_external_store(
        current, store="render_env_chunks_v2",
        chunk_bytes=1024, previous_generation=ref_old
    )
    payload = {
        "commercial_evidence_store_reference": ref_new,
        "commercial_evidence_memory": list(current),
        "evidence_store_status": {"status": "ok", "active_count": len(current)},
        "evidence_store_degraded": False,
    }
    def decode(ref):
        return decode_external_store(ref, ["broken"] if corrupt_previous else chunks)
    return verify_restart_continuity(
        payload, decode_previous=decode,
        evidence_key=lambda row: row["evidence_id"]
    )


class RestartContinuityTests(unittest.TestCase):
    def test_200_to_147_blocks_overwrite_and_preserves_both_sets(self):
        old = rows(200)
        new = old[:147]
        payload, status = exercise(old, new)
        self.assertEqual(status["status"], "continuity_blocked")
        self.assertEqual(status["missing_count"], 53)
        self.assertTrue(payload["evidence_store_degraded"])
        self.assertEqual(len(payload["commercial_evidence_memory"]), 200)
        self.assertEqual(
            payload["evidence_store_status"]["missing_from_new_generation"], 53
        )
        self.assertEqual(
            {r["evidence_id"] for r in payload["commercial_evidence_memory"]},
            {r["evidence_id"] for r in old},
        )

    def test_growth_across_restart_verifies(self):
        old = rows(147)
        new = rows(200)
        payload, status = exercise(old, new)
        self.assertEqual(status["status"], "verified")
        self.assertEqual(status["missing_count"], 0)
        self.assertFalse(payload["evidence_store_degraded"])

    def test_same_size_replacement_still_blocks_missing_identity(self):
        old = rows(3)
        new = old[:2] + [{"evidence_id": "different"}]
        payload, status = exercise(old, new)
        self.assertEqual(status["missing_count"], 1)
        self.assertTrue(payload["evidence_store_degraded"])
        self.assertEqual(len(payload["commercial_evidence_memory"]), 4)

    def test_corrupt_previous_is_not_claimed_verified(self):
        payload, status = exercise(rows(5), rows(6), corrupt_previous=True)
        self.assertEqual(status["status"], "continuity_unverified")
        self.assertTrue(payload["evidence_store_degraded"])
        self.assertEqual(len(payload["commercial_evidence_memory"]), 6)

    def test_missing_reference_does_not_change_state(self):
        initial = {"commercial_evidence_memory": rows(2)}
        payload, status = verify_restart_continuity(
            initial, decode_previous=lambda ref: None,
            evidence_key=lambda row: row["evidence_id"]
        )
        self.assertEqual(status["status"], "no_external_reference")
        self.assertEqual(payload, initial)

    def test_proven_archive_is_allowed(self):
        previous = rows(5)
        current = previous[:3]
        old_ref, old_chunks = encode_external_store(previous, store="render_env_chunks_v2")
        new_ref, _ = encode_external_store(current, store="render_env_chunks_v2", previous_generation=old_ref)
        payload = {"commercial_evidence_store_reference": new_ref,
                   "commercial_evidence_memory": current,
                   "commercial_evidence_archive_rows": previous[3:],
                   "evidence_store_status": {"status": "ok"}}
        out, status = verify_restart_continuity(
            payload,
            decode_previous=lambda ref: decode_external_store(ref, old_chunks),
            evidence_key=lambda row: row["evidence_id"],
            now_epoch=1800000500,
        )
        self.assertEqual(status["status"], "verified")
        self.assertEqual(status["archived_count"], 2)
        self.assertFalse(out.get("evidence_store_degraded", False))

    def test_proven_retention_is_allowed(self):
        previous = rows(4)
        previous[3]["last_seen_epoch"] = 1700000000
        current = previous[:3]
        old_ref, old_chunks = encode_external_store(previous, store="render_env_chunks_v2")
        new_ref, _ = encode_external_store(current, store="render_env_chunks_v2", previous_generation=old_ref)
        payload = {"commercial_evidence_store_reference": new_ref,
                   "commercial_evidence_memory": current}
        out, status = verify_restart_continuity(
            payload, decode_previous=lambda ref: decode_external_store(ref, old_chunks),
            evidence_key=lambda row: row["evidence_id"], now_epoch=1800000500,
        )
        self.assertEqual(status["status"], "verified")
        self.assertEqual(status["expired_count"], 1)
        self.assertFalse(out.get("evidence_store_degraded", False))

    def test_fallback_to_previous_is_held(self):
        previous = rows(4)
        payload, status = exercise(previous, previous)
        ref, chunks = encode_external_store(previous, store="render_env_chunks_v2")
        value = {"commercial_evidence_store_reference": ref,
                 "commercial_evidence_memory": previous}
        out, result = verify_restart_continuity(
            value, decode_previous=lambda r: previous,
            evidence_key=lambda row: row["evidence_id"],
            restore_status="recovered_previous_generation",
        )
        self.assertEqual(result["status"], "continuity_unverified")
        self.assertTrue(out["evidence_store_degraded"])

    def test_missing_predecessor_reference_blocks_checkpoint_promotion(self):
        old = rows(5)
        ref, _ = encode_external_store(old, store="render_env_chunks_v2")
        payload = {"commercial_evidence_store_reference": ref,
                   "commercial_evidence_memory": old,
                   "evidence_store_status": {"status": "ok"}}
        out, status = verify_restart_continuity(
            payload, decode_previous=lambda _: None,
            evidence_key=lambda row: row["evidence_id"]
        )
        self.assertEqual(status["status"], "continuity_unverified")
        self.assertTrue(out["evidence_store_degraded"])
        self.assertEqual(out["commercial_evidence_store_reference"], ref)

    def test_restart_warning_survives_checkpoint(self):
        old = rows(200)
        new = old[:147]
        changed, info = exercise(old, new)
        self.assertEqual(info["missing_count"], 53)
        checkpoint = preserve_checkpoint_continuity_status(
            changed["evidence_store_status"],
            {"status": "degraded", "active_count": len(changed["commercial_evidence_memory"]),
             "expected_active_count": len(new)}
        )
        self.assertEqual(checkpoint["status"], "continuity_blocked")
        self.assertEqual(checkpoint["missing_from_new_generation"], 53)
        self.assertEqual(checkpoint["active_count"], 200)
        again = preserve_checkpoint_continuity_status(checkpoint, dict(checkpoint))
        self.assertEqual(again, checkpoint)

    def test_normal_degraded_checkpoint_is_unchanged(self):
        status = {"status": "degraded", "active_count": 2}
        self.assertEqual(
            preserve_checkpoint_continuity_status({"status": "ok"}, status), status
        )

    def test_source_does_not_write_any_identifiers_to_public_telemetry(self):
        old = rows(5)
        payload, status = exercise(old, old[:1])
        self.assertNotIn("ev-1", str(status))
        self.assertNotIn("ev-1", str(payload["evidence_store_status"]))


if __name__ == "__main__":
    unittest.main()
