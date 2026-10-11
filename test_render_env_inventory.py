"""Offline tests for the read-only Render env inventory tool (synthetic data)."""
import importlib.util
import unittest
from pathlib import Path

from commercial_evidence_store import encode_external_store

_spec = importlib.util.spec_from_file_location("render_env_inventory", Path(__file__).parent / "tools" / "render_env_inventory.py")
inv = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(inv)


class InventoryToolTests(unittest.TestCase):
    def test_decode_generation_verifies_hash(self):
        rows = [{"evidence_id": f"x-{i}"} for i in range(30)]
        ref, chunks = encode_external_store(rows, chunk_bytes=256, store="render_env_chunks_v2")
        ok, sha, decoded = inv.decode_generation(chunks)
        self.assertTrue(ok)
        self.assertEqual(sha[:12], ref["generation"])
        self.assertEqual(len(decoded), 30)
        self.assertFalse(inv.decode_generation(chunks[:-1] if len(chunks) > 1 else ["xz64:broken"])[0])

    def test_family_classification(self):
        self.assertEqual(inv.family_of("NEO_EVIDENCE_ARCHIVE_aaaaaaaaaaaa_0"), "evidence_archive")
        self.assertEqual(inv.family_of("NEO_EVIDENCE_aaaaaaaaaaaa_0"), "evidence_active")
        self.assertEqual(inv.family_of("BACKUP_20261007T022000Z_ENV_NEO_STATE_JSON"), "backup_sets")
        self.assertEqual(inv.family_of("RENDER_API_KEY"), "other")

    def test_referenced_chain(self):
        a, _ = encode_external_store([{"evidence_id": "a"}], store="render_env_chunks_v2")
        b, _ = encode_external_store([{"evidence_id": "b"}], store="render_env_chunks_v2", previous_generation=a)
        self.assertEqual(inv.referenced_generations(b), [b["generation"], a["generation"]])


class ClassifyTests(unittest.TestCase):
    def test_retention_buckets(self):
        now = 2_000_000_000
        rows = [
            {"last_seen_epoch": now - 22 * 86400},
            {"last_seen_epoch": now - 86400, "gate_eligible": True},
            {"last_seen_epoch": now - 86400},
            {},
        ]
        self.assertEqual(inv.classify(rows, now), {
            "expired_by_retention": 1, "within_retention": 2,
            "within_retention_gate_eligible": 1, "no_last_seen": 1,
        })


if __name__ == "__main__":
    unittest.main()
