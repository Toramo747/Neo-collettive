# SPDX-License-Identifier: BUSL-1.1
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone

ENTER_STREAK=2
EXIT_STREAK=2
MIN_CONFIRM_SECONDS=6*60*60
MIN_CONFIRM_CYCLES=2
MAX_FLIPS=80

def _utc() -> str:
    return datetime.now(timezone.utc).isoformat()

def _parse_utc(value: object) -> datetime | None:
    raw=str(value or "").strip()
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z","+00:00")).astimezone(timezone.utc)
    except Exception:
        return None

def _norm(value: object) -> str:
    return re.sub(r"[^a-z0-9]+","_",str(value or "").lower()).strip("_")[:120]

def _domains(row: dict | None) -> set[str]:
    src=row if isinstance(row,dict) else {}
    return {
        str(x.get("domain") or "").strip().lower()
        for x in (src.get("sources") or [])
        if isinstance(x,dict) and str(x.get("domain") or "").strip()
    }

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

def _confirmation(
    prev: dict,
    row: dict,
    *,
    raw_pass: bool,
    now: str,
    cycle: int,
) -> tuple[bool,int,int,dict]:
    stable=bool(prev.get("stable"))
    prev_raw=prev.get("last_raw")
    pass_streak=int(prev.get("pass_streak") or 0)
    fail_streak=int(prev.get("fail_streak") or 0)
    last_cycle=int(prev.get("last_observed_cycle") or -1)
    distinct_cycle=cycle!=last_cycle
    fp=opportunity_fingerprint(row)
    domains=_domains(row)

    first_raw_pass_utc=str(prev.get("first_raw_pass_utc") or "") if raw_pass else ""
    first_fp=str(prev.get("first_fingerprint") or "") if raw_pass else ""
    first_domains={str(x) for x in (prev.get("first_domains") or [])} if raw_pass else set()
    pass_cycles={int(x) for x in (prev.get("pass_cycles") or []) if str(x).lstrip("-").isdigit()} if raw_pass else set()

    if raw_pass:
        if not first_raw_pass_utc:
            first_raw_pass_utc=now
            first_fp=fp
            first_domains=set(domains)
            pass_cycles=set()
        if distinct_cycle:
            pass_cycles.add(cycle)
            pass_streak=len(pass_cycles)
        fail_streak=0
        first_dt=_parse_utc(first_raw_pass_utc)
        now_dt=_parse_utc(now)
        seconds=max(0,int((now_dt-first_dt).total_seconds())) if first_dt and now_dt else 0
        new_domains=sorted(domains-first_domains)
        blockers=[]
        if seconds<MIN_CONFIRM_SECONDS:
            blockers.append("min_6_hours")
        if len(pass_cycles)<MIN_CONFIRM_CYCLES:
            blockers.append("min_2_research_cycles")
        if fp==first_fp:
            blockers.append("evidence_fingerprint_unchanged")
        if not new_domains:
            blockers.append("no_new_independent_domain")
        if not stable and not blockers:
            stable=True
    else:
        if distinct_cycle:
            fail_streak=fail_streak+1 if prev_raw is False else 1
        pass_streak=0
        first_raw_pass_utc=""
        first_fp=""
        first_domains=set()
        pass_cycles=set()
        seconds=0
        new_domains=[]
        blockers=[]
        if stable and fail_streak>=EXIT_STREAK:
            stable=False

    meta={
        "first_raw_pass_utc":first_raw_pass_utc,
        "first_fingerprint":first_fp,
        "first_domains":sorted(first_domains),
        "pass_cycles":sorted(pass_cycles)[-16:],
        "last_fingerprint":fp,
        "seconds_since_first_raw_pass":seconds,
        "new_domains_since_first_pass":len(new_domains),
        "confirmation_blockers":blockers,
        "distinct_cycle":distinct_cycle,
    }
    return stable,pass_streak,fail_streak,meta

def apply_gate_hysteresis(
    state: dict | None,
    opportunities: list[dict] | None,
    *,
    version: str="",
    commit: str="",
    observed_at_utc: str | None=None,
    cycle: int=0,
    tagger_version: str="",
    genome_id: str="",
) -> tuple[dict,list[dict]]:
    src=state if isinstance(state,dict) else {}
    current_context={
        "tagger_version":str(tagger_version or "")[:48],
        "genome_id":str(genome_id or "")[:120],
    }
    previous_context=src.get("confirmation_context") if isinstance(src.get("confirmation_context"),dict) else {}
    context_changed=bool(
        previous_context
        and (
            str(previous_context.get("tagger_version") or "")!=current_context["tagger_version"]
            or str(previous_context.get("genome_id") or "")!=current_context["genome_id"]
        )
    )
    candidates={} if context_changed else dict(src.get("candidates") or {})
    flips=list(src.get("flips") or [])
    now=str(observed_at_utc or _utc())
    cycle=max(0,int(cycle or 0))

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
        stable,pass_streak,fail_streak,meta=_confirmation(
            prev,row,raw_pass=raw_pass,now=now,cycle=cycle
        )
        fp=meta["last_fingerprint"]
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
            "first_raw_pass_utc":meta["first_raw_pass_utc"],
            "first_fingerprint":meta["first_fingerprint"],
            "first_domains":meta["first_domains"],
            "pass_cycles":meta["pass_cycles"],
            "last_observed_cycle":cycle,
            "seconds_since_first_raw_pass":meta["seconds_since_first_raw_pass"],
            "new_domains_since_first_pass":meta["new_domains_since_first_pass"],
            "confirmation_blockers":meta["confirmation_blockers"],
            "last_commit":str(commit or "")[:64],
        }
        results[key]=(stable,pass_streak,fail_streak,meta)

    for key,prev_raw in list(candidates.items()):
        if key in seen or not isinstance(prev_raw,dict):
            continue
        prev=dict(prev_raw)
        if int(prev.get("last_observed_cycle") or -1)!=cycle:
            absent=int(prev.get("absent_streak") or 0)+1
            prev["absent_streak"]=absent
            prev["pass_streak"]=0
            prev["first_raw_pass_utc"]=""
            prev["first_fingerprint"]=""
            prev["first_domains"]=[]
            prev["pass_cycles"]=[]
            if bool(prev.get("stable")) and absent>=EXIT_STREAK:
                prev["stable"]=False
                prev["fail_streak"]=max(EXIT_STREAK,int(prev.get("fail_streak") or 0))
            prev["updated_at_utc"]=now
            prev["last_observed_cycle"]=cycle
            candidates[key]=prev

    out=[]
    for raw in opportunities or []:
        if not isinstance(raw,dict):
            continue
        row=dict(raw)
        key=opportunity_identity(row)
        stable,pass_streak,fail_streak,meta=results[key]
        row["raw_gate_pass"]=bool(row.get("gate_pass"))
        row["stable_gate_pass"]=stable
        row["gate_candidate_key"]=key
        row["gate_confirmation"]={
            "pass_streak":pass_streak,
            "fail_streak":fail_streak,
            "enter_required":ENTER_STREAK,
            "exit_required":EXIT_STREAK,
            "seconds_since_first_raw_pass":meta["seconds_since_first_raw_pass"],
            "new_domains_since_first_pass":meta["new_domains_since_first_pass"],
            "confirmation_blockers":meta["confirmation_blockers"],
        }
        out.append(row)

    return {
        "schema_v":3,
        "candidates":candidates,
        "flips":flips[-MAX_FLIPS:],
        "updated_at_utc":now,
        "last_observed_commit":str(commit or "")[:64],
        "confirmation_context":current_context,
        "context_reset":context_changed,
    },out
