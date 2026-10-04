# SPDX-License-Identifier: BUSL-1.1
from __future__ import annotations
import hashlib
import json
from datetime import datetime, timezone
from typing import Any

ENTER_STREAK=2
EXIT_STREAK=2
MAX_FLIPS=80

def _utc() -> str:
    return datetime.now(timezone.utc).isoformat()

def opportunity_fingerprint(row: dict | None) -> str:
    src=row if isinstance(row,dict) else {}
    payload={
        "family":str(src.get("family") or ""),
        "tool_name":str(src.get("tool_name") or src.get("title") or ""),
        "score":int(src.get("monetization_score") or 0),
        "missing":sorted(str(x) for x in (src.get("missing") or [])),
        "domains":sorted({
            str(x.get("domain") or "")
            for x in (src.get("sources") or [])
            if isinstance(x,dict) and str(x.get("domain") or "")
        }),
    }
    raw=json.dumps(payload,sort_keys=True,separators=(",",":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:16]

def apply_gate_hysteresis(
    state: dict | None,
    opportunities: list[dict] | None,
    *,
    version: str="",
    commit: str="",
    observed_at_utc: str | None=None,
) -> tuple[dict,list[dict]]:
    src=state if isinstance(state,dict) else {}
    families=dict(src.get("families") or {})
    flips=list(src.get("flips") or [])
    now=str(observed_at_utc or _utc())
    out=[]
    for raw in opportunities or []:
        if not isinstance(raw,dict):
            continue
        row=dict(raw)
        family=str(row.get("family") or "")
        prev=dict(families.get(family) or {})
        raw_pass=bool(row.get("gate_pass"))
        prev_raw=prev.get("last_raw")
        stable=bool(prev.get("stable"))
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

        fp=opportunity_fingerprint(row)
        if prev_raw is not None and bool(prev_raw)!=raw_pass:
            flips.append({
                "observed_at_utc":now,
                "version":str(version or "")[:48],
                "commit":str(commit or "")[:64],
                "family":family[:64],
                "from_raw":bool(prev_raw),
                "to_raw":raw_pass,
                "stable_before":bool(prev.get("stable")),
                "stable_after":stable,
                "score":int(row.get("monetization_score") or 0),
                "missing":[str(x)[:80] for x in (row.get("missing") or [])[:12]],
                "fingerprint":fp,
            })

        families[family]={
            "stable":stable,
            "last_raw":raw_pass,
            "pass_streak":pass_streak,
            "fail_streak":fail_streak,
            "last_score":int(row.get("monetization_score") or 0),
            "last_fingerprint":fp,
            "updated_at_utc":now,
        }
        row["raw_gate_pass"]=raw_pass
        row["stable_gate_pass"]=stable
        row["gate_confirmation"]={
            "pass_streak":pass_streak,
            "fail_streak":fail_streak,
            "enter_required":ENTER_STREAK,
            "exit_required":EXIT_STREAK,
        }
        out.append(row)
    return {
        "schema_v":1,
        "families":families,
        "flips":flips[-MAX_FLIPS:],
        "updated_at_utc":now,
    },out
