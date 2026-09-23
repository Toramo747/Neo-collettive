from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse


def _clean(value: Any) -> str:
    return " ".join(str(value or "").split())


def _https_url(value: Any) -> str:
    text=_clean(value)
    if not text:
        return ""
    try:
        p=urlparse(text)
        if p.scheme=="https" and p.hostname:
            return text[:500]
    except Exception:
        pass
    return ""


def _extract_sources(payload: dict) -> list[str]:
    raw=payload.get("sources") or []
    if isinstance(raw,str):
        raw=[raw]
    out=[]
    if isinstance(raw,list):
        for item in raw[:20]:
            url=_https_url(item if not isinstance(item,dict) else item.get("url"))
            if url and url not in out:
                out.append(url)
    return out


def evaluate_agent_trust(payload: dict) -> dict:
    """Deterministic bounded trust/evidence assessment.

    This is not an identity authority and never certifies an agent. It separates
    identity evidence, declared capabilities and claim support so downstream
    systems can make an explicit allow/park/reject decision.
    """
    payload=payload if isinstance(payload,dict) else {}
    agent=payload.get("agent") if isinstance(payload.get("agent"),dict) else {}
    message=_clean(payload.get("message") or payload.get("claim"))
    sources=_extract_sources(payload)
    card=_https_url(agent.get("agent_card_url") or payload.get("agent_card_url"))
    agent_id=_clean(agent.get("agent_id") or payload.get("agent_id"))
    identity_verified=bool(payload.get("identity_verified"))
    card_signed=bool(agent.get("card_signature_verified") or payload.get("card_signature_verified"))
    interview=payload.get("interview") if isinstance(payload.get("interview"),dict) else {}

    declared=bool(agent_id)
    interview_complete=bool(interview.get("complete") or interview.get("interview_complete"))
    interview_score=max(0,min(100,int(interview.get("score") or interview.get("round_score") or 0)))

    identity_status=(
        "verified"
        if identity_verified
        else "signed_card"
        if card and card_signed
        else "self_declared"
        if declared
        else "anonymous"
    )

    low=message.lower()
    inference_markers=(
        "therefore","this proves","must mean","clearly","obviously","will pay",
        "guarantee","certainly","definitely","we can conclude",
    )
    support_markers=(
        "according to","source","evidence","documentation","documented","measured",
        "observed","reported","data show","data shows",
    )
    falsification_markers=("falsif","would disprove","would reject","control","counterexample")

    unsupported_inference=bool(message and any(x in low for x in inference_markers) and not sources)
    explicit_support=bool(sources or any(x in low for x in support_markers))
    falsifiable=bool(any(x in low for x in falsification_markers))

    identity_points={
        "anonymous":0,
        "self_declared":15,
        "signed_card":30,
        "verified":40,
    }[identity_status]
    capability_points=0
    if interview_complete:
        capability_points=25
    elif interview_score>=65:
        capability_points=15
    elif interview_score>0:
        capability_points=5

    evidence_points=min(25,len(sources)*8)
    if explicit_support and not sources:
        evidence_points=max(evidence_points,5)
    if falsifiable:
        evidence_points=min(25,evidence_points+5)

    penalty=25 if unsupported_inference else 0
    score=max(0,min(100,identity_points+capability_points+evidence_points-penalty))

    reasons=[]
    if identity_status=="anonymous":
        reasons.append("agent_identity_missing")
    elif identity_status=="self_declared":
        reasons.append("identity_is_self_declared")
    if not card:
        reasons.append("agent_card_missing")
    elif not card_signed:
        reasons.append("agent_card_signature_unverified")
    if not interview_complete:
        reasons.append("capability_interview_incomplete")
    if message and not explicit_support:
        reasons.append("claim_has_no_explicit_support")
    if unsupported_inference:
        reasons.append("unsupported_inference_detected")
    if message and not falsifiable:
        reasons.append("falsification_condition_missing")

    if identity_status=="anonymous" or unsupported_inference:
        decision="PARK"
    elif score>=70 and interview_complete and explicit_support:
        decision="ALLOW_BOUNDED"
    elif score>=35:
        decision="PARK"
    else:
        decision="REJECT"

    source_fact=message[:1200] if message and explicit_support else ""
    inference=""
    if message and not explicit_support:
        inference=message[:1200]

    return {
        "schema_v":1,
        "decision":decision,
        "trust_score":score,
        "identity":{
            "status":identity_status,
            "agent_id":agent_id,
            "agent_card_url":card,
            "card_signature_verified":card_signed,
        },
        "capability":{
            "interview_complete":interview_complete,
            "interview_score":interview_score,
        },
        "evidence":{
            "source_urls":sources,
            "source_fact":source_fact,
            "inference":inference,
            "unsupported_inference":unsupported_inference,
            "falsifiable":falsifiable,
        },
        "reasons":reasons,
        "boundary":"This result is a bounded policy signal, not proof of identity, truth, safety or commercial demand.",
    }
