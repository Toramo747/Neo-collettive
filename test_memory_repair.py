import ast
import json
import os
from pathlib import Path
import time
import unittest
from copy import deepcopy
from unittest.mock import patch

import cloud_mcp
from commercial_evidence_store import decode_external_store, encode_external_store
from evidence_integrity import migrate_evidence_memory
from evidence_memory_guard import repair_evidence_timestamps, replace_evidence_memory_rows
from public_snapshot import sanitize_public_autopilot


class MemoryRepairTests(unittest.TestCase):
    def _rows(self,count=100,quarantined=0,now=1_800_000_000.0):
        out=[]
        for i in range(count):
            out.append({
                "evidence_id":f"ev-{i}",
                "url":f"https://example.invalid/{i}",
                "family":"workflow_automation",
                "problem_key":"workflow_automation:ops:manual_reporting",
                "schema_v":3,
                "tagger_v":3,
                "migration_v":3,
                "gate_eligible":i>=quarantined,
                "quarantine_reason":"legacy_unverified_tagger_v1" if i<quarantined else None,
                "signal_types":["PAIN"],
                "first_seen_epoch":now-1000-i,
                "last_seen_epoch":now-100-i,
            })
        return out

    def test_missing_timestamp_reproduction_repairs_instead_of_dropping(self):
        now=1_800_000_000.0
        rows=self._rows(94,60,now)
        rows[0].pop("last_seen_epoch")
        rows[1]["last_seen_epoch"]=0
        legacy_retained=[
            row for row in rows
            if float(row.get("last_seen_epoch") or 0)
            and now-float(row.get("last_seen_epoch") or 0)<=21*86400
        ]
        self.assertEqual(len(legacy_retained),92)
        repaired,count=repair_evidence_timestamps(rows,checkpoint_epoch=now-60,now_epoch=now)
        self.assertEqual(len(repaired),94)
        self.assertEqual(count,2)
        self.assertTrue(all(float(row.get("last_seen_epoch") or 0)>0 for row in repaired))

    def test_100_rows_60_quarantined_survive_migration_and_revalidation_shape(self):
        rows=self._rows(100,60)
        migrated,meta=migrate_evidence_memory(rows)
        self.assertEqual(len(migrated),100)
        self.assertEqual(meta["rows"],100)
        replaced,telemetry=replace_evidence_memory_rows(rows,migrated,"migration",now_epoch=1_800_000_000.0)
        self.assertEqual(len(replaced),100)
        self.assertEqual(telemetry["evidence_regression_blocked"],0)

    def test_subset_replacement_is_blocked_and_old_is_kept(self):
        rows=self._rows(100,60)
        subset=rows[:40]
        replaced,telemetry=replace_evidence_memory_rows(
            rows,subset,"quarantine_revalidation",now_epoch=1_800_000_000.0
        )
        self.assertEqual(len(replaced),100)
        self.assertEqual(telemetry["evidence_regression_blocked"],1)

    def test_missing_timestamps_are_repaired_not_discarded(self):
        rows=self._rows(3,2)
        rows[0].pop("last_seen_epoch")
        rows[0]["first_seen_epoch"]=1_799_999_000.0
        rows[1].pop("last_seen_epoch")
        rows[1].pop("first_seen_epoch")
        fixed,count=repair_evidence_timestamps(
            rows,checkpoint_epoch=1_799_999_500.0,now_epoch=1_800_000_000.0
        )
        self.assertEqual(len(fixed),3)
        self.assertGreaterEqual(count,2)
        self.assertEqual(fixed[0]["last_seen_epoch"],fixed[0]["first_seen_epoch"])
        self.assertEqual(fixed[1]["last_seen_epoch"],1_799_999_500.0)
        self.assertTrue(fixed[0]["timestamp_repaired"])
        self.assertTrue(fixed[1]["timestamp_repaired"])

    def test_external_store_roundtrip_preserves_seen_epochs_exactly(self):
        rows=self._rows(25,10)
        ref,chunks=encode_external_store(rows,chunk_bytes=1024,store="render_env_chunks_v2")
        decoded=decode_external_store(ref,chunks)
        self.assertIsNotNone(decoded)
        self.assertEqual(
            [(r["first_seen_epoch"],r["last_seen_epoch"]) for r in decoded],
            [(r["first_seen_epoch"],r["last_seen_epoch"]) for r in rows],
        )

    def test_unchanged_generation_never_points_to_itself(self):
        rows=self._rows(8,3)
        first,_=encode_external_store(rows,chunk_bytes=1024,store="render_env_chunks_v2")
        second,_=encode_external_store(
            rows,chunk_bytes=1024,store="render_env_chunks_v2",previous_generation=first
        )
        self.assertEqual(first["generation"],second["generation"])
        self.assertNotIn("previous_generation",second)

    def test_orphan_generation_recovers_when_checkpoint_reference_is_missing(self):
        rows=self._rows(92,60)
        ref,chunks=encode_external_store(rows,chunk_bytes=60000,store="render_env_chunks_v2")
        stale={
            "schema_v":2,"store_mode":"external","store":"render_env_chunks_v2",
            "sha256":"3"*64,"generation":"3"*12,"evidence_count":94,"chunk_count":1,"raw_bytes":1,
        }
        env={
            cloud_mcp._commercial_evidence_env_key(i,ref):chunk
            for i,chunk in enumerate(chunks)
        }
        with patch.dict(os.environ,env,clear=False):
            hydrated,meta=cloud_mcp._hydrate_external_commercial_evidence({
                "commercial_evidence_memory":stale,
                "commercial_evidence_store_reference":stale,
            })
        self.assertEqual(meta["status"],"recovered_orphan_generation")
        self.assertEqual(len(hydrated["commercial_evidence_memory"]),92)
        self.assertEqual(hydrated["evidence_memory_recovery"]["recovered_rows"],92)

    def test_mid_cycle_subset_failure_keeps_previous_memory(self):
        old=deepcopy(cloud_mcp.AUTOPILOT_STATE)
        rows=self._rows(12,6)
        try:
            cloud_mcp.AUTOPILOT_STATE["commercial_evidence_memory"]=rows
            result=cloud_mcp.replace_evidence_memory(rows,rows[:2],"synthetic_mid_cycle")
            self.assertEqual(len(result),12)
            self.assertEqual(
                cloud_mcp.AUTOPILOT_STATE["evidence_memory_telemetry"]["evidence_regression_blocked"],1
            )
        finally:
            cloud_mcp.AUTOPILOT_STATE.clear()
            cloud_mcp.AUTOPILOT_STATE.update(old)

    def test_only_replace_function_assigns_commercial_memory(self):
        source=Path("cloud_mcp.py").read_text(encoding="utf-8")
        tree=ast.parse(source)
        offenders=[]
        allowed=[]
        class Visitor(ast.NodeVisitor):
            def __init__(self):
                self.stack=[]
            def visit_FunctionDef(self,node):
                self.stack.append(node.name)
                self.generic_visit(node)
                self.stack.pop()
            def visit_AsyncFunctionDef(self,node):
                self.stack.append(node.name)
                self.generic_visit(node)
                self.stack.pop()
            def visit_Assign(self,node):
                for target in node.targets:
                    if isinstance(target,ast.Subscript):
                        value=target.value
                        sl=target.slice
                        if (
                            isinstance(value,ast.Name) and value.id=="AUTOPILOT_STATE"
                            and isinstance(sl,ast.Constant) and sl.value=="commercial_evidence_memory"
                        ):
                            name=self.stack[-1] if self.stack else "<module>"
                            (allowed if name=="replace_evidence_memory" else offenders).append(name)
                self.generic_visit(node)
        Visitor().visit(tree)
        self.assertEqual(offenders,[])
        self.assertEqual(allowed,["replace_evidence_memory"])

    def test_backup_manifest_rows_seed_recovery_telemetry_only(self):
        manifest=json.dumps({"checkpoint":{"rows":94}})
        with patch.dict(os.environ,{"BACKUP_20261007T023646Z_MANIFEST":manifest},clear=False):
            self.assertTrue(cloud_mcp._backup_manifest_present())
            self.assertEqual(cloud_mcp._backup_manifest_recovery_rows(),94)

    def test_state_payload_persists_memory_telemetry(self):
        old=deepcopy(cloud_mcp.AUTOPILOT_STATE)
        try:
            cloud_mcp.AUTOPILOT_STATE["evidence_memory_telemetry"]={
                "evidence_in":94,"evidence_out":94,"recovered_rows":94,"backup_ok":True,
            }
            payload=cloud_mcp._state_payload()
            self.assertEqual(payload["evidence_memory_telemetry"]["recovered_rows"],94)
            self.assertTrue(payload["evidence_memory_telemetry"]["backup_ok"])
        finally:
            cloud_mcp.AUTOPILOT_STATE.clear()
            cloud_mcp.AUTOPILOT_STATE.update(old)

    def test_public_memory_telemetry_is_aggregate_only(self):
        out=sanitize_public_autopilot({
            "evidence_memory_telemetry":{
                "evidence_in":92,"evidence_out":92,"dropped_retention":0,
                "archived":0,"merged_duplicate":0,"timestamp_repaired":0,
                "evidence_regression_blocked":0,"recovered_rows":92,"backup_ok":True,
                "reason":"must-not-be-public",
            },
            "evidence_store_status":{"status":"recovered_orphan_generation","active_count":92},
        })
        self.assertEqual(out["evidence_memory"]["recovered_rows"],92)
        self.assertTrue(out["evidence_memory"]["backup_ok"])
        self.assertNotIn("reason",out["evidence_memory"])


if __name__=="__main__":
    unittest.main()
