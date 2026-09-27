import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

import registry_health_scan as rhs
from registry_health_scan import _sample_budget_seconds, _sample_order, _select_sample_candidates
from registry_health import (
    classify_verification,
    classify_compact_probe,
    final_category,
    is_opted_out,
    normalize_registry_rows,
    render_report,
    render_social_draft,
)


def row(name, *, latest=True, status="active", remotes=None, packages=None, version="1.0.0"):
    return {
        "server": {
            "name": name,
            "version": version,
            "remotes": remotes or [],
            "packages": packages or [],
        },
        "_meta": {
            "io.modelcontextprotocol.registry/official": {
                "isLatest": latest,
                "status": status,
            }
        },
    }


class RegistryHealthListingTests(unittest.TestCase):
    def test_keeps_only_active_latest_and_splits_access_classes(self):
        rows = normalize_registry_rows([
            row("a/remote", remotes=[{"type":"streamable-http","url":"https://a.example/mcp"}]),
            row("b/pkg", packages=[{"registryType":"npm","identifier":"b"}]),
            row("c/old", latest=False, remotes=[{"type":"streamable-http","url":"https://c.example/mcp"}]),
            row("d/deprecated", status="deprecated", remotes=[{"type":"streamable-http","url":"https://d.example/mcp"}]),
            row("e/sse", remotes=[{"type":"sse","url":"https://e.example/sse"}]),
            row("f/meta"),
            row("g/sse-plus-package", remotes=[{"type":"sse","url":"https://g.example/sse"}], packages=[{"registryType":"npm","identifier":"g"}]),
        ])
        by_name={x["name"]:x for x in rows}
        self.assertEqual(set(by_name), {"a/remote","b/pkg","e/sse","f/meta","g/sse-plus-package"})
        self.assertEqual(by_name["a/remote"]["access_class"], "remote")
        self.assertEqual(by_name["b/pkg"]["access_class"], "package_only")
        self.assertEqual(by_name["e/sse"]["access_class"], "remote_unverifiable_transport")
        self.assertEqual(by_name["g/sse-plus-package"]["access_class"], "remote_unverifiable_transport")
        self.assertEqual(by_name["f/meta"]["access_class"], "metadata_only")

    def test_opt_out_matches_exact_name_or_remote(self):
        server={"name":"a/remote","remotes":[{"url":"https://a.example/mcp"}]}
        self.assertTrue(is_opted_out(server,{"a/remote"}))
        self.assertTrue(is_opted_out(server,{"https://a.example/mcp"}))
        self.assertFalse(is_opted_out(server,{"a"}))

    def test_classification_is_mutually_exclusive(self):
        auth={"checks":{"initialize":{"http_status":401,"ok":False}},"errors":["initialize_failed"]}
        server_error={"checks":{"initialize":{"http_status":503,"ok":False}},"errors":["initialize_failed"]}
        good={
            "checks":{
                "initialize":{"http_status":200,"ok":True},
                "tools_list":{"ok":True,"invalid_input_schemas":0},
                "discovery":{"present":True},
            },
            "errors":[],
        }
        issue={
            "checks":{
                "initialize":{"http_status":200,"ok":True},
                "tools_list":{"ok":True,"invalid_input_schemas":0},
                "discovery":{"present":False},
            },
            "errors":[],
        }
        dead={"checks":{},"errors":["dns_error"]}
        not_mcp={"checks":{"initialize":{"http_status":200,"ok":False}},"errors":["initialize_failed"]}
        self.assertEqual(classify_verification(auth),"AUTH_REQUIRED")
        self.assertEqual(classify_verification(server_error),"SERVER_ERROR")
        self.assertEqual(classify_verification(good),"OK")
        self.assertEqual(classify_verification(issue),"OK_WITH_ISSUES")
        self.assertEqual(classify_verification(dead),"UNREACHABLE")
        self.assertEqual(classify_verification(not_mcp),"NOT_MCP")

    def test_report_is_aggregate_only(self):
        summary={
            "servers_total":10,"remote_verifiable":6,"package_only":4,
            "remote_unverifiable_transport":0,"metadata_only":0,"opted_out":0,
            "scanned":6,
            "categories":{"OK":{"count":4},"AUTH_REQUIRED":{"count":1},"UNREACHABLE":{"count":1}},
            "protocol_versions":{"2025-11-25":4},
            "invalid_input_schemas":1,"discovery_present":3,"tls_failures":1,
            "latency_ms":{"median":120.0,"p90":400.0,"samples":5},
        }
        report=render_report(summary,"2026-09-26")
        self.assertIn("MCP Registry Health Report",report)
        self.assertIn("aggregate results only",report)
        self.assertNotIn("example.com",report)
        social=render_social_draft(summary,"2026-09-26")
        self.assertEqual(len([x for x in social.splitlines() if x.strip()]),5)


    def test_sample_report_is_explicitly_non_registry_wide(self):
        summary={
            "scope":"SAMPLE","sample_size":12,"sample_seed":4242,
            "sample_population_remote_count":300,"servers_total":500,"remote_verifiable":300,
            "package_only":100,"remote_unverifiable_transport":50,"metadata_only":50,
            "opted_out":0,"scanned":12,
            "categories":{"OK":{"count":8},"AUTH_REQUIRED":{"count":1},"UNREACHABLE":{"count":3}},
            "protocol_versions":{},"invalid_input_schemas":0,"discovery_present":5,
            "tls_failures":1,"latency_ms":{"median":100.0,"p90":200.0,"samples":10},
        }
        report=render_report(summary,"2026-09-27")
        self.assertIn("SAMPLE ONLY",report)
        self.assertIn("Sample size: **12**",report)
        self.assertIn("must not be interpreted or published as statistics for the entire MCP Registry",report)
        social=render_social_draft(summary,"2026-09-27")
        self.assertIn("Results apply only to this sample",social)
        self.assertNotIn("We measured 500 active/latest Registry entries",social)

    def test_scan_workflow_persists_dated_and_latest_datasets(self):
        workflow=Path(".github/workflows/registry-health-scan.yml").read_text(encoding="utf-8")
        self.assertIn("Assert dataset persistence contract",workflow)
        self.assertIn("git add data/registry-health",workflow)
        self.assertIn("if [ -d docs/reports ]; then git add docs/reports; fi",workflow)
        self.assertIn("git add data/arena",workflow)
        self.assertIn("Verify Registry Health data persisted on main",workflow)
        self.assertIn("data/registry-health/latest-summary.json",workflow)
        self.assertIn("data/registry-health/latest-servers.json",workflow)
        self.assertIn('re.fullmatch(r"\\d{4}-\\d{2}-\\d{2}",p.name)',workflow)
        self.assertIn('"git","ls-tree","-r","--name-only","origin/main","data/registry-health"',workflow)
        self.assertIn('REGISTRY_HEALTH_PUBLISH_CHECKPOINTS: "1"',workflow)
        self.assertIn("Commit Registry Health dataset",workflow)
        self.assertIn("if: env.REGISTRY_HEALTH_PHASE == 'second'",workflow)
        self.assertNotIn('GITHUB_RUN_ATTEMPT',workflow)

    def test_sample_mode_has_30_minute_budget_and_seeded_random_order(self):
        self.assertEqual(_sample_budget_seconds(30),1800)
        servers=[{"name":f"srv-{i:02d}"} for i in range(12)]
        a=[x["name"] for x in _sample_order(servers,424242)]
        b=[x["name"] for x in _sample_order(servers,424242)]
        self.assertEqual(a,b)
        self.assertNotEqual(a,[x["name"] for x in servers])

    def test_sample_workflow_inputs_and_checkpoint_contract(self):
        workflow=Path(".github/workflows/registry-health-scan.yml").read_text(encoding="utf-8")
        self.assertIn("mode:",workflow)
        self.assertIn("max_minutes:",workflow)
        self.assertIn('default: "30"',workflow)
        self.assertIn("--mode",workflow)
        self.assertIn("inputs.mode",workflow)
        self.assertIn('REGISTRY_HEALTH_PUBLISH_CHECKPOINTS: "1"',workflow)
        source=Path("registry_health_scan.py").read_text(encoding="utf-8")
        self.assertIn('"scope":scope',source)
        self.assertIn('"sample_seed":sample_seed',source)
        self.assertIn('"sample_server_names"',source)
        self.assertIn('stopped_reason="max_minutes_reached"',source)
        self.assertIn("CHECKPOINT_EVERY_COMPLETIONS = 20",source)

    def test_sample_hard_stop_and_checkpoint_publish_contract(self):
        source=Path("registry_health_scan.py").read_text(encoding="utf-8")
        self.assertIn("deadline=(started+budget_seconds)",source)
        self.assertIn("wait_timeout=None if deadline is None else max(0.0,deadline-_monotonic())",source)
        self.assertIn("done,pending=await asyncio.wait",source)
        self.assertIn("task.cancel()",source)
        self.assertIn('stopped_reason="max_minutes_reached"',source)
        self.assertIn("CHECKPOINT_EVERY_COMPLETIONS = 20",source)
        self.assertIn('subprocess.run(["git","push","origin","HEAD:main"])',source)

    def test_sample_deadline_closes_complete_first_pass(self):
        listing={
            "snapshot_at_utc":"2026-09-27T12:00:00+00:00",
            "servers":[
                {"name":"a","version":"1","access_class":"remote","remotes":[{"url":"https://a.example/mcp"}]},
                {"name":"b","version":"1","access_class":"remote","remotes":[{"url":"https://b.example/mcp"}]},
            ],
        }
        probe={
            "timestamp":"2026-09-27T12:00:01+00:00",
            "category":"OK_WITH_ISSUES",
            "request_counts_by_host":{"a.example":1},
            "usage_scope":"internal_registry_health",
        }
        monotonic_values=iter([0.0,0.0,0.0,0.0,60.1,60.1])
        with tempfile.TemporaryDirectory() as td, \
             patch.object(rhs,"DATA_ROOT",Path(td)/"registry-health"), \
             patch.object(rhs,"fetch_complete_registry",AsyncMock(return_value=listing)), \
             patch.object(rhs,"run_probe",AsyncMock(return_value=probe)), \
             patch.object(rhs,"read_opt_out",return_value=set()), \
             patch.object(rhs,"_publish_progress_checkpoint",return_value=None), \
             patch.object(rhs,"_sample_budget_seconds",return_value=60), \
             patch.object(rhs,"MAX_CONCURRENCY",1), \
             patch.object(rhs,"_monotonic",side_effect=lambda: next(monotonic_values)):
            outdir=asyncio.run(rhs.first_phase(mode="sample",max_minutes=1))
            state=json.loads((outdir/"scan-state.json").read_text(encoding="utf-8"))
            summary=json.loads((outdir/"summary.json").read_text(encoding="utf-8"))
            latest=json.loads((rhs.DATA_ROOT/"latest-summary.json").read_text(encoding="utf-8"))
            servers=json.loads((rhs.DATA_ROOT/"latest-servers.json").read_text(encoding="utf-8"))
            self.assertEqual(state["status"],"FIRST_PASS")
            self.assertEqual(summary["status"],"FIRST_PASS")
            self.assertEqual(summary["scope"],"SAMPLE")
            self.assertEqual(summary["stopped_reason"],"max_minutes_reached")
            self.assertEqual(latest["generated_at_utc"],summary["generated_at_utc"])
            self.assertEqual(len(servers["servers"]),1)
            self.assertEqual(servers["sample_server_names"],state["sample_server_names"])

    def test_second_phase_rejects_non_first_pass_before_time_check(self):
        with tempfile.TemporaryDirectory() as td:
            outdir=Path(td)
            (outdir/"scan-state.json").write_text(json.dumps({
                "phase":"first",
                "status":"IN_PROGRESS",
                "final":False,
                "second_probe_not_before_utc":"2000-01-01T00:00:00+00:00",
            }),encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError,"second_probe_requires_FIRST_PASS"):
                asyncio.run(rhs.second_phase(outdir))


    def test_exact_sample_can_be_replayed_for_future_arena_evaluation(self):
        servers=[{"name":f"srv-{i:02d}"} for i in range(6)]
        replay=["srv-04","srv-01","srv-05"]
        selected=_select_sample_candidates(servers,123,replay)
        self.assertEqual([x["name"] for x in selected],replay)
        with self.assertRaisesRegex(RuntimeError,"sample_replay_members_missing"):
            _select_sample_candidates(servers,123,["srv-missing"])

    def test_one_shot_sample_dispatch_is_guarded(self):
        deploy=Path(".github/workflows/neo-render-deploy.yml").read_text(encoding="utf-8")
        self.assertIn("Dispatch authorized 30-minute Registry Health SAMPLE once",deploy)
        self.assertIn("[registry-sample-once]",deploy)
        self.assertIn("Registry Health SAMPLE already dispatched for this commit",deploy)
        self.assertIn("-f mode=sample",deploy)
        self.assertIn("-f max_minutes=30",deploy)

    def test_second_probe_preserves_sample_scope_and_membership(self):
        source=Path("registry_health_scan.py").read_text(encoding="utf-8")
        self.assertIn('scope=str(state.get("scope") or SCOPE_FULL)',source)
        self.assertIn("sample_membership_changed_before_second_probe",source)
        self.assertIn('"sample_seed":state.get("sample_seed")',source)
        self.assertIn('"sample_server_names":sample_names',source)
        self.assertIn('first.get("category") in {"OK","AUTH_REQUIRED"}',source)

    def test_second_probe_disagreement_is_intermittent(self):
        self.assertEqual(final_category({"category":"SERVER_ERROR"},{"category":"OK"}),"INTERMITTENT")
        self.assertEqual(final_category({"category":"SERVER_ERROR"},{"category":"SERVER_ERROR"}),"SERVER_ERROR")
        self.assertEqual(final_category({"category":"OK"},None),"OK")


    def test_classification_v2_does_not_require_discovery(self):
        result={"checks":{"initialize":{"ok":True,"http_status":200},"tools_list":{"ok":True,"invalid_input_schemas":0},"discovery":{"present":False}},"errors":[]}
        self.assertEqual(classify_verification(result,1),"OK_WITH_ISSUES")
        self.assertEqual(classify_verification(result,2),"OK")

    def test_compact_probe_reclassification_is_non_mutating(self):
        probe={"http_status":200,"summary":{"invalid_input_schemas":0,"discovery_present":False},"checks":{"initialize":{"ok":True,"http_status":200}},"errors":[]}
        before=json.dumps(probe,sort_keys=True)
        self.assertEqual(classify_compact_probe(probe,1),"OK_WITH_ISSUES")
        self.assertEqual(classify_compact_probe(probe,2),"OK")
        self.assertEqual(json.dumps(probe,sort_keys=True),before)


if __name__ == "__main__":
    unittest.main()
