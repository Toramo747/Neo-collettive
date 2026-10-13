import json, tempfile, unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path
from arena_evolution import initial_state, refresh_scores
from arena_registry_world import (
    AGENTS, EXTERNAL_PER_AGENT, load_registry_snapshot, mark_controls_zero_weight,
    register_external_predictions, evaluate_external_predictions, sync_registry_micelio,
)

def write_registry(root: Path, scan_at: str, rows, *, final=True, status="FINAL", scope="FULL", classification_version=2, derived_versions=()):
    root.mkdir(parents=True,exist_ok=True)
    cats={}
    for r in rows:
        cats.setdefault(r["category"],{"count":0,"percent_of_scanned":0.0})["count"]+=1
    for v in cats.values(): v["percent_of_scanned"]=round(100*v["count"]/len(rows),2)
    (root/"latest-summary.json").write_text(json.dumps({
        "generated_at_utc":scan_at,"scanned":len(rows),"categories":cats,
        "final":final,"status":status,"scope":scope,"classification_version":classification_version,
        "sample_server_names":[r["name"] for r in rows] if scope=="SAMPLE" else []
    }),encoding="utf-8")
    (root/"latest-servers.json").write_text(json.dumps({
        "generated_at_utc":scan_at,"scope":scope,"classification_version":classification_version,
        "sample_server_names":[r["name"] for r in rows] if scope=="SAMPLE" else [],
        "servers":rows
    }),encoding="utf-8")
    for version in derived_versions:
        dcats={}; drows=[]
        for r in rows:
            cat=r.get(f"category_v{version}",r["category"])
            dcats.setdefault(cat,{"count":0,"percent_of_scanned":0.0})["count"]+=1
            drows.append({**r,"category":cat,"classification_version":version})
        for v in dcats.values(): v["percent_of_scanned"]=round(100*v["count"]/len(drows),2)
        (root/f"latest-classification-v{version}.json").write_text(json.dumps({"classification_version":version,"scanned":len(drows),"categories":dcats,"servers":drows}),encoding="utf-8")

