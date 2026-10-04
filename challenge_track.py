# SPDX-License-Identifier: BUSL-1.1
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import time
from datetime import datetime, timezone
from typing import Any

from evidence_integrity import canonical_domain, commercial_family, is_self_contamination

CHALLENGE_TAGGER_VERSION = "1"
CHALLENGE_STATE_SCHEMA = 1
CHALLENGE_ENTER_STREAK = 2
CHALLENGE_EXIT_STREAK = 2
MAX_CHALLENGE_FLIPS = 80
PUBLIC_ID_LENGTH = 16

CHALLENGE_MISSING_CODES = frozenset({
    "three_independent_requesters",
    "two_independent_domains",
    "problem_age_60_days",
    "documented_workaround_or_failed_attempt",
    "feasibility_explicit",
    "feasibility_hard",
    "problem_already_resolved",
    "unknown_requirement",
})

PUBLIC_BOUNTY_DOMAINS = (
    "algora.io",
    "issuehunt.io",
    "bountysource.com",
)

_ROUTE_TERMS = (
    "feature request", "help wanted", "missing feature", "unsupported",
    "workaround", "work around", "no way to", "cannot ", "can't ",
    "open problem", "bounty", "reward", "prize", "sponsor",
)
_TOOL_ASK_RE = re.compile(
    r"\b(?:is there (?:a|an) (?:tool|app|software)|looking for (?:a )?(?:tool|app|software)|"
    r"does (?:a|any) (?:tool|app|software) exist|any tool for)\b",
    re.I,
)
_WORKAROUND_RE = re.compile(
    r"\b(?:workaround|work around|manual(?:ly)?|fallback|temporary|hack|"
    r"tried .{0,80}(?:failed|didn['’]t work|doesn['’]t work)|failed attempt)\b",
    re.I,
)
_HARD_RE = re.compile(r"\b(?:infeasible|impossible|not feasible|cannot be solved|undecidable)\b", re.I)
_REWARD_RE = re.compile(r"\b(?:bounty|reward|prize|sponsor(?:ed|ship)?|cash award)\b", re.I)

_STOP_PREFIXES = (
    "feature request", "request", "help wanted", "is there a tool", "is there an app",
    "looking for a tool", "looking for an app", "does a tool exist", "does any tool exist",
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _norm(value: Any, limit: int = 160) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value or "").lower()).strip("_")[:limit]


def challenge_config(env: dict[str, str] | None = None) -> dict:
    src = env if isinstance(env, dict) else os.environ
    def integer(name: str, default: int, low: int, high: int) -> int:
        try:
            value = int(src.get(name, default))
        except Exception:
            value = default
        return max(low, min(high, value))
    return {
        "min_requesters": integer("NEO_CHALLENGE_MIN_REQUESTERS", 3, 1, 20),
        "min_domains": integer("NEO_CHALLENGE_MIN_DOMAINS", 2, 1, 10),
        "min_age_days": integer("NEO_CHALLENGE_MIN_AGE_DAYS", 60, 1, 3650),
        "require_workaround": True,
        "hard_blocks": True,
        "manual_confirmation_required": True,
        "mode": "shadow",
    }


def _epoch(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        if isinstance(value, (int, float)):
            return float(value)
        raw = str(value).strip()
        if raw.isdigit():
            return float(raw)
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).timestamp()
    except Exception:
        return None


def _host(url: str) -> str:
    from urllib.parse import urlsplit
    try:
        return canonical_domain((urlsplit(str(url or "")).hostname or "").lower())
    except Exception:
        return ""


def _labels(metadata: dict) -> set[str]:
    out=set()
    for item in metadata.get("labels") or []:
        if isinstance(item,dict):
            item=item.get("name")
        code=_norm(item,80)
        if code:
            out.add(code)
    return out


def _resolved(metadata: dict) -> bool:
    state=str(metadata.get("state") or "").strip().lower()
    return bool(
        metadata.get("resolved")
        or metadata.get("accepted_answer")
        or metadata.get("accepted_answer_id")
        or state in {"closed","resolved","done"}
    )


def _feasibility(title: str, body: str, metadata: dict) -> str:
    value=str(metadata.get("feasibility") or "").strip().lower()
    if value in {"feasible","hard","unknown"}:
        return value
    text=(str(title or "")+" "+str(body or "")).strip()
    if _HARD_RE.search(text):
        return "hard"
    return "unknown"


