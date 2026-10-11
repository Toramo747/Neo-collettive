"""Offline tests for orphan planning/backup (synthetic env, no network)."""
import importlib.util
import json
import sys
import tempfile
import time
import unittest
from pathlib import Path

from commercial_evidence_store import encode_external_store
from state_codec import encode_checkpoint

sys.path.insert(0, str(Path(__file__).parent / "tools"))
_spec = importlib.util.spec_from_file_location("render_env_orphans", Path(__file__).parent / "tools" / "render_env_orphans.py")
orph = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(orph)

NOW = time.time()


def gen(prefix, rows, previous=None):
    ref, chunks = encode_external_store(rows, chunk_bytes=2048, store="render_env_chunks_v2", previous_generation=previous)
    return ref, {f"{prefix}{ref['generation']}_{i}": c for i, c in enumerate(chunks)}


def rows(ids):
    return [{"evidence_id": f"e-{i}", "last_seen_epoch": NOW} for i in ids]


class OrphanPlanTests(unittest.TestCase):
    def setUp(self):
        prev, e_prev = gen("NEO_EVIDENCE_", rows(range(170)))
        head, e_head = gen("NEO_EVIDENCE_", rows(range(172)), previous=prev)
        lost, e_lost = gen("NEO_EVIDENCE_", rows(range(203)))        # holds 31 missing identities
        dup, e_dup = gen("NEO_EVIDENCE_", rows(range(200)))          # subset of `lost`
        old, e_old = gen("NEO_EVIDENCE_", rows(range(100)))          # nothing missing
        ch, c_cur = gen("NEO_CHALLENGE_TRACK_", [{"track": 2}])
        ch_old, c_old = gen("NEO_CHALLENGE_TRACK_", [{"track": 1}])
        state = {"commercial_evidence_store_reference": head, "challenge_track_store_reference": ch}
        self.env = {"NEO_STATE_JSON": encode_checkpoint(state, 100000)[0], "OTHER_SECRET": "s"}
        for part in (e_prev, e_head, e_lost, e_dup, e_old, c_cur, c_old):
            self.env.update(part)
        self.ids = {"prev": prev["generation"], "head": head["generation"], "lost": lost["generation"],
                    "dup": dup["generation"], "old": old["generation"], "ch": ch["generation"], "ch_old": ch_old["generation"]}

    def test_plan_keeps_referenced_and_reintegration_sources(self):
        plan = orph.compute_plan(self.env)
        deleted = {k.split("_")[-2] for k in plan["delete_keys"]}
        self.assertEqual(plan["kept_for_reintegration"], [self.ids["lost"]])
        self.assertEqual(deleted, {self.ids["dup"], self.ids["old"], self.ids["ch_old"]})
        for keep in ("prev", "head", "lost", "ch"):
            self.assertNotIn(self.ids[keep], deleted)
        self.assertNotIn("OTHER_SECRET", plan["delete_keys"])
        self.assertEqual(plan["bytes_total_after"], plan["bytes_total_before"] - plan["bytes_freed"])

    def test_plan_refuses_without_readable_state(self):
        env = dict(self.env)
        env["NEO_STATE_JSON"] = "garbage"
        with self.assertRaises(ValueError):
            orph.compute_plan(env)

    def test_backup_is_verified_and_excludes_secrets(self):
        with tempfile.TemporaryDirectory() as d:
            out = orph.backup(d, self.env)
            root = Path(d) / out["dir"]
            manifest = json.loads((root / "manifest.json").read_text())
            self.assertNotIn("OTHER_SECRET", manifest["keys"])
            self.assertIn("NEO_STATE_JSON", manifest["keys"])
            self.assertEqual(out["keys"], len(self.env) - 1)

    def test_apply_refuses_changed_plan_or_missing_backup(self):
        plan = orph.compute_plan(self.env)
        with tempfile.TemporaryDirectory() as d:
            mpath = Path(d) / "m.json"
            mpath.write_text(json.dumps({"keys": {}}))
            with self.assertRaisesRegex(ValueError, "plan_changed"):
                orph.apply(str(mpath), "0000", self.env)
            with self.assertRaisesRegex(ValueError, "backup_missing"):
                orph.apply(str(mpath), plan["plan_id"], self.env)


if __name__ == "__main__":
    unittest.main()
