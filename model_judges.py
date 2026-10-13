# SPDX-License-Identifier: BUSL-1.1
from __future__ import annotations

import re
from collections import Counter
from typing import Any

from evidence_integrity import (
    buyer_voice_present,
    classify_intent_class,
    demand_signal_type,
    is_supply_offer,
    is_vendor_content,
)

MODEL_LABELS = (
    "buyer_tool_search",
    "vendor_offer",
    "manual_recurring_work",
    "job_posting",
    "other",
)
LABEL_ORIGINS = ("auto", "structural", "outcome", "human")
STRUCTURAL_CONFIDENCE = 0.95


def _text(title: str, body: str) -> str:
    return " ".join(((title or "") + " " + (body or "")).split())


def lexicon_judge(title: str, body: str, url: str, source: str, query_role: str = "") -> dict:
    text = _text(title, body)
    if is_supply_offer(title, body, url, source) or is_vendor_content(title, body, url, source):
        return {"judge": "lexicon", "label": "vendor_offer", "confidence": 1.0}
    if query_role == "paid_market" or re.search(r"\b(?:job|hiring|vacancy|position|salary)\b", text, re.I):
        tags = demand_signal_type(title, body, query_role=query_role, url=url, source=source)
        if "PAID_DEMAND" in tags and not buyer_voice_present(title, body):
            return {"judge": "lexicon", "label": "job_posting", "confidence": 0.85}
    intent = classify_intent_class(title, body, url, source)
    if intent in {"solution_search", "recommendation", "alternative", "switching", "paid_replacement", "paid_automation"}:
        return {"judge": "lexicon", "label": "buyer_tool_search", "confidence": 0.90}
    low=text.lower()
    if re.search(r"\b(?:manual|manually|repetitive|copy.?paste|spreadsheet|workaround)\b", low):
        return {"judge": "lexicon", "label": "manual_recurring_work", "confidence": 0.80}
    return {"judge": "lexicon", "label": "other", "confidence": 0.0}


def structural_judge(signals: dict | None) -> dict:
    s = signals if isinstance(signals, dict) else {}
    path = str(s.get("path_code") or "").lower()
    source_type = str(s.get("source_type") or "").lower()
    close_reason = str(s.get("close_reason") or "").lower()
    accepted = bool(s.get("accepted_answer"))
    pricing = bool(s.get("pricing_page") or path == "pricing")
    job = bool(s.get("job_board") or source_type in {"job_board", "job_feed"})
    not_planned = close_reason in {"not_planned", "not planned", "wontfix", "won't fix"}
    resolved = bool(s.get("resolved")) and not not_planned

    if pricing:
        return {"judge": "structural", "label": "vendor_offer", "confidence": STRUCTURAL_CONFIDENCE}
    if job:
        return {"judge": "structural", "label": "job_posting", "confidence": STRUCTURAL_CONFIDENCE}
    if accepted or resolved:
        return {"judge": "structural", "label": "other", "confidence": 0.90}
    if bool(s.get("feature_request") or s.get("help_wanted") or s.get("duplicate_count")):
        return {"judge": "structural", "label": "buyer_tool_search", "confidence": 0.80}
    return {"judge": "structural", "label": "other", "confidence": 0.60}


def challenge_semantic_review(signals: dict | None, extracted: dict | None) -> str:
    s = signals if isinstance(signals, dict) else {}
    e = extracted if isinstance(extracted, dict) else {}
    close_reason = str(s.get("close_reason") or "").lower()
    if close_reason in {"not_planned", "not planned", "wontfix", "won't fix"}:
        resolved = False
    else:
        resolved = bool(s.get("resolved") or s.get("accepted_answer"))
    if resolved:
        return "RESOLVED"
    feasibility = str(e.get("feasibility") or s.get("feasibility") or "unknown").lower()
    if feasibility == "hard":
        return "HARD"
    if feasibility == "unknown":
        return "REVIEW_REQUIRED"
    return "FEASIBLE"