def _problem_key(title: str, body: str, family: str) -> str:
    text=" ".join(str(title or "").lower().split())
    for prefix in _STOP_PREFIXES:
        if text.startswith(prefix):
            text=text[len(prefix):].lstrip(" :-?")
    if len(text) < 8:
        text=" ".join(str(body or "").lower().split())[:220]
    tokens=[
        x for x in re.findall(r"[a-z0-9]+",text)
        if x not in {"the","a","an","for","to","of","and","or","please","need","wanted","help"}
    ][:18]
    core="_".join(tokens)[:180] or "unknown_problem"
    return f"{_norm(family,64) or 'other'}|{core}"


def _challenge_key(problem_key: str) -> str:
    return hashlib.sha256(str(problem_key or "").encode("utf-8")).hexdigest()[:24]


def _row_fingerprint(row: dict) -> str:
    payload={
        "challenge_key":str(row.get("challenge_key") or ""),
        "requester_key":str(row.get("requester_key") or ""),
        "domain":str(row.get("domain") or ""),
        "created_at_epoch":int(float(row.get("created_at_epoch") or 0)),
        "workaround":bool(row.get("workaround")),
        "feasibility":str(row.get("feasibility") or ""),
        "reward":bool(row.get("reward")),
        "resolved":bool(row.get("resolved")),
    }
    return hashlib.sha256(json.dumps(payload,sort_keys=True,separators=(",",":")).encode("utf-8")).hexdigest()[:24]


def _hmac_id(secret: str, key_version: str, purpose: str, value: str) -> str:
    derived=hmac.new(
        secret.encode("utf-8"),
        ("mycelix-challenge-telemetry|"+key_version+"|"+purpose).encode("utf-8"),
        hashlib.sha256,
    ).digest()
    return hmac.new(derived,str(value).encode("utf-8"),hashlib.sha256).hexdigest()[:PUBLIC_ID_LENGTH]


def route_challenge_evidence(
    *,
    url: str,
    title: str,
    body: str,
    source: str,
    metadata: dict | None = None,
    commercial_rejection_reason: str = "",
    now_epoch: float | None = None,
) -> dict | None:
    metadata=metadata if isinstance(metadata,dict) else {}
    text=" ".join((str(title or "")+" "+str(body or "")).split())
    if is_self_contamination(url,source,text):
        return None
    domain=_host(url)
    if not domain:
        return None

    labels=_labels(metadata)
    response_count=max(0,int(metadata.get("response_count") or metadata.get("answer_count") or metadata.get("comments_count") or 0))
    satisfactory=bool(metadata.get("satisfactory_answer") or metadata.get("accepted_answer") or metadata.get("accepted_answer_id"))
    unresolved_tool_ask=bool(_TOOL_ASK_RE.search(text) and not satisfactory and response_count==0)
    bounty_source=any(domain==d or domain.endswith("."+d) for d in PUBLIC_BOUNTY_DOMAINS)
    github_shadow=bool(commercial_rejection_reason=="github_no_buyer_problem_context")
    challenge_label=bool(labels & {"help_wanted","feature_request","bounty","reward","good_first_issue"})
    route_term=any(term in text.lower() for term in _ROUTE_TERMS)

    if not (github_shadow or unresolved_tool_ask or bounty_source or challenge_label or route_term):
        return None

    family=commercial_family(text.lower())
    problem_key=_problem_key(title,body,family)
    created=_epoch(metadata.get("created_at_epoch") or metadata.get("created_at") or metadata.get("creation_date"))
    now=float(now_epoch if now_epoch is not None else time.time())
    requester=str(
        metadata.get("requester_key")
        or metadata.get("author")
        or metadata.get("user_login")
        or metadata.get("owner_id")
        or ""
    ).strip()[:160]
    workaround=bool(metadata.get("failed_attempt") or metadata.get("workaround") or _WORKAROUND_RE.search(text))
    feasibility=_feasibility(title,body,metadata)
    reward=bool(metadata.get("reward_explicit") or metadata.get("bounty_amount") or _REWARD_RE.search(text) or bounty_source)
    resolved=_resolved(metadata)

    return {
        "track":"challenge",
        "schema_v":CHALLENGE_STATE_SCHEMA,
        "tagger_v":CHALLENGE_TAGGER_VERSION,
        "challenge_key":_challenge_key(problem_key),
        "problem_key":problem_key,
        "family":family,
        "requester_key":requester,
        "domain":domain,
        "source":_norm(source,64),
        "created_at_epoch":created,
        "first_seen_epoch":now,
        "last_seen_epoch":now,
        "workaround":workaround,
        "feasibility":feasibility,
        "reward":reward,
        "resolved":resolved,
        "reaction_count":max(0,int(metadata.get("reaction_count") or 0)),
        "duplicate_count":max(0,int(metadata.get("duplicate_count") or 0)),
        "labels":sorted(labels)[:12],
        "fingerprint":_row_fingerprint({
            "challenge_key":_challenge_key(problem_key),
            "requester_key":requester,
            "domain":domain,
            "created_at_epoch":created or 0,
            "workaround":workaround,
            "feasibility":feasibility,
            "reward":reward,
            "resolved":resolved,
        }),
    }


