import asyncio
import unittest

import cloud_mcp
from commercial_evidence_store import encode_external_store, generation_id


def ref_for(payload):
    ref, _ = encode_external_store([payload], chunk_bytes=50, store="render_env_chunks_v2")
    return ref


class OrphanCleanup(unittest.TestCase):
    def setUp(self):
        self.deleted = []
        self.saved = {k: getattr(cloud_mcp, k) for k in ("_delete_challenge_track_generation", "_delete_evidence_generation")}

        async def del_ch(ref):
            self.deleted.append(("challenge", generation_id(ref)))

        async def del_ev(ref):
            self.deleted.append(("evidence", generation_id(ref)))

        cloud_mcp._delete_challenge_track_generation = del_ch
        cloud_mcp._delete_evidence_generation = del_ev
        self.state_backup = {k: cloud_mcp.AUTOPILOT_STATE.get(k) for k in (
            "challenge_track_store_reference", "commercial_evidence_store_reference", "commercial_evidence_archive_reference")}

    def tearDown(self):
        for k, v in self.saved.items():
            setattr(cloud_mcp, k, v)
        cloud_mcp.AUTOPILOT_STATE.update(self.state_backup)

    def test_uncommitted_new_generation_is_deleted(self):
        committed = ref_for({"a": 1})
        new = ref_for({"a": 2})
        cloud_mcp.AUTOPILOT_STATE["challenge_track_store_reference"] = committed
        asyncio.run(cloud_mcp._discard_uncommitted_generations(new, None, None))
        self.assertEqual(self.deleted, [("challenge", generation_id(new))])

    def test_generation_still_committed_is_kept(self):
        committed = ref_for({"a": 1})
        same = ref_for({"a": 1})
        cloud_mcp.AUTOPILOT_STATE["challenge_track_store_reference"] = committed
        asyncio.run(cloud_mcp._discard_uncommitted_generations(same, None, None))
        self.assertEqual(self.deleted, [])


if __name__ == "__main__":
    unittest.main()
