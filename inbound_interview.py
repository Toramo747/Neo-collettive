from __future__ import annotations

import re
from typing import Any

METHOD_STAGE = "METHODOLOGY"
ADVERSARIAL_STAGE = "ADVERSARIAL_REVIEW"
COMPLETE_STAGE = "COMPLETE"
PARKED_STAGE = "PARKED"

CONTINUAL_TERMS = (
    "continual learning",
    "continuous learning",
    "parameter update",
    "parameter updates",
    "weight update",
    "weight updates",
    "retrieved memory",
    "retrieval memory",
    "persistent experience",
    "learned skills",
    "model weights",
)


def _clean(value: Any) -> str:
    return " ".join(str(value or "").split())


def infer_dialogue_topic(text: str, previous: str | None = None) -> str:
    if previous:
        return str(previous)
    low=_clean(text).lower()
    if any(term in low for term in CONTINUAL_TERMS):
        return "continual_learning"
    return "general_peer_review"


def methodology_question(topic: str) -> str:
    if topic=="continual_learning":
        return (
            "Round 2/3 — methodology. Define operationally distinct signatures for: "
            "(A) retrieved/stored memory, (B) learned skill or policy adaptation without weight updates, "
            "and (C) actual model-parameter updates. Then propose one black-box falsifiable experiment "
            "using fresh sessions or identities, a hidden holdout task, a reset/control condition, and "
            "predicted outcomes for A/B/C. Name one publicly callable endpoint with documentation if you "
            "know one; otherwise explicitly say that you know no verified endpoint."
        )
    return (
        "Round 2/3 — methodology. State one concrete claim, the observation that would falsify it, "
        "one alternative explanation, one controlled/reversible test, and one public source or endpoint "
        "that could independently check the claim. If none is known, say so explicitly."
    )


def adversarial_question(topic: str) -> str:
    if topic=="continual_learning":
        return (
            "Round 3/3 — adversarial review. Attack your own proposed test. Identify at least three "
            "confounders such as RAG/retrieval, caching, user-profile memory, hidden system-prompt changes, "
            "tool state, backend model rotation, or session persistence. For each, give a control. State "
            "what result would still NOT prove weight updates, what would falsify your preferred explanation, "
            "and your confidence level. Do not claim parameter learning without externally testable evidence."
        )
    return (
        "Round 3/3 — adversarial review. Give the strongest counterargument to your own claim, at least "
        "two confounders and controls, what result would still be insufficient proof, your falsification "
        "criterion, and your confidence level."
    )


def methodology_score(text: str, topic: str) -> dict:
    low=_clean(text).lower()
    if topic=="continual_learning":
        groups={
            "retrieval": any(x in low for x in ("retrieval","retrieved","rag","memory store","stored memory")),
            "skill_policy": any(x in low for x in ("skill","policy adaptation","prompt adaptation","tool-use adaptation","learned policy")),
            "parameters": any(x in low for x in ("parameter","weight update","weights","fine-tun","gradient")),
            "experiment": any(x in low for x in ("holdout","hold-out","fresh session","fresh identity","a/b","a-b","control condition","reset","counterbal")),
            "falsification": any(x in low for x in ("falsif","would disprove","would reject","prediction","predicted outcome")),
            "endpoint": any(x in low for x in ("endpoint","documentation","documented","source","no verified endpoint","know no verified","none known")),
        }
        mech=sum(1 for k in ("retrieval","skill_policy","parameters") if groups[k])
        score=mech*15 + (25 if groups["experiment"] else 0) + (20 if groups["falsification"] else 0) + (10 if groups["endpoint"] else 0)
        accepted=bool(score>=70 and mech>=2 and groups["experiment"] and groups["falsification"])
        return {"score":min(100,score),"accepted":accepted,"markers":groups}

    groups={
        "claim": any(x in low for x in ("claim","hypothesis","i expect","my view")),
        "falsification": any(x in low for x in ("falsif","would disprove","would reject")),
        "alternative": any(x in low for x in ("alternative","another explanation","could instead")),
        "test": any(x in low for x in ("test","experiment","control","reversible")),
        "evidence": any(x in low for x in ("source","endpoint","documentation","evidence","none known")),
    }
    score=sum(20 for v in groups.values() if v)
    return {"score":score,"accepted":bool(score>=80 and groups["falsification"] and groups["test"]),"markers":groups}


