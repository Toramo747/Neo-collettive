# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Andrea Gava
"""Read-only bridge from Registry Health datasets into the isolated Arena."""
from __future__ import annotations
import hashlib, json, re
from collections import Counter
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

AGENTS=("Scout","Analyst","Critic","Builder-planner")
REGISTRY_SUMMARY="latest-summary.json"
REGISTRY_SERVERS="latest-servers.json"
EXTERNAL_PER_AGENT=10

def _parse(v: str):
    try: return datetime.fromisoformat(str(v).replace("Z","+00:00"))
    except Exception: return None

def _load(path: Path, default: Any):
    try: return json.loads(path.read_text(encoding="utf-8"))
    except Exception: return default

def _scan_at(summary: dict, servers: dict) -> str:
    for obj in (summary,servers):
        for key in ("generated_at_utc","snapshot_at_utc","scan_at_utc","completed_at_utc"):
            if obj.get(key): return str(obj[key])
    return ""

def load_registry_snapshot(registry_dir: str|Path="data/registry-health") -> dict|None:
    root=Path(registry_dir)
    sp=root/REGISTRY_SUMMARY; rp=root/REGISTRY_SERVERS
    if not sp.exists() or not rp.exists():
        return None
    summary=_load(sp,{})
    servers_doc=_load(rp,{})
    rows=servers_doc.get("servers") if isinstance(servers_doc,dict) else None
    if not isinstance(summary,dict) or not isinstance(rows,list):
        return None
    scan_at=_scan_at(summary,servers_doc)
    if not scan_at:
        return None
    clean=[]
    for row in rows:
        if not isinstance(row,dict): continue
        name=str(row.get("name") or "").strip()
        cat=str(row.get("category") or "").strip().upper()
        if not name or not cat: continue
        clean.append({
            "name":name,"category":cat,"version":str(row.get("version") or ""),
            "remote_url":str(row.get("remote_url") or ""),
        })
    if not clean:
        return None
    return {
        "scan_at_utc":scan_at,
        "summary":summary,
        "servers":clean,
        "source_files":[str(sp),str(rp)],
    }

def _variant_for(state: dict, agent: str) -> str:
    active=[v for v in (state.get("variants") or []) if isinstance(v,dict) and v.get("agent")==agent and v.get("status")=="ACTIVE"]
    if not active: return ""
    preferred=[v for v in active if any(k in str(v.get("strategy") or "") for k in ("evidence","falsification","independence","smallest"))]
    return str((preferred or active)[0].get("variant_id") or "")

def mark_controls_zero_weight(state: dict) -> dict:
    for pred in state.get("predictions") or []:
        if not isinstance(pred,dict): continue
        if pred.get("prediction_scope")!="external_registry":
            pred["prediction_scope"]="system_control"
            pred["score_weight"]=0.0
    return state

def _agent_probability(agent: str, category: str, kind: str) -> float:
    base={
        "OK":0.82,"OK_WITH_ISSUES":0.68,"AUTH_REQUIRED":0.72,
        "SERVER_ERROR":0.48,"NOT_MCP":0.75,"UNREACHABLE":0.38,"INTERMITTENT":0.50,
    }.get(category,0.55)
    if kind=="recover": base=1.0-base
    offsets={"Scout":0.02,"Analyst":0.0,"Critic":-0.08,"Builder-planner":0.04}
    return round(max(0.05,min(0.95,base+offsets.get(agent,0.0))),2)

