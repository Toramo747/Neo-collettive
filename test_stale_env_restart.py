"""Offline proof that a restart with a stale process env no longer loses evidence.

Render applies env vars written through the API only on the next deploy, so a
plain restart boots with the deploy-time NEO_STATE_JSON and evidence chunks.
These tests reproduce that situation with synthetic data: the *saved* env (what
the Render API returns) holds a newer 200-row generation, the *process* env
holds the deploy-time 145-row generation.
"""
import copy
import json
import os
import tempfile
import time
import unittest
from unittest.mock import patch

import httpx

import cloud_mcp
from commercial_evidence_store import encode_external_store
from render_saved_env import BootEnv, fetch_saved_env, generation_inventory, load_boot_env
from state_codec import decode_checkpoint, encode_checkpoint
from state_generation_guard import check_write_allowed, next_generation


def rows(n, start=0):
    base = int(time.time()) - 3600
    return [
        {"evidence_id": f"syn-{i}", "gate_eligible": i % 5 == 0,
         "last_seen_epoch": base + i, "first_seen_epoch": base + i}
        for i in range(start, start + n)
    ]


def build_env(evidence_rows, cycles, generation, previous_ref=None):
    ref, chunks = encode_external_store(
        evidence_rows, chunk_bytes=4096, store="render_env_chunks_v2",
        previous_generation=previous_ref,
    )
    env = {cloud_mcp._commercial_evidence_env_key(i, ref): c for i, c in enumerate(chunks)}
    payload = {
        "runtime_profile": dict(cloud_mcp.RUNTIME_IDENTITY),
        "cycles_completed": cycles,
        "state_saved_at_utc": "2026-10-10T05:14:00+00:00",
        "commercial_evidence_memory": ref,
        "state_generation": generation,
    }
    value, _, _ = encode_checkpoint(payload, cloud_mcp.STATE_ENV_MAX_BYTES)
    env[cloud_mcp.STATE_ENV_KEY] = value
    return env, ref


class _Isolated:
    """Run cloud_mcp._restore_state with no files, no network, fresh globals."""

    def __init__(self, boot_env):
        self.boot_env = boot_env

    def __enter__(self):
        self.saved_state = copy.deepcopy(cloud_mcp.AUTOPILOT_STATE)
        self.saved_boot = cloud_mcp._BOOT_ENV
        self.tmp = tempfile.TemporaryDirectory()
        self.cwd = os.getcwd()
        os.chdir(self.tmp.name)
        self.patches = [
            patch.object(cloud_mcp, "STATE_SNAPSHOT_PATH", os.path.join(self.tmp.name, "none.json")),
            patch.object(cloud_mcp, "_load_cycle_floor", lambda: (None, {"source": None})),
        ]
        for p in self.patches:
            p.start()
        cloud_mcp.AUTOPILOT_STATE["commercial_evidence_memory"] = []
        cloud_mcp.AUTOPILOT_STATE["cycles_completed"] = 0
        cloud_mcp.AUTOPILOT_STATE.pop("commercial_evidence_store_reference", None)
        cloud_mcp._BOOT_ENV = self.boot_env
        return self

    def __exit__(self, *exc):
        for p in self.patches:
            p.stop()
        os.chdir(self.cwd)
        self.tmp.cleanup()
        cloud_mcp._BOOT_ENV = self.saved_boot
        cloud_mcp.AUTOPILOT_STATE.clear()
        cloud_mcp.AUTOPILOT_STATE.update(self.saved_state)
        return False


def restore(boot_env):
    with _Isolated(boot_env):
        source = cloud_mcp._restore_state()
        memory = list(cloud_mcp.AUTOPILOT_STATE.get("commercial_evidence_memory") or [])
        return source, memory, cloud_mcp.AUTOPILOT_STATE.get("state_generation"), dict(cloud_mcp.AUTOPILOT_STATE.get("boot_env") or {})


