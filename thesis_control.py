"""Bounded thesis lifecycle controls.

This module changes search allocation only. It never relaxes the commercial
quality gate or turns historical evidence into current evidence.
"""
from __future__ import annotations

import re


GENERIC_CUSTOMER_SEGMENTS = {"buyers"}


def thesis_seed_fingerprint(seed_problem_key: str) -> str:
    """Normalize mechanical seed drift without broad semantic guessing.

    Examples such as:
      manual_data_entry:buyers:manual_data_entry
      manual_data_entry:buyers:buyers_manual_data_entry
    map to the same fingerprint because the duplicated adjacent actor token is
    a planner artifact, not a genuinely different customer problem.
    """
    raw=str(seed_problem_key or "").strip().lower()
    if not raw:
        return ""
    family, sep, rest=raw.partition(":")
    if not sep:
        family=""
        rest=raw
    rest_parts=rest.split(":")
    if len(rest_parts)>=2 and rest_parts[0] in GENERIC_CUSTOMER_SEGMENTS:
        rest=":".join(rest_parts[1:])
    words=[x for x in re.split(r"[^a-z0-9]+",rest) if x]
    collapsed=[]
    for word in words:
        if not collapsed or collapsed[-1]!=word:
            collapsed.append(word)
    while len(collapsed)>1 and collapsed[0] in GENERIC_CUSTOMER_SEGMENTS:
        collapsed.pop(0)
    normalized=" ".join(collapsed)
    return (family+"|"+normalized) if family else normalized


def exhausted_seed_blocked(
    history: list[dict] | None,
    seed_problem_key: str,
    current_cycle: int,
    cooldown_cycles: int,
    *,
    current_rank: int | None = None,
    current_missing: list[str] | None = None,
) -> bool:
    """Block stale exhausted seeds unless new evidence materially improves them.

    Inside the cooldown the seed is always blocked. After the cooldown, callers
    that provide candidate evidence context may reopen only when the candidate
    rank improved or at least one previously-missing gate requirement was
    satisfied. Callers without evidence context retain the legacy cooldown-only
    behavior.
    """
    fingerprint=thesis_seed_fingerprint(seed_problem_key)
    if not fingerprint:
        return False
    current=max(0,int(current_cycle or 0))
    cooldown=max(1,int(cooldown_cycles or 1))
    for raw in reversed(history or []):
        if not isinstance(raw,dict):
            continue
        if str(raw.get("status") or "").upper()!="EXHAUSTED":
            continue
        historical_fingerprints={
            thesis_seed_fingerprint(str(raw.get("seed_problem_key") or "")),
            thesis_seed_fingerprint(str(raw.get("problem_id") or "")),
        }
        historical_fingerprints.discard("")
        if fingerprint not in historical_fingerprints:
            continue
        closed=max(0,int(raw.get("closed_at_cycle") or 0))
        if current < closed + cooldown:
            return True
        if current_rank is None and current_missing is None:
            return False
        try:
            previous_rank=int(raw.get("rank") or 0)
        except (TypeError,ValueError):
            previous_rank=0
        candidate_rank=None
        if current_rank is not None:
            try:
                candidate_rank=int(current_rank)
            except (TypeError,ValueError):
                candidate_rank=None
        previous_missing={
            str(x) for x in (raw.get("missing") or []) if str(x)
        }
        candidate_missing={
            str(x) for x in (current_missing or []) if str(x)
        }
        rank_progress=bool(
            candidate_rank is not None and candidate_rank > previous_rank
        )
        missing_progress=bool(
            previous_missing and candidate_missing < previous_missing
        )
        return not (rank_progress or missing_progress)
    return False

def finalize_exhausted_thesis(active: dict | None, *, quality_gate: bool, closed_at_cycle: int) -> dict:
    """Close an active thesis exactly when its bounded cycle budget is consumed.

    A passed commercial quality gate is never converted into exhaustion.
    The caller owns persistence/history updates.
    """
    row=dict(active) if isinstance(active,dict) else {}
    if not row or str(row.get("status") or "").upper()!="ACTIVE":
        return {"closed":False,"active":active,"finished":None}
    try:
        used=max(0,int(row.get("cycles_used") or 0))
        budget=max(1,int(row.get("budget_cycles") or 4))
    except (TypeError,ValueError):
        return {"closed":False,"active":active,"finished":None}
    if quality_gate or used < budget:
        return {"closed":False,"active":row,"finished":None}
    finished=dict(row)
    finished["status"]="EXHAUSTED"
    finished["closed_at_cycle"]=max(0,int(closed_at_cycle or 0))
    return {"closed":True,"active":None,"finished":finished}
