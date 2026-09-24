"""Bounded thesis lifecycle controls.

This module changes search allocation only. It never relaxes the commercial
quality gate or turns historical evidence into current evidence.
"""
from __future__ import annotations
from typing import Any


def exhausted_seed_blocked(
    history: list[dict] | None,
    seed_problem_key: str,
    current_cycle: int,
    cooldown_cycles: int,
) -> bool:
    """Prevent immediate recreation of an exhausted thesis on the same seed."""
    key=str(seed_problem_key or "").strip()
    if not key:
        return False
    current=max(0,int(current_cycle or 0))
    cooldown=max(1,int(cooldown_cycles or 1))
    for raw in reversed(history or []):
        if not isinstance(raw,dict):
            continue
        if str(raw.get("status") or "").upper()!="EXHAUSTED":
            continue
        if str(raw.get("seed_problem_key") or "")!=key:
            continue
        closed=max(0,int(raw.get("closed_at_cycle") or 0))
        return current < closed + cooldown
    return False