def register_external_predictions(state: dict, registry_dir: str|Path="data/registry-health", *, cycle_id: str) -> int:
    snap=load_registry_snapshot(registry_dir)
    if not snap:
        state["external_prediction_status"]={
            "status":"BLOCKED_NO_REGISTRY_DATA","cycle_id":str(cycle_id),
            "required_per_agent":EXTERNAL_PER_AGENT,"registered":0,
            "reason":"Registry Health latest-summary/latest-servers not available; no extra scan launched.",
        }
        return 0
    marker=f"{snap['scan_at_utc']}|{cycle_id}"
    existing=[
        x for x in (state.get("predictions") or [])
        if isinstance(x,dict) and x.get("prediction_scope")=="external_registry" and x.get("generation_marker")==marker
    ]
    if existing:
        return len(existing)
    rows=snap["servers"]
    summary=snap["summary"]
    scanned=int(summary.get("scanned") or len(rows) or 0)
    ok_count=int(((summary.get("categories") or {}).get("OK") or {}).get("count") or sum(1 for r in rows if r["category"]=="OK"))
    ok_share=(ok_count/scanned) if scanned else 0.0
    created=_parse(snap["scan_at_utc"]) or datetime.now(timezone.utc)
    added=[]
    for ai,agent in enumerate(AGENTS):
        variant_id=_variant_for(state,agent)
        for j in range(EXTERNAL_PER_AGENT):
            if j<8:
                row=rows[(ai*8+j)%len(rows)]
                cat=row["category"]
                if cat=="UNREACHABLE":
                    due=created+timedelta(days=14)
                    verification={"kind":"registry_next_scan","test":"server_recovers","server_name":row["name"],"base_category":cat}
                    statement=f"{row['name']} in UNREACHABLE will be reachable at the first Registry Health scan on or after {due.date().isoformat()}."
                    p=_agent_probability(agent,cat,"recover")
                else:
                    due=created+timedelta(days=7)
                    verification={"kind":"registry_next_scan","test":"server_stays_category","server_name":row["name"],"expected_category":cat}
                    statement=f"{row['name']} will still be {cat} at the first Registry Health scan on or after {due.date().isoformat()}."
                    p=_agent_probability(agent,cat,"stay")
                target={"server_name":row["name"],"base_category":cat}
            else:
                due=created+timedelta(days=7)
                delta=(-0.03 if j==8 else 0.03)
                threshold=round(max(0.0,min(1.0,ok_share+delta)),4)
                verification={"kind":"registry_next_scan","test":"ok_share_gt","threshold":threshold}
                statement=f"At the first Registry Health scan on or after {due.date().isoformat()}, the OK share will be greater than {threshold:.1%}."
                p=round(0.62 if j==8 else 0.42,2)
                if agent=="Critic": p=round(max(0.05,p-0.08),2)
                target={"base_ok_share":round(ok_share,4),"threshold":threshold}
            pid=hashlib.sha256(f"{marker}|{agent}|{j}|{statement}".encode()).hexdigest()[:18]
            added.append({
                "prediction_id":"world-"+pid,"agent":agent,"variant_id":variant_id,
                "statement":statement,"probability":p,"created_at_utc":created.isoformat(),
                "due_at_utc":due.isoformat(),"status":"PENDING",
                "prediction_scope":"external_registry","score_weight":1.0,
                "generation_marker":marker,"registry_base_scan_at_utc":snap["scan_at_utc"],
                "verification":verification,"target":target,
                "evaluated_at_utc":None,"outcome":None,"calibration_score":None,"sources":[],
            })
    state.setdefault("predictions",[]).extend(added)
    counts=Counter(x["agent"] for x in added)
    state["external_prediction_status"]={
        "status":"READY","cycle_id":str(cycle_id),"registry_scan_at_utc":snap["scan_at_utc"],
        "required_per_agent":EXTERNAL_PER_AGENT,"registered":len(added),
        "by_agent":dict(counts),"no_new_scan":True,
    }
    return len(added)

