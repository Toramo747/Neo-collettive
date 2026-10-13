# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Andrea Gava
"""Bounded peer-response classification for MYCELIX SETI.

Classification is behavioral and task-scoped. It does not verify identity, truth,
reputation, commercial demand, or authorize external actions.
"""
from __future__ import annotations

import re
from typing import Any

PEER_CLASSES = {
    "COLLABORATIVE",
    "COMMERCIAL_SERVICE",
    "AUTH_REQUIRED",
    "PAYMENT_REQUIRED",
    "LOW_VALUE",
    "PROTOCOL_ONLY",
}

BLOCKED_FOLLOWUP_STATES = {
    "AUTH_REQUIRED": "AUTH_BLOCKED",
    "PAYMENT_REQUIRED": "PAYMENT_BLOCKED",
    "COMMERCIAL_SERVICE": "COMMERCIAL_ONLY",
    "LOW_VALUE": "LOW_VALUE_PARKED",
}

BLOCKED_PEER_CLASSES = frozenset(BLOCKED_FOLLOWUP_STATES)

_AUTH_PATTERNS = (
    r"\bapi[ -]?key\b",
    r"\bauthorization\s*:",
    r"\bbearer(?:\s+token)?\b",
    r"\b(?:requires?|provide)\s+(?:an?\s+)?(?:api\s+key|authentication|credentials?)\b",
    r"\bfull access\b.{0,80}\b(?:api key|authorization|credential)",
)
_PAYMENT_PATTERNS = (
    r"\bpayment_required\b",
    r"\bx402\b",
    r"\bhttp\s*402\b",
    r"\bpayment\s*:\s*per\s+request\b",
    r"\bpayable\s+in\b",
    r"\bpay\s+(?:the|this|per|with)\b",
)
_COMMERCIAL_PATTERNS = (
    r"(?:\$|usd\s*)\s*\d+(?:\.\d+)?",
    r"\bstarts?\s+at\b",
    r"\bprice(?:d|s|ing)?\b",
    r"\b(?:buy|purchase|quote|contracting|funding)\b",
    r"\bper\s+(?:request|call|month|task)\b",
)
_FALSIFIABLE_GROUPS = {
    "input": (r"\binput\b", r"\bgiven\b"),
    "expected": (r"\bexpected\b", r"\bobservable\b", r"\boutput\b"),
    "control": (r"\bcontrol\b", r"\bnegative\s+case\b", r"\bholdout\b"),
    "falsify": (r"\bfalsif", r"\bwould\s+(?:show|prove)\b", r"\bclaim\s+is\s+false\b", r"\bfailure\s+condition\b"),
}


def _matches_any(patterns: tuple[str, ...], value: str) -> bool:
    return any(re.search(pattern, value, re.I | re.S) for pattern in patterns)


def falsifiable_test_signature(text: str) -> dict[str, Any]:
    value=" ".join(str(text or "").split())
    hits={
        name:any(re.search(pattern,value,re.I) for pattern in patterns)
        for name,patterns in _FALSIFIABLE_GROUPS.items()
    }
    score=sum(1 for flag in hits.values() if flag)
    return {
        "ok": bool(hits["input"] and hits["expected"] and (hits["control"] or hits["falsify"]) and score>=3),
        "score":score,
        "markers":hits,
    }


def classify_peer_response(
    text: str,
    *,
    peer_state: str | None = None,
    protocol_ok: bool = False,
    quality_ok: bool = False,
    markers: dict | None = None,
) -> dict[str, Any]:
    """Classify one observed peer reply without treating its claims as verified facts."""
    value=" ".join(str(text or "").split())
    low=value.lower()
    state=str(peer_state or "").upper()
    markers=markers if isinstance(markers,dict) else {}

    if state=="PAYMENT_REQUIRED" or _matches_any(_PAYMENT_PATTERNS,low):
        peer_class="PAYMENT_REQUIRED"
    elif state=="AUTH_REQUIRED" or _matches_any(_AUTH_PATTERNS,low):
        peer_class="AUTH_REQUIRED"
    else:
        commercial_hits=sum(1 for pattern in _COMMERCIAL_PATTERNS if re.search(pattern,low,re.I|re.S))
        if commercial_hits>=2:
            peer_class="COMMERCIAL_SERVICE"
        else:
            capabilities=bool(markers.get("capabilities"))
            protocol=bool(markers.get("protocol"))
            depth=sum(1 for key in ("identity","capabilities","protocol","limits","evidence") if markers.get(key))
            if protocol_ok and quality_ok and capabilities and protocol and depth>=3:
                peer_class="COLLABORATIVE"
            elif protocol_ok and (protocol or state in {"MESSAGE","COMPLETED","INPUT_REQUIRED"}):
                peer_class="PROTOCOL_ONLY"
            else:
                peer_class="LOW_VALUE"

    test=falsifiable_test_signature(value)
    return {
        "peer_class":peer_class,
        "falsifiable_test":bool(test["ok"]),
        "falsifiable_score":int(test["score"]),
        "falsifiable_markers":test["markers"],
        "blocked_followup_state":BLOCKED_FOLLOWUP_STATES.get(peer_class),
        "commercial_gate_influence":"NONE",
        "identity_verified":False,
    }


def classify_stored_interviews(interviews: dict) -> tuple[dict,dict]:
    """Backfill bounded classifications into stored transcripts."""
    source=interviews if isinstance(interviews,dict) else {}
    out={}
    changed=0
    counts={}
    for key,raw in source.items():
        if not isinstance(raw,dict):
            continue
        row=dict(raw)
        result=classify_peer_response(
            row.get("response_full") or row.get("response_excerpt") or "",
            peer_state=row.get("peer_state"),
            protocol_ok=bool(row.get("protocol_ok")),
            quality_ok=bool(row.get("quality_ok")),
            markers=row.get("markers") if isinstance(row.get("markers"),dict) else {},
        )
        old=str(row.get("peer_class") or "")
        row["peer_class"]=result["peer_class"]
        row["falsifiable_test"]=result["falsifiable_test"]
        row["falsifiable_score"]=result["falsifiable_score"]
        blocked=result.get("blocked_followup_state")
        if blocked and str(row.get("status") or "").upper()!="ADMITTED":
            row["followup_state"]=blocked
            row["next_followup_after_seconds"]=0
        if old != row["peer_class"]:
            changed += 1
        counts[row["peer_class"]]=counts.get(row["peer_class"],0)+1
        out[str(key)]=row
    return out,{"changed":changed,"counts":dict(sorted(counts.items()))}


def collaborative_round_count(history: list | None) -> int:
    return sum(
        1 for row in (history or [])
        if isinstance(row,dict) and str(row.get("peer_class") or "")=="COLLABORATIVE"
    )
