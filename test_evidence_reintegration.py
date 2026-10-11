"""Offline tests: verifiable, idempotent, reversible evidence reintegration (synthetic)."""
import copy
import json
import time
import unittest
from unittest.mock import patch

import cloud_mcp
from commercial_evidence_store import encode_external_store
from evidence_reintegration import apply_plan, build_plan, revert_batch

NOW = time.time()


def rows(ids, *, age_days=1, eligible_every=4):
    return [{"evidence_id": f"syn-{i}", "last_seen_epoch": NOW - age_days * 86400,
             "gate_eligible": i % eligible_every == 0} for i in ids]


def saved_env(*generations, corrupt=None):
    env = {}
    for g in generations:
        ref, chunks = encode_external_store(g, chunk_bytes=2048, store="render_env_chunks_v2")
        for i, c in enumerate(chunks):
            env[cloud_mcp._commercial_evidence_env_key(i, ref)] = ("xz64:corrupt" if corrupt and i == 0 and len(g) == corrupt else c)
    return env


KEY = cloud_mcp._evidence_memory_key


class PlanTests(unittest.TestCase):
    def test_plan_selects_only_missing_within_retention(self):
        current = rows(range(172))
        orphan = rows(range(150)) + rows(range(500, 552)) + rows(range(900, 905), age_days=30)
        plan = build_plan(saved_env(orphan, current), current, KEY, now=NOW)
        self.assertEqual(plan["candidates"], 52)
        self.assertEqual(plan["skipped_expired_rows"], 5)
        self.assertEqual(plan["intact_generations"], 2)
        self.assertEqual(len(plan["source_generations"]), 1)
        self.assertNotIn("syn-", json.dumps({k: v for k, v in plan.items() if k != "_rows"}))

    def test_corrupt_generation_is_ignored(self):
        current = rows(range(10))
        plan = build_plan(saved_env(rows(range(10, 30)), corrupt=20), current, KEY, now=NOW)
        self.assertEqual(plan["candidates"], 0)
        self.assertIsNone(plan["plan_id"])

    def test_apply_is_idempotent_and_revert_is_exact(self):
        current = rows(range(172))
        env = saved_env(rows(range(200)), current)
        plan = build_plan(env, current, KEY, now=NOW)
        merged, entry = apply_plan(plan, current, now=NOW)
        self.assertEqual(len(merged), 200)
        self.assertEqual(entry["rows"], 28)
        again = build_plan(env, merged, KEY, now=NOW)
        self.assertEqual(again["candidates"], 0)  # nothing left: re-apply is a no-op
        reverted, rentry = revert_batch(merged, plan["plan_id"], now=NOW)
        self.assertEqual(reverted, current)
        self.assertEqual(rentry["rows"], 28)


class _Req:
    def __init__(self, body):
        self._body = body

    async def json(self):
        return self._body


class EndpointTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.state = copy.deepcopy(cloud_mcp.AUTOPILOT_STATE)
        cloud_mcp.AUTOPILOT_STATE["commercial_evidence_memory"] = rows(range(172))
        cloud_mcp.AUTOPILOT_STATE["evidence_reintegration_ledger"] = []
        env = saved_env(rows(range(203)), rows(range(172)))
        self.patch = patch.object(cloud_mcp, "fetch_saved_env", lambda *a, **k: {"ok": True, "values": env})
        self.patch.start()

    async def asyncTearDown(self):
        self.patch.stop()
        cloud_mcp.AUTOPILOT_STATE.clear()
        cloud_mcp.AUTOPILOT_STATE.update(self.state)

    async def call(self, body):
        r = await cloud_mcp.api_admin_evidence_reintegration(_Req(body))
        return r.status_code, json.loads(r.body)

    async def test_plan_apply_requires_confirmation_then_revert(self):
        code, plan = await self.call({"mode": "plan"})
        self.assertEqual((code, plan["candidates"]), (200, 31))
        code, out = await self.call({"mode": "apply", "confirm": "wrong"})
        self.assertEqual(code, 409)
        self.assertEqual(len(cloud_mcp.AUTOPILOT_STATE["commercial_evidence_memory"]), 172)
        code, out = await self.call({"mode": "apply", "confirm": plan["plan_id"]})
        self.assertEqual((code, out["rows"], out["active_count"]), (200, 31, 203))
        code, out = await self.call({"mode": "apply", "confirm": plan["plan_id"]})
        self.assertEqual(out.get("reason"), "nothing_to_reintegrate")
        code, out = await self.call({"mode": "revert", "batch": plan["plan_id"]})
        self.assertEqual((out["rows"], out["active_count"]), (31, 172))
        self.assertEqual([e["action"] for e in cloud_mcp.AUTOPILOT_STATE["evidence_reintegration_ledger"]], ["apply", "revert"])


if __name__ == "__main__":
    unittest.main()