class RegistryWorldTests(unittest.TestCase):
    def rows(self):
        cats=["OK","OK","OK_WITH_ISSUES","AUTH_REQUIRED","UNREACHABLE","SERVER_ERROR","INTERMITTENT","NOT_MCP","OK","OK","OK","UNREACHABLE"]
        return [{"name":f"srv-{i:02d}","category":c,"version":"1","final":True} for i,c in enumerate(cats)]

    def test_no_dataset_registers_nothing_and_launches_no_scan(self):
        with tempfile.TemporaryDirectory() as td:
            s=initial_state()
            n=register_external_predictions(s,Path(td)/"registry",cycle_id="1")
            self.assertEqual(n,0)
            self.assertEqual(s["external_prediction_status"]["status"],"BLOCKED_NO_REGISTRY_DATA")
            self.assertTrue("no extra scan launched" in s["external_prediction_status"]["reason"])

    def test_first_pass_dataset_is_not_used_by_arena(self):
        with tempfile.TemporaryDirectory() as td:
            reg=Path(td)/"registry"
            write_registry(reg,"2026-09-27T04:00:00+00:00",self.rows(),final=False,status="FIRST_PASS")
            self.assertIsNone(load_registry_snapshot(reg))
            s=initial_state()
            n=register_external_predictions(s,reg,cycle_id="1")
            self.assertEqual(n,0)

    def test_final_sample_is_accepted_and_limited_to_sample_rows(self):
        with tempfile.TemporaryDirectory() as td:
            reg=Path(td)/"registry"; rows=self.rows()[:6]
            write_registry(reg,"2026-09-27T04:00:00+00:00",rows,scope="SAMPLE")
            snap=load_registry_snapshot(reg)
            self.assertIsNotNone(snap)
            self.assertEqual(snap["scope"],"SAMPLE")
            self.assertEqual({r["name"] for r in snap["servers"]},{r["name"] for r in rows})
            self.assertTrue(snap["sample_fingerprint"])

    def test_sample_prediction_waits_for_same_sample(self):
        with tempfile.TemporaryDirectory() as td:
            reg=Path(td)/"registry"; rows=self.rows()[:8]
            write_registry(reg,"2026-09-01T00:00:00+00:00",rows,scope="SAMPLE")
            s=initial_state(); register_external_predictions(s,reg,cycle_id="1")
            p=next(x for x in s["predictions"] if x.get("prediction_scope")=="external_registry")
            later=list(rows)
            later[-1]={"name":"different-server","category":"OK","version":"1","final":True}
            write_registry(reg,"2026-09-20T00:00:00+00:00",later,scope="SAMPLE")
            evaluate_external_predictions(s,reg,at=datetime(2026,9,20,tzinfo=timezone.utc))
            self.assertEqual(p["status"],"AWAITING_MATCHING_SAMPLE")

    def test_each_agent_gets_ten_external_predictions(self):
        with tempfile.TemporaryDirectory() as td:
            reg=Path(td)/"registry"; write_registry(reg,"2026-09-27T04:00:00+00:00",self.rows())
            s=initial_state()
            n=register_external_predictions(s,reg,cycle_id="1")
            self.assertEqual(n,len(AGENTS)*EXTERNAL_PER_AGENT)
            ext=[p for p in s["predictions"] if p.get("prediction_scope")=="external_registry"]
            for agent in AGENTS:
                self.assertEqual(sum(1 for p in ext if p["agent"]==agent),10)
            self.assertTrue(all(p["score_weight"]==1.0 and 0.0<=p["probability"]<=1.0 for p in ext))

    def test_controls_have_zero_weight(self):
        s={"predictions":[{"prediction_id":"control","status":"EVALUATED","calibration_score":1.0,"variant_id":"scout-evidence"}]}
        mark_controls_zero_weight(s)
        self.assertEqual(s["predictions"][0]["score_weight"],0.0)
        self.assertEqual(s["predictions"][0]["prediction_scope"],"system_control")

    def test_external_prediction_evaluates_only_on_later_scan(self):
        with tempfile.TemporaryDirectory() as td:
            reg=Path(td)/"registry"; rows=self.rows()
            write_registry(reg,"2026-09-01T00:00:00+00:00",rows)
            s=initial_state(); register_external_predictions(s,reg,cycle_id="1")
            p=next(x for x in s["predictions"] if x.get("prediction_scope")=="external_registry")
            future=datetime(2026,9,20,tzinfo=timezone.utc)
            evaluate_external_predictions(s,reg,at=future)
            self.assertIn(p["status"],("PENDING","AWAITING_REGISTRY_SCAN"))
            write_registry(reg,"2026-09-20T00:00:00+00:00",rows)
            n=evaluate_external_predictions(s,reg,at=future)
            self.assertGreater(n,0)
            self.assertEqual(p["status"],"EVALUATED")

    def test_provisional_registry_observation_is_not_active_fact(self):
        with tempfile.TemporaryDirectory() as td:
            reg=Path(td)/"registry"
            rows=self.rows()
            rows[0]["final"]=False
            write_registry(reg,"2026-09-01T00:00:00+00:00",rows)
            m={"beliefs":[]}; m,n=sync_registry_micelio(m,reg)
            self.assertFalse(any(b.get("server_name")=="srv-00" and b.get("status")=="ACTIVE" for b in m["beliefs"]))

    def test_registry_micelio_fact_and_change_quarantine(self):
        with tempfile.TemporaryDirectory() as td:
            reg=Path(td)/"registry"; rows=self.rows()
            write_registry(reg,"2026-09-01T00:00:00+00:00",rows)
            m={"beliefs":[]}; m,n=sync_registry_micelio(m,reg)
            self.assertGreater(n,0)
            old=next(b for b in m["beliefs"] if b.get("server_name")=="srv-00")
            self.assertEqual(old["status"],"ACTIVE")
            self.assertEqual(old["evidence"][0]["category"],"OK")
            rows[0]["category"]="UNREACHABLE"
            write_registry(reg,"2026-09-15T00:00:00+00:00",rows)
            m,n=sync_registry_micelio(m,reg)
            self.assertEqual(old["status"],"QUARANTINE")
            newer=[b for b in m["beliefs"] if b.get("server_name")=="srv-00" and b.get("status")=="ACTIVE"]
            self.assertEqual(len(newer),1)
            self.assertEqual(newer[0]["registry_category"],"UNREACHABLE")

    def test_prediction_classification_version_mismatch_blocks_evaluation(self):
        with tempfile.TemporaryDirectory() as td:
            reg=Path(td)/"registry"; rows=self.rows()
            write_registry(reg,"2026-09-01T00:00:00+00:00",rows,classification_version=2)
            s=initial_state(); register_external_predictions(s,reg,cycle_id="1")
            p=next(x for x in s["predictions"] if x.get("prediction_scope")=="external_registry")
            self.assertEqual(p["classification_version"],2)
            p["classification_version"]=1
            p["due_at_utc"]="2026-09-02T00:00:00+00:00"
            write_registry(reg,"2026-09-20T00:00:00+00:00",rows,classification_version=2)
            n=evaluate_external_predictions(s,reg,at=datetime(2026,9,20,tzinfo=timezone.utc))
            self.assertEqual(n,39)
            self.assertEqual(p["status"],"AWAITING_MATCHING_CLASSIFICATION")
            self.assertIsNone(p.get("evaluated_at_utc"))

    def test_new_predictions_use_v2_derived_view_on_legacy_final(self):
        with tempfile.TemporaryDirectory() as td:
            reg=Path(td)/"registry"; rows=self.rows()
            write_registry(reg,"2026-09-01T00:00:00+00:00",rows,classification_version=1,derived_versions=(2,))
            s=initial_state(); register_external_predictions(s,reg,cycle_id="1")
            ext=[x for x in s["predictions"] if x.get("prediction_scope")=="external_registry"]
            self.assertTrue(ext)
            self.assertTrue(all(x.get("classification_version")==2 for x in ext))


    def test_future_registry_scan_exposes_both_classification_versions(self):
        with tempfile.TemporaryDirectory() as td:
            reg=Path(td)/"registry"; rows=self.rows()
            write_registry(reg,"2026-10-04T20:00:00+00:00",rows,classification_version=2,derived_versions=(1,))
            v1=load_registry_snapshot(reg,1)
            v2=load_registry_snapshot(reg,2)
            self.assertIsNotNone(v1)
            self.assertIsNotNone(v2)
            self.assertEqual(v1["classification_version"],1)
            self.assertEqual(v2["classification_version"],2)

    def test_v1_prediction_evaluates_against_v1_view_on_future_scan(self):
        with tempfile.TemporaryDirectory() as td:
            reg=Path(td)/"registry"; rows=self.rows()
            write_registry(reg,"2026-09-27T19:33:09+00:00",rows,classification_version=1,derived_versions=(2,))
            s=initial_state()
            register_external_predictions(s,reg,cycle_id="1")
            p=next(x for x in s["predictions"] if x.get("prediction_scope")=="external_registry")
            p["classification_version"]=1
            p["registry_base_scan_at_utc"]="2026-09-27T19:33:09+00:00"
            p["due_at_utc"]="2026-10-04T19:33:09+00:00"
            p["status"]="PENDING"
            write_registry(reg,"2026-10-04T20:00:00+00:00",rows,classification_version=2,derived_versions=(1,))
            n=evaluate_external_predictions(s,reg,at=datetime(2026,10,4,20,1,tzinfo=timezone.utc))
            self.assertGreaterEqual(n,1)
            self.assertEqual(p["status"],"EVALUATED")
            self.assertEqual(p["classification_version"],1)
            self.assertTrue(s["registry_classification_compatibility"]["retain_v1_view"])

if __name__=="__main__": unittest.main()