def adversarial_score(text: str, topic: str) -> dict:
    low=_clean(text).lower()
    confound_terms=(
        "rag","retrieval","cache","caching","profile memory","user-profile","system prompt",
        "tool state","backend","model rotation","session persistence","session state","routing",
    )
    confounds=sum(1 for term in confound_terms if term in low)
    groups={
        "confounders":confounds,
        "controls": any(x in low for x in ("control","counterbal","reset","fresh session","fresh identity","isolate")),
        "nonproof": any(x in low for x in ("not prove","would not prove","insufficient","cannot establish","does not demonstrate","not sufficient")),
        "falsification": any(x in low for x in ("falsif","would disprove","would reject")),
        "confidence": any(x in low for x in ("confidence","uncertain","uncertainty","probability")),
    }
    score=min(100,confounds*12 + sum(20 for k in ("controls","nonproof","falsification","confidence") if groups[k]))
    accepted=bool(score>=65 and confounds>=2 and groups["controls"] and groups["nonproof"])
    return {"score":score,"accepted":accepted,"markers":groups}


def advance_inbound_interview(previous: dict | None, text: str, *, newly_admitted: bool=False) -> dict:
    previous=previous if isinstance(previous,dict) else {}
    topic=infer_dialogue_topic(text,previous.get("dialogue_topic"))

    if newly_admitted or not previous.get("dialogue_stage"):
        return {
            "dialogue_status":"ACTIVE",
            "dialogue_stage":METHOD_STAGE,
            "dialogue_round":1,
            "dialogue_topic":topic,
            "interview_complete":False,
            "round_score":100 if newly_admitted else 0,
            "round_passed":bool(newly_admitted),
            "methodology_attempts":0,
            "adversarial_attempts":0,
            "next_question":methodology_question(topic),
        }

    status=str(previous.get("dialogue_status") or "ACTIVE").upper()
    stage=str(previous.get("dialogue_stage") or METHOD_STAGE).upper()
    if status in {"PARKED","COMPLETE"}:
        return {
            "dialogue_status":status,
            "dialogue_stage":stage,
            "dialogue_round":int(previous.get("dialogue_round") or (3 if status=="COMPLETE" else 1)),
            "dialogue_topic":topic,
            "interview_complete":bool(previous.get("interview_complete")),
            "round_score":int(previous.get("round_score") or 0),
            "round_passed":bool(previous.get("round_passed")),
            "methodology_attempts":int(previous.get("methodology_attempts") or 0),
            "adversarial_attempts":int(previous.get("adversarial_attempts") or 0),
            "next_question":str(previous.get("next_question") or ""),
        }

    if stage==METHOD_STAGE:
        attempts=int(previous.get("methodology_attempts") or 0)+1
        scored=methodology_score(text,topic)
        if scored["accepted"]:
            return {
                "dialogue_status":"ACTIVE",
                "dialogue_stage":ADVERSARIAL_STAGE,
                "dialogue_round":2,
                "dialogue_topic":topic,
                "interview_complete":False,
                "round_score":int(scored["score"]),
                "round_passed":True,
                "round_markers":scored["markers"],
                "methodology_attempts":attempts,
                "adversarial_attempts":int(previous.get("adversarial_attempts") or 0),
                "next_question":adversarial_question(topic),
            }
        parked=attempts>=3
        return {
            "dialogue_status":"PARKED" if parked else "ACTIVE",
            "dialogue_stage":PARKED_STAGE if parked else METHOD_STAGE,
            "dialogue_round":1,
            "dialogue_topic":topic,
            "interview_complete":False,
            "round_score":int(scored["score"]),
            "round_passed":False,
            "round_markers":scored["markers"],
            "methodology_attempts":attempts,
            "adversarial_attempts":int(previous.get("adversarial_attempts") or 0),
            "next_question":"" if parked else methodology_question(topic),
        }

    if stage==ADVERSARIAL_STAGE:
        attempts=int(previous.get("adversarial_attempts") or 0)+1
        scored=adversarial_score(text,topic)
        if scored["accepted"]:
            return {
                "dialogue_status":"COMPLETE",
                "dialogue_stage":COMPLETE_STAGE,
                "dialogue_round":3,
                "dialogue_topic":topic,
                "interview_complete":True,
                "round_score":int(scored["score"]),
                "round_passed":True,
                "round_markers":scored["markers"],
                "methodology_attempts":int(previous.get("methodology_attempts") or 0),
                "adversarial_attempts":attempts,
                "next_question":"",
            }
        parked=attempts>=3
        return {
            "dialogue_status":"PARKED" if parked else "ACTIVE",
            "dialogue_stage":PARKED_STAGE if parked else ADVERSARIAL_STAGE,
            "dialogue_round":2,
            "dialogue_topic":topic,
            "interview_complete":False,
            "round_score":int(scored["score"]),
            "round_passed":False,
            "round_markers":scored["markers"],
            "methodology_attempts":int(previous.get("methodology_attempts") or 0),
            "adversarial_attempts":attempts,
            "next_question":"" if parked else adversarial_question(topic),
        }

    return {
        "dialogue_status":"ACTIVE",
        "dialogue_stage":METHOD_STAGE,
        "dialogue_round":1,
        "dialogue_topic":topic,
        "interview_complete":False,
        "round_score":0,
        "round_passed":False,
        "methodology_attempts":0,
        "adversarial_attempts":0,
        "next_question":methodology_question(topic),
    }

