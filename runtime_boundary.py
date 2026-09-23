from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

RUNTIME_PROFILE_PATH = Path("runtime_profile.json")
EXPECTED_PROFILE_ID = "mycelix-prod-main"
RUNTIME_STATE_SCHEMA = 1

CONTROL_PLANE_STRONG_MARKERS = (
    "g4_pass",
    "g4_amend",
    "historical terminal vocabulary",
    "exact-head ci",
    "workflow_dispatch",
    "[skip render]",
    "runtime snapshot",
    "github actions workflow",
    "merge commit",
    "pull request #",
)
CONTROL_PLANE_META_RE = re.compile(
    r"\b(?:ci|cd|workflow|deploy|deployment|branch|commit|rollback|rerun)\b",
    re.I,
)


def load_runtime_profile() -> dict:
    raw=RUNTIME_PROFILE_PATH.read_text(encoding="utf-8")
    data=json.loads(raw)
    if not isinstance(data,dict):
        raise RuntimeError("runtime_profile_invalid")
    if int(data.get("schema_version") or 0)!=1:
        raise RuntimeError("runtime_profile_schema_mismatch")
    if str(data.get("profile_id") or "")!=EXPECTED_PROFILE_ID:
        raise RuntimeError("runtime_profile_id_mismatch")
    if str(data.get("deployment_role") or "")!="production":
        raise RuntimeError("runtime_profile_role_mismatch")
    if str(data.get("branch") or "")!="main":
        raise RuntimeError("runtime_profile_branch_mismatch")

    tracks=data.get("tracks") if isinstance(data.get("tracks"),dict) else {}
    commercial=tracks.get("commercial_discovery") if isinstance(tracks.get("commercial_discovery"),dict) else {}
    agent_network=tracks.get("agent_network") if isinstance(tracks.get("agent_network"),dict) else {}
    trust_lab=tracks.get("trust_lab") if isinstance(tracks.get("trust_lab"),dict) else {}
    denied=set(commercial.get("must_not_consume_as_commercial_evidence") or [])
    required_denied={
        "trust_lab_evaluations",
        "inbound_messages",
        "inbound_agent_stats",
        "seti.signal_memory",
        "runtime_telemetry",
        "ci_control_plane_text",
    }
    if not required_denied.issubset(denied):
        raise RuntimeError("runtime_profile_commercial_boundary_incomplete")
    if agent_network.get("may_write_commercial_evidence") is not False:
        raise RuntimeError("runtime_profile_agent_network_boundary_unsafe")
    if trust_lab.get("may_write_commercial_evidence") is not False:
        raise RuntimeError("runtime_profile_trust_boundary_unsafe")
    if trust_lab.get("may_change_commercial_gate") is not False:
        raise RuntimeError("runtime_profile_gate_boundary_unsafe")
    if (data.get("commercial_gate") or {}).get("unchanged") is not True:
        raise RuntimeError("runtime_profile_gate_not_locked")

    canonical=json.dumps(data,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode("utf-8")
    out=dict(data)
    out["config_fingerprint"]=hashlib.sha256(canonical).hexdigest()[:16]
    out["state_schema"]=RUNTIME_STATE_SCHEMA
    return out


def runtime_identity() -> dict:
    profile=load_runtime_profile()
    return {
        "profile_id":profile["profile_id"],
        "deployment_role":profile["deployment_role"],
        "state_namespace":profile["state_namespace"],
        "state_schema":profile["state_schema"],
        "config_fingerprint":profile["config_fingerprint"],
    }


def state_profile_status(payload: dict | None) -> dict:
    if not isinstance(payload,dict):
        return {"compatible":False,"status":"invalid","profile_id":""}
    marker=payload.get("runtime_profile")
    if not isinstance(marker,dict) or not marker.get("profile_id"):
        return {"compatible":True,"status":"legacy_untagged","profile_id":""}
    profile_id=str(marker.get("profile_id") or "")
    return {
        "compatible":profile_id==EXPECTED_PROFILE_ID,
        "status":"match" if profile_id==EXPECTED_PROFILE_ID else "profile_mismatch",
        "profile_id":profile_id,
    }


def is_control_plane_text(value: Any) -> bool:
    text=" ".join(str(value or "").split()).lower()
    if not text:
        return False
    if any(marker in text for marker in CONTROL_PLANE_STRONG_MARKERS):
        return True
    # Require multiple meta/control-plane terms before rejecting generic DevOps pain.
    terms=set(m.group(0).lower() for m in CONTROL_PLANE_META_RE.finditer(text))
    return len(terms)>=3 and any(x in text for x in ("historical","terminal","lineage","head sha","ci rerun","workflow run"))


def _commercial_row_is_control_plane(row: Any) -> bool:
    if not isinstance(row,dict):
        return False
    combined=" ".join(
        str(row.get(k) or "")
        for k in ("pain","thesis","source_title","job_to_be_done","claim","text")
    )
    return is_control_plane_text(combined)


def sanitize_commercial_state(payload: dict | None) -> tuple[dict | None, dict | None]:
    if not isinstance(payload,dict):
        return payload,None

    cleaned=dict(payload)
    events=list(cleaned.get("boundary_events") or [])
    rejected_problem_id=""
    rejected_source_url=""

    thesis=cleaned.get("active_thesis")
    if isinstance(thesis,dict) and _commercial_row_is_control_plane(thesis):
        rejected=dict(thesis)
        rejected["status"]="REJECTED_CONTROL_PLANE_CONTAMINATION"
        rejected["rejected_reason"]="ci_control_plane_text_not_commercial_pain"
        history=list(cleaned.get("thesis_history") or [])
        history.append(rejected)
        cleaned["thesis_history"]=history[-30:]
        cleaned["active_thesis"]=None
        rejected_problem_id=str(thesis.get("problem_id") or "")
        rejected_source_url=str(thesis.get("source_url") or "")

    removed={}
    for key in ("hypothesis_queue","observed_pain_candidates"):
        rows=cleaned.get(key)
        if not isinstance(rows,list):
            continue
        kept=[row for row in rows if not _commercial_row_is_control_plane(row)]
        removed[key]=len(rows)-len(kept)
        cleaned[key]=kept

    total_removed=sum(removed.values())+(1 if rejected_problem_id else 0)
    if not total_removed:
        return payload,None

    event={
        "type":"commercial_boundary_rejection",
        "reason":"ci_control_plane_text_not_commercial_pain",
        "problem_id":rejected_problem_id,
        "source_url":rejected_source_url,
        "removed":removed,
    }
    events.append(event)
    cleaned["boundary_events"]=events[-40:]
    return cleaned,event
