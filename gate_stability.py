# SPDX-License-Identifier: BUSL-1.1
from __future__ import annotations
import hashlib
import json
import re
from datetime import datetime, timezone

ENTER_STREAK=2
EXIT_STREAK=2
MAX_FLIPS=80

def _utc() -> str:
    return datetime.now(timezone.utc).isoformat()

def _norm(value: object) -> str:
    return re.sub(r"[^a-z0-9]+","_",str(value or "").lower()).strip("_")[:120]

def opportunity_identity(row: dict | None) -> str:
    src=row if isinstance(row,dict) else {}
    family=_norm(src.get("family"))
    tool=_norm(src.get("tool_name") or src.get("title"))
    target=_norm(src.get("target_user"))
    problem=_norm(src.get("problem"))
    material="|".join((family,tool,target,problem))
    digest=hashlib.sha256(material.encode("utf-8")).hexdigest()[:16]
    return (family or "unknown")+"|"+digest

def opportunity_fingerprint(row: dict | None) -> str:
    src=row if isinstance(row,dict) else {}
    payload={
        "identity":opportunity_identity(src),
        "sources":sorted([
            {
                "domain":str(x.get("domain") or ""),
                "signal_types":sorted(str(v) for v in (x.get("signal_types") or [])),
                "real_price":bool(x.get("real_price")),
                "payment_required":bool(x.get("payment_required")),
                "coverage_source":str(x.get("coverage_source") or ""),
            }
            for x in (src.get("sources") or [])
            if isinstance(x,dict)
        ],key=lambda x:json.dumps(x,sort_keys=True)),
        "existing_tools":sorted([
            {"domain":str(x.get("domain") or ""),"price":str(x.get("price") or "")}
            for x in (src.get("existing_tools") or [])
            if isinstance(x,dict)
        ],key=lambda x:json.dumps(x,sort_keys=True)),
    }
    raw=json.dumps(payload,sort_keys=True,separators=(",",":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:16]

def _advance(prev: dict, raw_pass: bool) -> tuple[bool,int,int]:
    stable=bool(prev.get("stable"))
    prev_raw=prev.get("last_raw")
    pass_streak=int(prev.get("pass_streak") or 0)
    fail_streak=int(prev.get("fail_streak") or 0)
    if raw_pass:
        pass_streak=pass_streak+1 if prev_raw is True else 1
        fail_streak=0
        if not stable and pass_streak>=ENTER_STREAK:
            stable=True
    else:
        fail_streak=fail_streak+1 if prev_raw is False else 1
        pass_streak=0
        if stable and fail_streak>=EXIT_STREAK:
            stable=False
    return stable,pass_streak,fail_streak

def apply_gate_hysteresis(
    state: dict | None,
    opportunities: list[dict] | None,
    *,
    version: str="",
    commit: str="",
    observed_at_utc: str | None=None,
) -> tuple[dict,list[dict]]:
    src=state if isinstance(state,dict) else {}
    candidates=dict(src.get("candidates") or {})
    flips=list(src.get("flips") or [])
    now=str(observed_at_utc or _utc())

    # One state transition per stable opportunity identity per cycle.
    grouped={}
    order=[]
    for raw in opportunities or []:
        if not isinstance(raw,dict):
            continue
        row=dict(raw)
        key=opportunity_identity(row)
        if key not in grouped:
            order.append(key)
            grouped[key]=row
        else:
            # Keep the strongest representative without advancing streak twice.
            current=grouped[key]
            if (
                int(bool(row.get("gate_pass"))),
                int(row.get("monetization_score") or 0),
                len(row.get("sources") or []),
            ) > (
                int(bool(current.get("gate_pass"))),
                int(current.get("monetization_score") or 0),
                len(current.get("sources") or []),
            ):
                grouped[key]=row

    seen=set(grouped)
    results={}
    for key in order:
        row=grouped[key]
        prev=dict(candidates.get(key) or {})
        raw_pass=bool(row.get("gate_pass"))
        stable,pass_streak,fail_streak=_advance(prev,raw_pass)
        fp=opportunity_fingerprint(row)
        if prev.get("last_raw") is not None and bool(prev.get("last_raw"))!=raw_pass:
            flips.append({
                "observed_at_utc":now,
                "version":str(version or "")[:48],
                "commit":str(commit or "")[:64],
                "candidate_key":key,
                "family":str(row.get("family") or "")[:64],
                "from_raw":bool(prev.get("last_raw")),
                "to_raw":raw_pass,
                "stable_before":bool(prev.get("stable")),
                "stable_after":stable,
                "previous_score":int(prev.get("last_score") or 0),
                "current_score":int(row.get("monetization_score") or 0),
                "previous_missing":[str(x)[:80] for x in (prev.get("last_missing") or [])[:12]],
                "current_missing":[str(x)[:80] for x in (row.get("missing") or [])[:12]],
                "previous_fingerprint":str(prev.get("last_fingerprint") or ""),
                "current_fingerprint":fp,
                "evidence_unchanged":bool(fp and fp==str(prev.get("last_fingerprint") or "")),
            })
        first_raw_pass_utc=str(prev.get("first_raw_pass_utc") or "") if raw_pass else ""
        if raw_pass and not first_raw_pass_utc:
            first_raw_pass_utc=now
        candidates[key]={
            "stable":stable,
            "last_raw":raw_pass,
            "pass_streak":pass_streak,
            "fail_streak":fail_streak,
            "absent_streak":0,
            "last_score":int(row.get("monetization_score") or 0),
            "last_missing":[str(x)[:80] for x in (row.get("missing") or [])[:12]],
            "last_fingerprint":fp,
            "family":str(row.get("family") or "")[:64],
            "updated_at_utc":now,
            "first_raw_pass_utc":first_raw_pass_utc,
            "last_commit":str(commit or "")[:64],
        }
        results[key]=(stable,pass_streak,fail_streak)

    # A previously stable candidate cannot remain stable forever if it vanishes.
    for key,prev_raw in list(candidates.items()):
        if key in seen or not isinstance(prev_raw,dict):
            continue
        prev=dict(prev_raw)
        absent=int(prev.get("absent_streak") or 0)+1
        prev["absent_streak"]=absent
        prev["pass_streak"]=0
        if bool(prev.get("stable")) and absent>=EXIT_STREAK:
            prev["stable"]=False
            prev["fail_streak"]=max(EXIT_STREAK,int(prev.get("fail_streak") or 0))
        prev["updated_at_utc"]=now
        candidates[key]=prev

    out=[]
    for raw in opportunities or []:
        if not isinstance(raw,dict):
            continue
        row=dict(raw)
        key=opportunity_identity(row)
        stable,pass_streak,fail_streak=results[key]
        row["raw_gate_pass"]=bool(row.get("gate_pass"))
        row["stable_gate_pass"]=stable
        row["gate_candidate_key"]=key
        row["gate_confirmation"]={
            "pass_streak":pass_streak,
            "fail_streak":fail_streak,
            "enter_required":ENTER_STREAK,
            "exit_required":EXIT_STREAK,
        }
        out.append(row)

    return {
        "schema_v":2,
        "candidates":candidates,
        "flips":flips[-MAX_FLIPS:],
        "updated_at_utc":now,
        "last_observed_commit":str(commit or "")[:64],
    },out
