# SPDX-License-Identifier: BUSL-1.1
from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timezone

ENTER_STREAK=2
EXIT_STREAK=2
MIN_CONFIRM_SECONDS=6*60*60
MIN_CONFIRM_CYCLES=2
CONFIRM_FAIL_RESET=max(1,int(os.getenv("NEO_GATE_CONFIRM_FAIL_RESET","3")))
CONFIRM_MIN_PASS_RATIO=max(0.0,min(1.0,float(os.getenv("NEO_GATE_CONFIRM_MIN_PASS_RATIO","0.60"))))
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
    post_deploy_pass_ignored: bool = False,
) -> tuple[bool,int,int,dict]:
    stable=bool(prev.get("stable"))
    prev_raw=prev.get("last_raw")
    pass_streak=int(prev.get("pass_streak") or 0)
    fail_streak=int(prev.get("fail_streak") or 0)
    last_cycle=int(prev.get("last_observed_cycle") or -1)
    distinct_cycle=cycle!=last_cycle
    fp=opportunity_fingerprint(row)
    domains=_domains(row)

    first_raw_pass_utc=str(prev.get("first_raw_pass_utc") or "")
    first_fp=str(prev.get("first_fingerprint") or "")
    first_domains={str(x) for x in (prev.get("first_domains") or [])}
    pass_cycles={int(x) for x in (prev.get("pass_cycles") or []) if str(x).lstrip("-").isdigit()}
    observations=[
        {
            "cycle":int(x.get("cycle") or 0),
            "passed":bool(x.get("passed")),
            "observed_at_utc":str(x.get("observed_at_utc") or ""),
        }
        for x in (prev.get("confirmation_observations") or [])
        if isinstance(x,dict)
    ][-64:]
    confirmation_fail_streak=max(0,int(prev.get("confirmation_fail_streak") or 0))

    def reset_series() -> None:
        nonlocal first_raw_pass_utc,first_fp,first_domains,pass_cycles,observations
        nonlocal confirmation_fail_streak,pass_streak
        first_raw_pass_utc=""
        first_fp=""
        first_domains=set()
        pass_cycles=set()
        observations=[]
        confirmation_fail_streak=0
        pass_streak=0

    # Stable candidates retain the existing EXIT_STREAK behavior exactly.
    if stable:
        if raw_pass:
            fail_streak=0
            if distinct_cycle:
                pass_streak=pass_streak+1 if prev_raw is True else 1
        else:
            if distinct_cycle:
                fail_streak=fail_streak+1 if prev_raw is False else 1
            pass_streak=0
            if fail_streak>=EXIT_STREAK:
                stable=False
                reset_series()
        meta={
            "first_raw_pass_utc":first_raw_pass_utc,
            "first_fingerprint":first_fp,
            "first_domains":sorted(first_domains),
            "pass_cycles":sorted(pass_cycles)[-16:],
            "confirmation_observations":observations,
            "confirmation_fail_streak":confirmation_fail_streak,
            "last_fingerprint":fp,
            "seconds_since_first_raw_pass":max(0,int(prev.get("seconds_since_first_raw_pass") or 0)),
            "new_domains_since_first_pass":max(0,int(prev.get("new_domains_since_first_pass") or 0)),
            "confirmation_blockers":[],
            "tolerated_fail_cycles":0,
            "pass_ratio_in_window":1.0 if raw_pass else 0.0,
            "distinct_cycle":distinct_cycle,
            "post_deploy_pass_ignored":False,
        }
        return stable,pass_streak,fail_streak,meta

    # A raw pass from the first cycle after a deploy is diagnostic only.
    # It neither opens nor advances the confirmation window.
    if post_deploy_pass_ignored and raw_pass:
        first_dt=_parse_utc(first_raw_pass_utc)
        now_dt=_parse_utc(now)
        seconds=max(0,int((now_dt-first_dt).total_seconds())) if first_dt and now_dt else 0
        observed_count=len(observations)
        passed_count=sum(1 for x in observations if x.get("passed"))
        ratio=(passed_count/observed_count) if observed_count else 0.0
        meta={
            "first_raw_pass_utc":first_raw_pass_utc,
            "first_fingerprint":first_fp,
            "first_domains":sorted(first_domains),
            "pass_cycles":sorted(pass_cycles)[-16:],
            "confirmation_observations":observations,
            "confirmation_fail_streak":confirmation_fail_streak,
            "last_fingerprint":fp,
            "seconds_since_first_raw_pass":seconds,
            "new_domains_since_first_pass":max(0,int(prev.get("new_domains_since_first_pass") or 0)),
            "confirmation_blockers":["post_deploy_pass_ignored"],
            "tolerated_fail_cycles":sum(1 for x in observations if not x.get("passed")),
            "pass_ratio_in_window":ratio,
            "distinct_cycle":False,
            "post_deploy_pass_ignored":True,
        }
        return False,len(pass_cycles),fail_streak,meta

    # Before the first passing observation there is no confirmation window.
    if raw_pass and not first_raw_pass_utc:
        first_raw_pass_utc=now
        first_fp=fp
        first_domains=set(domains)
        pass_cycles=set()
        observations=[]
        confirmation_fail_streak=0

    if first_raw_pass_utc and distinct_cycle:
        observations.append({"cycle":cycle,"passed":raw_pass,"observed_at_utc":now})
        observations=observations[-64:]
        if raw_pass:
            pass_cycles.add(cycle)
            confirmation_fail_streak=0
        else:
            confirmation_fail_streak+=1

    pass_streak=len(pass_cycles)
    fail_streak=confirmation_fail_streak if first_raw_pass_utc else (fail_streak+1 if distinct_cycle and prev_raw is False else 1 if distinct_cycle and not raw_pass else 0)

    first_dt=_parse_utc(first_raw_pass_utc)
    now_dt=_parse_utc(now)
    seconds=max(0,int((now_dt-first_dt).total_seconds())) if first_dt and now_dt else 0
    observed_count=len(observations)
    passed_count=sum(1 for x in observations if x.get("passed"))
    ratio=(passed_count/observed_count) if observed_count else 0.0

    reset_reason=""
    if first_raw_pass_utc and confirmation_fail_streak>=CONFIRM_FAIL_RESET:
        reset_reason="consecutive_failures"
    elif first_raw_pass_utc and seconds>=MIN_CONFIRM_SECONDS and observed_count and ratio<CONFIRM_MIN_PASS_RATIO:
        reset_reason="pass_ratio_below_60"

    if reset_reason:
        reset_series()
        # A passing cycle that triggers a ratio reset is also the first
        # observation of the new confirmation series.
        if raw_pass:
            first_raw_pass_utc=now
            first_fp=fp
            first_domains=set(domains)
            pass_cycles={cycle}
            observations=[{"cycle":cycle,"passed":True,"observed_at_utc":now}]
            pass_streak=1
            fail_streak=0
            ratio=1.0
        else:
            fail_streak=0
            ratio=0.0
        seconds=0

    new_domains=sorted(domains-first_domains) if first_raw_pass_utc else []
    blockers=[]
    if raw_pass and first_raw_pass_utc:
        if seconds<MIN_CONFIRM_SECONDS:
            blockers.append("min_6_hours")
        if len(pass_cycles)<MIN_CONFIRM_CYCLES:
            blockers.append("min_2_research_cycles")
        if fp==first_fp:
            blockers.append("evidence_fingerprint_unchanged")
        if not new_domains:
            blockers.append("no_new_independent_domain")
        if seconds>=MIN_CONFIRM_SECONDS and ratio<CONFIRM_MIN_PASS_RATIO:
            blockers.append("pass_ratio_below_60")
        if not blockers:
            stable=True

    tolerated_fail_cycles=(
        sum(1 for x in observations if not x.get("passed"))
        if first_raw_pass_utc and confirmation_fail_streak<CONFIRM_FAIL_RESET else 0
    )
    meta={
        "first_raw_pass_utc":first_raw_pass_utc,
        "first_fingerprint":first_fp,
        "first_domains":sorted(first_domains),
        "pass_cycles":sorted(pass_cycles)[-16:],
        "confirmation_observations":observations,
        "confirmation_fail_streak":confirmation_fail_streak,
        "last_fingerprint":fp,
        "seconds_since_first_raw_pass":seconds,
        "new_domains_since_first_pass":len(new_domains),
        "confirmation_blockers":blockers,
        "tolerated_fail_cycles":tolerated_fail_cycles,
        "pass_ratio_in_window":ratio,
        "distinct_cycle":distinct_cycle,
        "post_deploy_pass_ignored":False,
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
    first_cycle_after_deploy: bool=False,
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
            prev,row,raw_pass=raw_pass,now=now,cycle=cycle,
            post_deploy_pass_ignored=bool(first_cycle_after_deploy and raw_pass and not bool(prev.get("stable"))),
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
            "confirmation_observations":meta["confirmation_observations"],
            "confirmation_fail_streak":meta["confirmation_fail_streak"],
            "last_observed_cycle":cycle,
            "seconds_since_first_raw_pass":meta["seconds_since_first_raw_pass"],
            "new_domains_since_first_pass":meta["new_domains_since_first_pass"],
            "confirmation_blockers":meta["confirmation_blockers"],
            "tolerated_fail_cycles":meta["tolerated_fail_cycles"],
            "pass_ratio_in_window":meta["pass_ratio_in_window"],
            "post_deploy_pass_ignored":bool(meta.get("post_deploy_pass_ignored")),
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
            if bool(prev.get("stable")):
                prev["pass_streak"]=0
                if absent>=EXIT_STREAK:
                    prev["stable"]=False
                    prev["fail_streak"]=max(EXIT_STREAK,int(prev.get("fail_streak") or 0))
                    prev["first_raw_pass_utc"]=""
                    prev["first_fingerprint"]=""
                    prev["first_domains"]=[]
                    prev["pass_cycles"]=[]
                    prev["confirmation_observations"]=[]
                    prev["confirmation_fail_streak"]=0
            elif str(prev.get("first_raw_pass_utc") or ""):
                obs=[x for x in (prev.get("confirmation_observations") or []) if isinstance(x,dict)][-63:]
                obs.append({"cycle":cycle,"passed":False,"observed_at_utc":now})
                prev["confirmation_observations"]=obs
                consecutive=max(0,int(prev.get("confirmation_fail_streak") or 0))+1
                prev["confirmation_fail_streak"]=consecutive
                total=len(obs)
                passed=sum(1 for x in obs if bool(x.get("passed")))
                ratio=(passed/total) if total else 0.0
                first_dt=_parse_utc(prev.get("first_raw_pass_utc"))
                now_dt=_parse_utc(now)
                elapsed=max(0,int((now_dt-first_dt).total_seconds())) if first_dt and now_dt else 0
                prev["tolerated_fail_cycles"]=sum(1 for x in obs if not bool(x.get("passed")))
                prev["pass_ratio_in_window"]=ratio
                if consecutive>=CONFIRM_FAIL_RESET or (elapsed>=MIN_CONFIRM_SECONDS and ratio<CONFIRM_MIN_PASS_RATIO):
                    prev["pass_streak"]=0
                    prev["fail_streak"]=0
                    prev["first_raw_pass_utc"]=""
                    prev["first_fingerprint"]=""
                    prev["first_domains"]=[]
                    prev["pass_cycles"]=[]
                    prev["confirmation_observations"]=[]
                    prev["confirmation_fail_streak"]=0
                    prev["tolerated_fail_cycles"]=0
                    prev["pass_ratio_in_window"]=0.0
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
            "tolerated_fail_cycles":meta["tolerated_fail_cycles"],
            "pass_ratio_in_window":meta["pass_ratio_in_window"],
            "post_deploy_pass_ignored":bool(meta.get("post_deploy_pass_ignored")),
        }
        out.append(row)

    return {
        "schema_v":4,
        "candidates":candidates,
        "flips":flips[-MAX_FLIPS:],
        "updated_at_utc":now,
        "last_observed_commit":str(commit or "")[:64],
        "confirmation_context":current_context,
        "context_reset":context_changed,
        "post_deploy_pass_ignored":sum(
            1 for _stable,_pass,_fail,meta in results.values()
            if bool(meta.get("post_deploy_pass_ignored"))
        ),
    },out