class StaleEnvRestartTests(unittest.TestCase):
    def setUp(self):
        self.deploy_rows = rows(145)
        self.deploy_env, self.deploy_ref = build_env(self.deploy_rows, 2956, 10)
        self.saved_rows = rows(200)
        saved_env, self.saved_ref = build_env(self.saved_rows, 3309, 364, previous_ref=self.deploy_ref)
        # Render-saved env: the newer generation; the deploy-time chunks were
        # cleaned up through the API, but survive in the stale process env.
        self.saved_env = saved_env

    def test_without_fix_stale_process_env_restores_old_generation(self):
        # Reproduces the 10 Oct incident: process env only (old behaviour).
        stale = BootEnv(source="process_env_fallback", environ=self.deploy_env.get)
        _, memory, generation, status = restore(stale)
        self.assertEqual(len(memory), 145)
        self.assertEqual(generation, 10)
        self.assertEqual(status["boot_env_source"], "process_env_fallback")

    def test_with_fix_saved_env_restores_newest_generation(self):
        boot = BootEnv(self.saved_env, source="render_api_saved", environ=self.deploy_env.get)
        _, memory, generation, status = restore(boot)
        self.assertEqual(len(memory), 200)
        self.assertEqual({r["evidence_id"] for r in memory}, {r["evidence_id"] for r in self.saved_rows})
        self.assertEqual(generation, 364)
        self.assertEqual(status["boot_env_source"], "render_api_saved")
        self.assertGreaterEqual(status["stale_process_values_detected"], 1)

    def test_deleted_saved_key_does_not_resurrect_from_process_env(self):
        boot = BootEnv(self.saved_env, source="render_api_saved", environ=self.deploy_env.get)
        stale_key = cloud_mcp._commercial_evidence_env_key(0, self.deploy_ref)
        self.assertIsNotNone(self.deploy_env.get(stale_key))
        self.assertIsNone(boot.get(stale_key))

    def test_multiple_consecutive_restarts_never_lose_identity(self):
        env = dict(self.saved_env)
        current_rows = list(self.saved_rows)
        generation = 364
        process_env = dict(self.deploy_env)  # never refreshed: no deploy between restarts
        previous_ref = self.saved_ref
        for restart in range(5):
            boot = BootEnv(env, source="render_api_saved", environ=process_env.get)
            _, memory, loaded_gen, _ = restore(boot)
            self.assertEqual({r["evidence_id"] for r in memory}, {r["evidence_id"] for r in current_rows}, restart)
            self.assertEqual(loaded_gen, generation)
            # Simulated checkpoint after the restart: 10 new rows, new generation.
            current_rows = current_rows + rows(10, start=1000 + restart * 10)
            generation = next_generation(loaded_gen)
            env, previous_ref = build_env(current_rows, 3400 + restart, generation, previous_ref=previous_ref)
        self.assertEqual(len(current_rows), 250)


class GenerationGuardTests(unittest.TestCase):
    def _saved(self, generation, writer=None):
        payload = {"state_generation": generation}
        if writer:
            payload["state_writer_id"] = writer
        return encode_checkpoint(payload, 100000)[0]

    def test_blocks_write_when_saved_generation_is_newer(self):
        out = check_write_allowed(10, self._saved(364), decode_checkpoint, "me")
        self.assertFalse(out["allowed"])
        self.assertEqual(out["status"], "stale_generation_write_blocked")

    def test_allows_normal_successor(self):
        self.assertTrue(check_write_allowed(364, self._saved(364), decode_checkpoint, "me")["allowed"])

    def test_adopts_own_write_with_lost_response(self):
        out = check_write_allowed(364, self._saved(365, "me"), decode_checkpoint, "me")
        self.assertTrue(out["allowed"])
        self.assertEqual(out["loaded_generation"], 365)

    def test_other_instance_newer_write_is_blocked(self):
        self.assertFalse(check_write_allowed(364, self._saved(365, "other"), decode_checkpoint, "me")["allowed"])

    def test_legacy_and_corrupt_saved_do_not_block(self):
        self.assertTrue(check_write_allowed(0, encode_checkpoint({"x": 1}, 100000)[0], decode_checkpoint)["allowed"])
        self.assertEqual(check_write_allowed(5, "garbage", decode_checkpoint)["status"], "saved_undecodable")
        self.assertEqual(check_write_allowed(5, None, decode_checkpoint)["status"], "saved_unreadable")


class _GuardClient:
    saved = None
    puts = []

    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def get(self, url, headers=None):
        return httpx.Response(200, json={"key": "NEO_STATE_JSON", "value": type(self).saved})

    async def put(self, url, headers=None, json=None):
        type(self).puts.append(url)
        return httpx.Response(200, json={"value": (json or {}).get("value")})

    async def delete(self, *a, **k):
        return httpx.Response(204)


class CheckpointGuardIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_checkpoint_refuses_to_overwrite_newer_saved_state(self):
        saved_state = copy.deepcopy(cloud_mcp.AUTOPILOT_STATE)
        old = (cloud_mcp.RENDER_API_KEY, cloud_mcp.RENDER_SERVICE_ID)
        try:
            cloud_mcp.RENDER_API_KEY = "synthetic"
            cloud_mcp.RENDER_SERVICE_ID = "synthetic"
            cloud_mcp.AUTOPILOT_STATE["state_generation"] = 10
            _GuardClient.saved = encode_checkpoint({"state_generation": 364, "state_writer_id": "other"}, 100000)[0]
            _GuardClient.puts = []
            with patch.object(cloud_mcp.httpx, "AsyncClient", _GuardClient):
                result = await cloud_mcp._checkpoint_state_to_render()
            self.assertFalse(result["ok"])
            self.assertEqual(result["reason"], "stale_generation_write_blocked")
            self.assertEqual(_GuardClient.puts, [])  # nothing written, not even chunks
            self.assertEqual(cloud_mcp.AUTOPILOT_STATE["evidence_store_status"]["status"], "continuity_blocked")
        finally:
            cloud_mcp.RENDER_API_KEY, cloud_mcp.RENDER_SERVICE_ID = old
            cloud_mcp.AUTOPILOT_STATE.clear()
            cloud_mcp.AUTOPILOT_STATE.update(saved_state)

    async def test_checkpoint_writes_incremented_generation(self):
        saved_state = copy.deepcopy(cloud_mcp.AUTOPILOT_STATE)
        old = (cloud_mcp.RENDER_API_KEY, cloud_mcp.RENDER_SERVICE_ID)
        try:
            cloud_mcp.RENDER_API_KEY = "synthetic"
            cloud_mcp.RENDER_SERVICE_ID = "synthetic"
            cloud_mcp.AUTOPILOT_STATE["state_generation"] = 364
            _GuardClient.saved = encode_checkpoint({"state_generation": 364}, 100000)[0]
            _GuardClient.puts = []
            with patch.object(cloud_mcp.httpx, "AsyncClient", _GuardClient):
                result = await cloud_mcp._checkpoint_state_to_render()
            self.assertTrue(result["ok"], result)
            self.assertEqual(result["state_generation"], 365)
            self.assertEqual(cloud_mcp.AUTOPILOT_STATE["state_generation"], 365)
        finally:
            cloud_mcp.RENDER_API_KEY, cloud_mcp.RENDER_SERVICE_ID = old
            cloud_mcp.AUTOPILOT_STATE.clear()
            cloud_mcp.AUTOPILOT_STATE.update(saved_state)


class SavedEnvFetchTests(unittest.TestCase):
    def _transport(self, pages, status=200):
        calls = {"n": 0}

        def handler(request):
            calls["n"] += 1
            if status != 200:
                return httpx.Response(status)
            cursor = request.url.params.get("cursor")
            return httpx.Response(200, json=pages.get(cursor, []))
        return httpx.MockTransport(handler), calls

    def test_paginates_and_keeps_only_persisted_keys(self):
        first = [{"envVar": {"key": f"NEO_EVIDENCE_abcdefabcdef_{i}", "value": "v"}, "cursor": f"c{i}"} for i in range(99)]
        first.append({"envVar": {"key": "RENDER_API_KEY", "value": "secret"}, "cursor": "c99"})
        second = [{"envVar": {"key": "NEO_STATE_JSON", "value": "s"}, "cursor": "end"}]
        transport, calls = self._transport({None: first, "c99": second})
        out = fetch_saved_env("https://api.test/v1", "srv", "k", transport=transport)
        self.assertTrue(out["ok"])
        self.assertEqual(calls["n"], 2)
        self.assertNotIn("RENDER_API_KEY", out["values"])
        self.assertEqual(len(out["values"]), 100)

    def test_api_failure_falls_back_to_process_env(self):
        transport, _ = self._transport({}, status=503)
        boot = load_boot_env("https://api.test/v1", "srv", "k", transport=transport,
                             environ={"NEO_STATE_JSON": "process"}.get)
        self.assertEqual(boot.source, "process_env_fallback")
        self.assertEqual(boot.status()["reason"], "http_503")
        self.assertEqual(boot.get("NEO_STATE_JSON"), "process")

    def test_not_configured_makes_no_request(self):
        boot = load_boot_env(None, None, None, environ={}.get)
        self.assertEqual(boot.status()["reason"], "render_api_not_configured")

    def test_inventory_counts_orphans_without_values(self):
        keys = ["NEO_EVIDENCE_aaaaaaaaaaaa_0", "NEO_EVIDENCE_aaaaaaaaaaaa_1",
                "NEO_EVIDENCE_bbbbbbbbbbbb_0", "NEO_EVIDENCE_ARCHIVE_cccccccccccc_0",
                "NEO_CHALLENGE_TRACK_dddddddddddd_0", "NEO_COMMERCIAL_EVIDENCE_0"]
        inv = generation_inventory(keys, ["aaaaaaaaaaaa", "cccccccccccc"])
        self.assertEqual(inv["families"]["NEO_EVIDENCE_"]["orphan_generations"], 1)
        self.assertEqual(inv["families"]["NEO_EVIDENCE_ARCHIVE_"]["orphan_generations"], 0)
        self.assertEqual(inv["families"]["NEO_CHALLENGE_TRACK_"]["orphan_generations"], 1)
        self.assertEqual(inv["legacy_v1_chunks"], 1)
        self.assertEqual(sorted(inv["orphan_generation_ids"]), ["bbbbbbbbbbbb", "dddddddddddd"])


if __name__ == "__main__":
    unittest.main()
