"""Deterministic outcome council for MYCELIX.

These agents do not generate evidence and cannot bypass gates. They turn the
existing runtime state into binary, auditable outcomes and next actions.
"""
from __future__ import annotations

from typing import Any


def _int(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _peer_proof(seti: dict | None, inbound_stats: dict | None) -> dict:
    seti = seti if isinstance(seti, dict) else {}
    summary = seti.get("last_summary") if isinstance(seti.get("last_summary"), dict) else {}
    inbound = inbound_stats if isinstance(inbound_stats, dict) else {}

    completed_inbound = []
    for key, row in inbound.items():
        if not isinstance(row, dict):
            continue
        if bool(row.get("interview_complete")) and _int(row.get("dialogue_round")) >= 3:
            completed_inbound.append(str(row.get("agent_id") or key))

    admitted = _int(seti.get("admitted_agent_count") or summary.get("admitted_agent_count"))
    ready = _int(seti.get("interview_ready_now_count") or summary.get("interview_ready_now"))
    eligible = _int(seti.get("eligible_candidate_count") or summary.get("eligible_candidates"))
    complete = bool(completed_inbound) or admitted > 0

    return {
        "agent": "Peer Closer",
        "objective": "Complete one independent public A2A peer dialogue 3/3.",
        "status": "COMPLETE" if complete else "PURSUE",
        "complete": complete,
        "proof": {
            "seti_admitted_after_3_round_gate": admitted,
            "inbound_completed_3_round": completed_inbound[:5],
            "eligible_candidates": eligible,
            "interview_ready_now": ready,
            "last_interview_status": summary.get("last_interview_status"),
        },
        "next_action": (
            "Preserve the completed peer evidence and seek a second independent peer."
            if complete
            else (
                "Run the bounded 3-round interview on the next interview-ready public Agent Card."
                if ready > 0
                else "Find one public HTTPS Agent Card that passes preflight and can answer three substantive rounds."
            )
        ),
    }


def _market_proof(result: dict | None, active_thesis: dict | None, thesis_history: list | None, cycle: int) -> dict:
    result = result if isinstance(result, dict) else {}
    active = active_thesis if isinstance(active_thesis, dict) else {}
    history = [x for x in (thesis_history or []) if isinstance(x, dict)]

    quality = result.get("evidence_quality") if isinstance(result.get("evidence_quality"), dict) else {}
    gate = bool(result.get("quality_gate") or quality.get("quality_gate"))
    qualified = list(result.get("qualified_problem_keys") or quality.get("qualified_problem_keys") or [])

    recent_exhausted = None
    for row in reversed(history):
        if str(row.get("status") or "").upper() != "EXHAUSTED":
            continue
        if _int(row.get("closed_at_cycle")) >= max(0, cycle - 1):
            recent_exhausted = row
            break

    budget = _int(active.get("budget_cycles"))
    used = _int(active.get("cycles_used"))
    remaining = max(0, budget - used) if budget else None
    missing = list(active.get("missing") or [])

    if gate and qualified:
        status = "COMPLETE"
        next_action = "Freeze the validated problem and proceed only to the already-authorized bounded validation/build path."
    elif recent_exhausted:
        status = "THESIS_REJECTED_WITHIN_BUDGET"
        next_action = "Do not reopen the exhausted seed during cooldown; test a materially different problem."
    else:
        status = "PURSUE"
        next_action = (
            "Use the remaining thesis cycles only on the missing gate evidence; exhaust and rotate if it does not arrive."
            if budget else "Select one falsifiable commercial thesis with a bounded cycle budget."
        )

    return {
        "agent": "Market Closer",
        "objective": "Pass the unchanged commercial evidence gate or reject the thesis within its bounded budget.",
        "status": status,
        "complete": bool(gate and qualified),
        "proof": {
            "quality_gate": gate,
            "qualified_problem_keys": qualified[:5],
            "active_thesis_id": active.get("thesis_id"),
            "active_seed": active.get("seed_problem_key"),
            "cycles_used": used,
            "budget_cycles": budget,
            "cycles_remaining": remaining,
            "missing": missing,
            "recent_exhausted_thesis_id": (recent_exhausted or {}).get("thesis_id"),
            "recent_exhausted_closed_at_cycle": (recent_exhausted or {}).get("closed_at_cycle"),
        },
        "next_action": next_action,
    }


def outcome_council(
    *,
    result: dict | None,
    seti: dict | None,
    inbound_stats: dict | None,
    active_thesis: dict | None,
    thesis_history: list | None,
    cycle: int,
    previous: dict | None = None,
) -> dict:
    peer = _peer_proof(seti, inbound_stats)
    market = _market_proof(result, active_thesis, thesis_history, cycle)

    wins = []
    if peer["complete"]:
        wins.append("EXTERNAL_PEER_3_OF_3")
    if market["complete"]:
        wins.append("COMMERCIAL_GATE_PASSED")
    if market["status"] == "THESIS_REJECTED_WITHIN_BUDGET":
        wins.append("THESIS_REJECTED_WITHIN_BUDGET")

    previous = previous if isinstance(previous, dict) else {}
    prior_wins = set(previous.get("wins") or [])
    new_wins = [x for x in wins if x not in prior_wins]

    if new_wins:
        audit_status = "RESULT"
    elif wins:
        audit_status = "HOLD_RESULT"
    else:
        audit_status = "NO_RESULT_YET"

    auditor = {
        "agent": "Outcome Auditor",
        "objective": "Count only externally verifiable outcomes; reject activity metrics as success.",
        "status": audit_status,
        "complete": bool(wins),
        "proof": {
            "wins": wins,
            "new_wins": new_wins,
            "cycle": _int(cycle),
        },
        "next_action": (
            "Protect the achieved result and move to the next unmet binary objective."
            if wins
            else "Do not add features. Spend the next cycle only on peer 3/3 or the active thesis gate/missing evidence."
        ),
    }

    return {
        "schema_v": 1,
        "cycle": _int(cycle),
        "mode": "external_results_only",
        "wins": wins,
        "new_wins": new_wins,
        "result_count": len(wins),
        "agents": {
            "peer_closer": peer,
            "market_closer": market,
            "outcome_auditor": auditor,
        },
        "overall_status": "RESULT" if wins else "WORKING",
        "feature_freeze": not bool(wins),
        "rule": "A version, scan, candidate, build, or internal score is not a result by itself.",
    }