def evaluate_external_predictions(state: dict, registry_dir: str|Path="data/registry-health", *, at: datetime|None=None) -> int:
    snap=load_registry_snapshot(registry_dir)
    if not snap: return 0
    scan_dt=_parse(snap["scan_at_utc"])
    if not scan_dt: return 0
    at=at or datetime.now(timezone.utc)
    by_name={r["name"]:r for r in snap["servers"]}
    summary=snap["summary"]
    scanned=int(summary.get("scanned") or len(by_name) or 0)
    ok_count=int(((summary.get("categories") or {}).get("OK") or {}).get("count") or sum(1 for r in by_name.values() if r["category"]=="OK"))
    ok_share=(ok_count/scanned) if scanned else 0.0
    evaluated=0
    for pred in state.get("predictions") or []:
        if not isinstance(pred,dict) or pred.get("prediction_scope")!="external_registry" or pred.get("status") not in {"PENDING","AWAITING_REGISTRY_SCAN"}:
            continue
        due=_parse(str(pred.get("due_at_utc") or ""))
        base=_parse(str(pred.get("registry_base_scan_at_utc") or ""))
        if not due or at<due: continue
        if not base or scan_dt<=base:
            pred["status"]="AWAITING_REGISTRY_SCAN"
            continue
        ver=pred.get("verification") or {}; test=str(ver.get("test") or "")
        outcome=False
        if test=="server_stays_category":
            row=by_name.get(str(ver.get("server_name") or ""))
            outcome=bool(row and row["category"]==str(ver.get("expected_category") or ""))
        elif test=="server_recovers":
            row=by_name.get(str(ver.get("server_name") or ""))
            outcome=bool(row and row["category"]!="UNREACHABLE")
        elif test=="ok_share_gt":
            outcome=ok_share>float(ver.get("threshold") or 0.0)
        else:
            continue
        p=max(0.0,min(1.0,float(pred.get("probability") or 0.0))); y=1.0 if outcome else 0.0
        pred["outcome"]=bool(outcome)
        pred["calibration_score"]=round(1.0-(p-y)**2,6)
        pred["evaluated_at_utc"]=at.isoformat()
        pred["evaluated_registry_scan_at_utc"]=snap["scan_at_utc"]
        pred["sources"]=list(snap["source_files"])
        pred["status"]="EVALUATED"
        evaluated+=1
    return evaluated

def sync_registry_micelio(memory: dict, registry_dir: str|Path="data/registry-health") -> tuple[dict,int]:
    snap=load_registry_snapshot(registry_dir)
    if not snap:
        memory["external_registry_status"]={"status":"BLOCKED_NO_REGISTRY_DATA","imported":0,"no_new_scan":True}
        return memory,0
    beliefs=[x for x in (memory.get("beliefs") or []) if isinstance(x,dict)]
    imported=0
    for row in snap["servers"]:
        name=row["name"]; cat=row["category"]
        current=[
            b for b in beliefs if b.get("source_scope")=="registry_health" and b.get("server_name")==name and b.get("status")=="ACTIVE"
        ]
        same=next((b for b in current if b.get("registry_category")==cat),None)
        for old in current:
            if old is same: continue
            old["status"]="QUARANTINE"
            old["confidence"]=0.45
            old.setdefault("verification_history",[]).append({
                "verified_at_utc":snap["scan_at_utc"],"ok":False,
                "reason":"registry_category_changed","observed_category":cat,
            })
        evidence={
            "kind":"registry_health","server_name":name,"category":cat,
            "scan_at_utc":snap["scan_at_utc"],"verified_read_only":True,
            "dataset":"data/registry-health/latest-servers.json",
        }
        if same:
            prev=str(((same.get("evidence") or [{}])[-1] or {}).get("scan_at_utc") or "")
            if prev!=snap["scan_at_utc"]:
                same["evidence"]=[evidence]
                same["last_verified_utc"]=snap["scan_at_utc"]
                same["confidence"]=min(1.0,float(same.get("confidence") or 0.9)+0.03)
                same.setdefault("verification_history",[]).append({"verified_at_utc":snap["scan_at_utc"],"ok":True,"category":cat})
            continue
        digest=hashlib.sha256(f"{name}|{cat}|{snap['scan_at_utc']}".encode()).hexdigest()[:16]
        beliefs.append({
            "belief_id":"registry-"+digest,
            "text":f"Registry Health currently classifies {name} as {cat}.",
            "author":"Registry Health","origin_session":"external-registry",
            "type":"fact","source_scope":"registry_health","server_name":name,"registry_category":cat,
            "evidence":[evidence],"confidence":0.95,"last_verified_utc":snap["scan_at_utc"],
            "expires_utc":None,"status":"ACTIVE",
            "verification_history":[{"verified_at_utc":snap["scan_at_utc"],"ok":True,"category":cat}],
        })
        imported+=1
    memory["beliefs"]=beliefs
    memory["external_registry_status"]={
        "status":"READY","scan_at_utc":snap["scan_at_utc"],"imported":imported,
        "active_external_facts":sum(1 for b in beliefs if b.get("source_scope")=="registry_health" and b.get("status")=="ACTIVE"),
        "no_new_scan":True,
    }
    return memory,imported