def merge_challenge_memory(existing: list[dict] | None, current: list[dict] | None, now_epoch: float | None=None) -> list[dict]:
    now=float(now_epoch if now_epoch is not None else time.time())
    retention=365*24*3600
    rows=[
        dict(x) for x in (existing or [])
        if isinstance(x,dict) and now-float(x.get("last_seen_epoch") or now) <= retention
    ]
    index={}
    for i,row in enumerate(rows):
        key=str(row.get("fingerprint") or "")
        if key:
            index[key]=i
    for raw in current or []:
        if not isinstance(raw,dict):
            continue
        row=dict(raw)
        row["track"]="challenge"
        key=str(row.get("fingerprint") or _row_fingerprint(row))
        row["fingerprint"]=key
        if key in index:
            old=rows[index[key]]
            row["first_seen_epoch"]=min(float(old.get("first_seen_epoch") or now),float(row.get("first_seen_epoch") or now))
            row["last_seen_epoch"]=now
            rows[index[key]]=row
        else:
            index[key]=len(rows)
            rows.append(row)
    rows.sort(key=lambda x:float(x.get("last_seen_epoch") or 0),reverse=True)
    return rows[:300]


def evaluate_challenges(memory: list[dict] | None, *, config: dict | None=None, now_epoch: float | None=None) -> list[dict]:
    cfg=dict(challenge_config())
    if isinstance(config,dict):
        cfg.update(config)
    now=float(now_epoch if now_epoch is not None else time.time())
    grouped={}
    for row in memory or []:
        if not isinstance(row,dict) or str(row.get("track") or "")!="challenge":
            continue
        key=str(row.get("challenge_key") or "")
        if key:
            grouped.setdefault(key,[]).append(row)
    out=[]
    for key,rows in grouped.items():
        open_rows=[r for r in rows if not bool(r.get("resolved"))]
        requesters={str(r.get("requester_key") or "") for r in open_rows if str(r.get("requester_key") or "")}
        domains={str(r.get("domain") or "") for r in open_rows if str(r.get("domain") or "")}
        created=[float(r.get("created_at_epoch")) for r in open_rows if r.get("created_at_epoch") is not None]
        age_days=max(0,int((now-min(created))/86400)) if created else 0
        workaround_count=sum(1 for r in open_rows if bool(r.get("workaround")))
        reward_count=sum(1 for r in open_rows if bool(r.get("reward")))
        feas={str(r.get("feasibility") or "") for r in open_rows}
        feasibility="hard" if "hard" in feas else "feasible" if "feasible" in feas else "unknown" if "unknown" in feas else ""
        missing=[]
        if not open_rows:
            missing.append("problem_already_resolved")
        if len(requesters)<int(cfg["min_requesters"]):
            missing.append("three_independent_requesters")
        if len(domains)<int(cfg["min_domains"]):
            missing.append("two_independent_domains")
        if age_days<int(cfg["min_age_days"]):
            missing.append("problem_age_60_days")
        if bool(cfg.get("require_workaround",True)) and workaround_count<1:
            missing.append("documented_workaround_or_failed_attempt")
        if feasibility not in {"feasible","hard","unknown"}:
            missing.append("feasibility_explicit")
        if bool(cfg.get("hard_blocks",True)) and feasibility=="hard":
            missing.append("feasibility_hard")
        missing=[x if x in CHALLENGE_MISSING_CODES else "unknown_requirement" for x in missing]
        gate_pass=not missing
        score=min(100,
            min(len(requesters),3)*10
            + min(len(domains),2)*10
            + (20 if age_days>=int(cfg["min_age_days"]) else min(19,age_days//3))
            + (15 if workaround_count else 0)
            + (15 if feasibility=="feasible" else 10 if feasibility=="unknown" else 0)
            + min(reward_count,1)*5
        )
        out.append({
            "challenge_key":key,
            "family":str(rows[0].get("family") or "other")[:64],
            "source_count":len(open_rows),
            "independent_requester_count":len(requesters),
            "independent_domain_count":len(domains),
            "age_days":age_days,
            "workaround_count":workaround_count,
            "feasibility":feasibility or "unknown",
            "reward_signal_count":reward_count,
            "score":score,
            "gate_pass":gate_pass,
            "missing":missing,
            "evidence_fingerprint":hashlib.sha256(
                "|".join(sorted(str(r.get("fingerprint") or "") for r in rows)).encode("utf-8")
            ).hexdigest()[:24],
        })
    out.sort(key=lambda r:(int(bool(r.get("gate_pass"))),int(r.get("score") or 0),int(r.get("independent_requester_count") or 0)),reverse=True)
    return out


def _advance(prev: dict, raw_pass: bool) -> tuple[bool,int,int]:
    stable=bool(prev.get("stable"))
    previous=prev.get("last_raw")
    ps=int(prev.get("pass_streak") or 0)
    fs=int(prev.get("fail_streak") or 0)
    if raw_pass:
        ps=ps+1 if previous is True else 1
        fs=0
        if not stable and ps>=CHALLENGE_ENTER_STREAK:
            stable=True
    else:
        fs=fs+1 if previous is False else 1
        ps=0
        if stable and fs>=CHALLENGE_EXIT_STREAK:
            stable=False
    return stable,ps,fs


def apply_challenge_hysteresis(
    state: dict | None,
    candidates_in: list[dict] | None,
    *,
    commit: str="",
    observed_at_utc: str | None=None,
) -> tuple[dict,list[dict]]:
    src=state if isinstance(state,dict) else {}
    states=dict(src.get("candidates") or {})
    flips=list(src.get("flips") or [])
    now=str(observed_at_utc or _now_iso())
    results=[]
    seen=set()
    for raw in candidates_in or []:
        if not isinstance(raw,dict):
            continue
        row=dict(raw)
        key=str(row.get("challenge_key") or "")
        if not key:
            continue
        seen.add(key)
        prev=dict(states.get(key) or {})
        raw_pass=bool(row.get("gate_pass"))
        stable,ps,fs=_advance(prev,raw_pass)
        first=str(prev.get("first_raw_pass_utc") or "") if raw_pass else ""
        if raw_pass and not first:
            first=now
        if prev.get("last_raw") is not None and bool(prev.get("last_raw"))!=raw_pass:
            flips.append({
                "observed_at_utc":now,
                "candidate_key":key,
                "from_raw":bool(prev.get("last_raw")),
                "to_raw":raw_pass,
                "previous_missing":list(prev.get("last_missing") or [])[:12],
                "current_missing":list(row.get("missing") or [])[:12],
            })
        states[key]={
            "stable":stable,
            "last_raw":raw_pass,
            "pass_streak":ps,
            "fail_streak":fs,
            "absent_streak":0,
            "last_missing":list(row.get("missing") or [])[:12],
            "last_score":int(row.get("score") or 0),
            "first_raw_pass_utc":first,
            "updated_at_utc":now,
            "last_commit":str(commit or "")[:64],
        }
        row["raw_gate_pass"]=raw_pass
        row["stable_gate_pass"]=stable
        row["gate_confirmation"]={"pass_streak":ps,"fail_streak":fs,"enter_required":CHALLENGE_ENTER_STREAK,"exit_required":CHALLENGE_EXIT_STREAK}
        results.append(row)
    for key,prev0 in list(states.items()):
        if key in seen or not isinstance(prev0,dict):
            continue
        prev=dict(prev0)
        absent=int(prev.get("absent_streak") or 0)+1
        prev["absent_streak"]=absent
        prev["pass_streak"]=0
        prev["first_raw_pass_utc"]=""
        if bool(prev.get("stable")) and absent>=CHALLENGE_EXIT_STREAK:
            prev["stable"]=False
            prev["fail_streak"]=max(CHALLENGE_EXIT_STREAK,int(prev.get("fail_streak") or 0))
        states[key]=prev
    return {
        "schema_v":CHALLENGE_STATE_SCHEMA,
        "candidates":states,
        "flips":flips[-MAX_CHALLENGE_FLIPS:],
        "updated_at_utc":now,
        "last_observed_commit":str(commit or "")[:64],
    },results


def build_challenge_telemetry(
    rows: list[dict] | None,
    gate_state: dict | None,
    *,
    secret: str,
    id_key_version: str,
    cycle: int,
    commit: str,
    first_cycle_after_deploy: bool,
    observed_at_utc: str,
) -> list[dict]:
    if not secret:
        return []
    states=(gate_state or {}).get("candidates") if isinstance(gate_state,dict) else {}
    states=states if isinstance(states,dict) else {}
    now=_epoch(observed_at_utc) or time.time()
    out=[]
    for row in list(rows or [])[:3]:
        if not isinstance(row,dict):
            continue
        key=str(row.get("challenge_key") or "")
        state=states.get(key) if isinstance(states.get(key),dict) else {}
        first=_epoch(state.get("first_raw_pass_utc"))
        missing=[str(x) for x in (row.get("missing") or []) if str(x) in CHALLENGE_MISSING_CODES][:12]
        out.append({
            "candidate_id":_hmac_id(secret,id_key_version,"candidate",key),
            "evidence_fingerprint":_hmac_id(secret,id_key_version,"evidence",str(row.get("evidence_fingerprint") or "")),
            "id_key_version":str(id_key_version or "v1")[:16],
            "score":max(0,int(row.get("score") or 0)),
            "source_count":max(0,int(row.get("source_count") or 0)),
            "independent_domain_count":max(0,int(row.get("independent_domain_count") or 0)),
            "independent_requester_count":max(0,int(row.get("independent_requester_count") or 0)),
            "age_days":max(0,int(row.get("age_days") or 0)),
            "workaround_count":max(0,int(row.get("workaround_count") or 0)),
            "feasibility_code":str(row.get("feasibility") or "unknown") if str(row.get("feasibility") or "") in {"feasible","hard","unknown"} else "unknown",
            "reward_signal_count":max(0,int(row.get("reward_signal_count") or 0)),
            "raw_gate_pass":bool(row.get("raw_gate_pass")),
            "stable_gate_pass":bool(row.get("stable_gate_pass")),
            "pass_streak":max(0,int((row.get("gate_confirmation") or {}).get("pass_streak") or 0)),
            "fail_streak":max(0,int((row.get("gate_confirmation") or {}).get("fail_streak") or 0)),
            "missing_codes":missing,
            "cycle":max(0,int(cycle or 0)),
            "commit":str(commit or "")[:64],
            "first_cycle_after_deploy":bool(first_cycle_after_deploy),
            "seconds_since_first_raw_pass":max(0,int(now-first)) if first else None,
            "tagger_version":CHALLENGE_TAGGER_VERSION,
        })
    return out


def challenge_funnel(collected: int, current_rows: list[dict], evaluated: list[dict]) -> dict:
    requesters={str(x.get("requester_key") or "") for x in current_rows if str(x.get("requester_key") or "")}
    return {
        "collected":max(0,int(collected or 0)),
        "routed":len(current_rows),
        "independent_requesters":len(requesters),
        "age_qualified":sum(1 for x in current_rows if x.get("created_at_epoch") and (time.time()-float(x.get("created_at_epoch")))/86400>=60),
        "workarounds":sum(1 for x in current_rows if bool(x.get("workaround"))),
        "feasibility_checked":sum(1 for x in current_rows if str(x.get("feasibility") or "") in {"feasible","hard","unknown"}),
        "ready":sum(1 for x in evaluated if bool(x.get("stable_gate_pass"))),
    }


def evaluate_public_control_cases(cases: list[dict]) -> dict:
    total=correct=0
    details=[]
    for case in cases or []:
        if not isinstance(case,dict):
            continue
        total+=1
        cfg=case.get("config") if isinstance(case.get("config"),dict) else None
        rows=[dict(x,track="challenge") for x in (case.get("evidence") or []) if isinstance(x,dict)]
        evaluated=evaluate_challenges(rows,config=cfg,now_epoch=float(case.get("now_epoch") or 0) or time.time())
        observed=bool(evaluated and evaluated[0].get("gate_pass"))
        expected=bool(case.get("expect_ready"))
        ok=observed==expected
        correct+=int(ok)
        details.append({"id":str(case.get("id") or "")[:80],"ok":ok,"observed_ready":observed})
    return {"cases":total,"correct":correct,"accuracy":round(correct/max(1,total),4),"details":details,"track":"challenge","used_for_evolution":False}


__all__=[
    "CHALLENGE_MISSING_CODES","CHALLENGE_TAGGER_VERSION","challenge_config",
    "route_challenge_evidence","merge_challenge_memory","evaluate_challenges",
    "apply_challenge_hysteresis","build_challenge_telemetry","challenge_funnel",
    "evaluate_public_control_cases",
]