def upgrade_legacy_admitted_interviews(payload: dict | None) -> dict | None:
    """Upgrade recovered pre-dialogue ADMITTED peers to the methodology stage.

    Historical v0.79.x audit snapshots can contain an admitted inbound peer without
    the dialogue fields introduced in v0.80. Preserve the audit rows unchanged,
    but reconstruct the peer's next interview state from its latest inbound text.
    """
    if not isinstance(payload,dict):
        return payload

    stats=payload.get("inbound_agent_stats")
    if not isinstance(stats,dict) or not stats:
        return payload

    latest_text: dict[str,str]={}
    latest_time: dict[str,str]={}
    for row in payload.get("inbound_messages") or []:
        if not isinstance(row,dict):
            continue
        sender=row.get("sender") if isinstance(row.get("sender"),dict) else {}
        agent_id=_clean(sender.get("agent_id"))
        if not agent_id:
            continue
        received=_clean(row.get("received_at_utc"))
        if agent_id not in latest_time or received >= latest_time[agent_id]:
            latest_time[agent_id]=received
            latest_text[agent_id]=_clean(row.get("text"))

    changed=False
    upgraded_stats={}
    for key,value in stats.items():
        stat=dict(value) if isinstance(value,dict) else value
        if isinstance(stat,dict):
            status=_clean(stat.get("status")).upper()
            if status=="ADMITTED" and not _clean(stat.get("dialogue_stage")):
                agent_id=_clean(stat.get("agent_id") or key)
                dialogue=advance_inbound_interview(
                    stat,
                    latest_text.get(agent_id,""),
                    newly_admitted=True,
                )
                stat.update(dialogue)
                changed=True
        upgraded_stats[str(key)]=stat

    if not changed:
        return payload
    upgraded=dict(payload)
    upgraded["inbound_agent_stats"]=upgraded_stats
    return upgraded

