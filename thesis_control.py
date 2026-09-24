"""Bounded thesis lifecycle controls.

This module changes search allocation only. It never relaxes the commercial
quality gate or turns historical evidence into current evidence.
"""
from __future__ import annotations

import re


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
    words=[x for x in re.split(r"[^a-z0-9]+",rest) if x]
    collapsed=[]
    for word in words:
        if not collapsed or collapsed[-1]!=word:
            collapsed.append(word)
    normalized=" ".join(collapsed)
    return (family+"|"+normalized) if family else normalized


def exhausted_seed_blocked(
    history: list[dict] | None,
    seed_problem_key: str,
    current_cycle: int,
    cooldown_cycles: int,
) -> bool:
    """Prevent immediate recreation of an exhausted thesis on the same semantic seed."""
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
        if thesis_seed_fingerprint(str(raw.get("seed_problem_key") or ""))!=fingerprint:
            continue
        closed=max(0,int(raw.get("closed_at_cycle") or 0))
        return current < closed + cooldown
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