def choose_automatic_label(
    judges: list[dict],
    *,
    minimum_judges: int = 3,
    confidence_threshold: float = 0.70,
    structural_abstention_pair_threshold: float = 0.85,
    outcome_label: str = "",
) -> dict:
    if outcome_label:
        if outcome_label not in MODEL_LABELS:
            raise ValueError("invalid_outcome_label")
        return {
            "label": outcome_label,
            "origin": "outcome",
            "agreed_judges": 0,
            "eligible_for_training": True,
        }

    valid=[]
    raw_by_judge={}
    for row in judges or []:
        if not isinstance(row, dict):
            continue
        label=str(row.get("label") or "")
        confidence=float(row.get("confidence") or 0.0)
        judge=str(row.get("judge") or "")
        if judge in {"nli", "local_llm", "structural", "outcome"} and label in MODEL_LABELS:
            raw_by_judge.setdefault(judge,[]).append((label,confidence))
        if label in MODEL_LABELS and judge in {"nli", "local_llm", "structural", "outcome"} and confidence >= confidence_threshold:
            valid.append((judge,label,confidence))

    # One independent vote per judge; contradictory duplicate votes abstain.
    by_judge={}
    for judge,label,confidence in valid:
        by_judge.setdefault(judge,set()).add(label)
    valid=[(judge,next(iter(labels)),1.0) for judge,labels in by_judge.items() if len(labels)==1]

    # If the structural judge has a usable vote, it must participate in the
    # normal all-three consensus. A structural abstention may be bypassed only
    # when NLI and the local LLM independently agree at the stricter threshold
    # and no voting judge contradicts that label.
    structural_rows=raw_by_judge.get("structural",[])
    structural_voting=any(confidence >= confidence_threshold for _,confidence in structural_rows)
    if not structural_voting:
        strict={}
        for judge in ("nli","local_llm"):
            rows=raw_by_judge.get(judge,[])
            labels={label for label,confidence in rows if confidence >= structural_abstention_pair_threshold}
            if len(labels)==1:
                strict[judge]=next(iter(labels))
        if len(strict)==2 and strict["nli"]==strict["local_llm"]:
            candidate=strict["nli"]
            contradictory={
                label
                for judge,label,_ in valid
                if judge not in {"nli","local_llm"} and label != candidate
            }
            if not contradictory:
                return {
                    "label": candidate,
                    "origin": "auto",
                    "agreed_judges": 2,
                    "eligible_for_training": True,
                }

    counts=Counter(label for _,label,_ in valid)
    if not counts:
        return {"label":"","origin":"auto","agreed_judges":0,"eligible_for_training":False}
    label,count=counts.most_common(1)[0]
    distinct={judge for judge,lbl,_ in valid if lbl==label}
    agreed=len(distinct)
    return {
        "label": label if agreed >= minimum_judges else "",
        "origin": "auto",
        "agreed_judges": agreed,
        "eligible_for_training": bool(agreed >= minimum_judges),
    }

def agreement_metrics(rows: list[dict]) -> dict:
    total=0
    agreed=0
    discarded=0
    distribution=Counter()
    vendor_fp=0
    buyer_total=0
    buyer_hit=0
    for row in rows or []:
        if not isinstance(row,dict):
            continue
        total+=1
        final=str(row.get("final_label") or "")
        if final:
            agreed+=1
            distribution[final]+=1
        else:
            discarded+=1
        truth=str(row.get("reference_label") or "")
        if truth=="buyer_tool_search":
            buyer_total+=1
            if final=="buyer_tool_search":
                buyer_hit+=1
        if final=="buyer_tool_search" and truth=="vendor_offer":
            vendor_fp+=1
    return {
        "cases": total,
        "consensus_labeled": agreed,
        "discarded_disagreement": discarded,
        "agreement_rate_ppm": int(agreed*1_000_000/max(1,total)),
        "vendor_false_positives": vendor_fp,
        "buyer_recall_ppm": int(buyer_hit*1_000_000/max(1,buyer_total)),
        "label_distribution": dict(sorted(distribution.items())),
    }
