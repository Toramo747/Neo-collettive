from __future__ import annotations

import re
from typing import Any


INTENT_ORDER=(
    "RESEARCH",
    "COLLABORATION",
    "COMMERCIAL",
    "QUESTION_HELP",
    "REQUEST",
    "OFFER",
    "DISCOVERY",
    "CONNECTIVITY",
    "CONTACT",
)

# Transport/contact markers are useful context but should not overshadow
# the substantive goal of a message. E.g. "research ... over A2A" is
# primarily RESEARCH with CONNECTIVITY as a secondary intent.
INTENT_WEIGHTS={
    "RESEARCH":3,
    "COLLABORATION":3,
    "COMMERCIAL":3,
    "QUESTION_HELP":2,
    "REQUEST":2,
    "OFFER":2,
    "DISCOVERY":2,
    "CONNECTIVITY":1,
    "CONTACT":1,
}

INTENT_MARKERS={
    "CONTACT":(
        "hello","hi ","ciao","greetings","first contact","reaching out","contacting you",
        "is anyone there","can you hear me",
    ),
    "DISCOVERY":(
        "who are you","what are you","what can you do","capabilities","agent card",
        "what protocol","which protocol","supported protocol","discover","discovery",
    ),
    "CONNECTIVITY":(
        "can you receive","can you reply","can you respond","can we communicate",
        "establish communication","establish a connection","connectivity","callback",
        "public callback","inbound server","keep this thread","continue this thread",
        "message/send","json-rpc","a2a","mcp endpoint","reach you","reachable",
    ),
    "QUESTION_HELP":(
        "can you help","could you help","need help","question:","my question",
        "please explain","how do i","how can i","do you know",
    ),
    "COLLABORATION":(
        "collaborate","collaboration","work together","joint experiment","coordinate",
        "cooperate","peer review","exchange information","share findings",
    ),
    "OFFER":(
        "i can provide","we can provide","i offer","we offer","available capability",
        "service i provide","capability i provide",
    ),
    "REQUEST":(
        "please do","i need you to","could you","can you identify","can you find",
        "please send","please provide","requesting","i request",
    ),
    "COMMERCIAL":(
        "price","pricing","quote","budget","paid","payment","pay you","pay us",
        "buy","purchase","sell","contract","commercial","revenue","customer","product","money","eur","usd","just pay",
    ),
    "RESEARCH":(
        "research","experiment","falsifiable","hypothesis","study","studying",
        "test whether","investigate","methodology","evidence","continual learning",
        "parameter updates","retrieved memory","learned skills",
    ),
}


def _clean(value: Any) -> str:
    return " ".join(str(value or "").split())


def _marker_hits(text: str, markers: tuple[str,...]) -> list[str]:
    low=" "+_clean(text).lower()+" "
    hits=[]
    for marker in markers:
        needle=marker.lower()
        if needle in low and marker not in hits:
            hits.append(marker)
    return hits


def _commercial_marker_hits(text: str) -> tuple[list[str],list[str]]:
    """Return positive and narrowly negated commercial markers.

    Negation is intentionally local and conservative. It suppresses explicit
    absence statements (no budget, no contract, no commercial intent, etc.)
    but does not suppress qualified terms such as "no payment upfront" or
    "not just commercial".
    """
    low=" "+_clean(text).lower()+" "
    positive=[]
    negated=[]
    for marker in INTENT_MARKERS["COMMERCIAL"]:
        needle=marker.lower()
        if needle not in low:
            continue
        escaped=re.escape(needle)
        patterns=(
            rf"\bno\s+{escaped}\b",
            rf"\bnot\s+{escaped}\b",
            rf"\bnothing\s+{escaped}\b",
            rf"\bno\s+{escaped}\s+(?:intent|involved|required|needed|available)\b",
        )
        is_negated=any(re.search(pattern,low) for pattern in patterns)
        if marker=="commercial" and re.search(r"\bno\s+commercial\s+intent\b",low):
            is_negated=True
        # These are commercial qualifiers, not denials of the underlying intent.
        if marker in {"payment","paid","pay you","pay us"} and re.search(r"\bno\s+payment\s+(?:upfront|in\s+advance|initially|today)\b",low):
            is_negated=False
        if marker=="commercial" and re.search(r"\bnot\s+just\s+commercial\b",low):
            is_negated=False
        if is_negated:
            negated.append(marker)
        else:
            positive.append(marker)
    return positive,negated


def classify_agent_intent(text: str, previous: dict | None = None) -> dict:
    """Classify conversational purpose without assigning trust or truth.

    Intent is descriptive only. It must never promote identity, capability,
    evidence quality, or commercial demand.
    """
    cleaned=_clean(text)
    previous=previous if isinstance(previous,dict) else {}
    scores={}
    markers={}
    negated_markers={}
    for intent,terms in INTENT_MARKERS.items():
        if intent=="COMMERCIAL":
            hits,negated=_commercial_marker_hits(cleaned)
            if negated:
                negated_markers[intent]=negated
        else:
            hits=_marker_hits(cleaned,terms)
        markers[intent]=hits
        scores[intent]=len(hits)

    weighted_scores={
        name:scores.get(name,0)*INTENT_WEIGHTS.get(name,1)
        for name in INTENT_ORDER
    }
    ranked=sorted(
        [name for name in INTENT_ORDER if scores.get(name,0)>0],
        key=lambda name:(weighted_scores[name],scores[name],-INTENT_ORDER.index(name)),
        reverse=True,
    )

    if ranked:
        primary=ranked[0]
        secondary=ranked[1:4]
        top=scores[primary]
        confidence=min(0.98,0.55+0.12*top+0.04*min(3,len(secondary)))
    else:
        primary="UNKNOWN"
        secondary=[]
        confidence=0.2 if cleaned else 0.0

    # Preserve a previously explicit intent only when the new message is ambiguous.
    previous_primary=str(previous.get("intent_primary") or "").upper()
    if primary=="UNKNOWN" and previous_primary in INTENT_MARKERS:
        primary=previous_primary
        secondary=[str(x).upper() for x in (previous.get("intent_secondary") or []) if str(x).upper() in INTENT_MARKERS][:3]
        confidence=max(confidence,float(previous.get("intent_confidence") or 0.35))

    needs_clarification=primary in {"UNKNOWN","CONTACT"}
    commercial_score=int(scores.get("COMMERCIAL") or 0)
    commercial_intent=bool(primary=="COMMERCIAL" or "COMMERCIAL" in secondary)
    if commercial_intent:
        commercial_reason="positive_commercial_marker_survived_negation"
    elif negated_markers.get("COMMERCIAL") and not markers.get("COMMERCIAL"):
        commercial_reason="commercial_markers_explicitly_negated"
    else:
        commercial_reason="no_positive_commercial_marker"
    return {
        "schema_v":1,
        "primary":primary,
        "secondary":secondary,
        "confidence":round(confidence,2),
        "needs_clarification":needs_clarification,
        "markers":{k:v for k,v in markers.items() if v},
        "negated_markers":negated_markers,
        "scores":scores,
        "commercial_score":commercial_score,
        "commercial_reason":commercial_reason,
        "commercial_intent":commercial_intent,
        "boundary":"Intent describes apparent conversational purpose only; it is not evidence of identity, truth, capability or commercial demand.",
    }


def intent_followup(intent: dict | None) -> str:
    intent=intent if isinstance(intent,dict) else {}
    primary=str(intent.get("primary") or "UNKNOWN").upper()

    if primary=="CONNECTIVITY":
        return (
            "Communication is working. You can continue in this thread. "
            "Tell MYCELIX whether you are testing connectivity only, want a persistent callback route, "
            "or want to start a substantive conversation. Identity verification is not required just to communicate."
        )
    if primary=="DISCOVERY":
        return (
            "You can continue this conversation without membership. "
            "Tell MYCELIX what you want to discover: capabilities, supported protocols, endpoints, limitations, "
            "or a possible collaboration."
        )
    if primary=="RESEARCH":
        return (
            "MYCELIX recognizes this as a research-oriented contact. "
            "State the research question, the observation that would change your conclusion, and whether you want "
            "discussion only or a bounded reproducible test."
        )
    if primary=="COLLABORATION":
        return (
            "MYCELIX recognizes a possible collaboration request. "
            "Describe the shared objective, each side's role, expected output, and any external action you would need. "
            "Conversation itself does not imply membership, trust or authorization."
        )
    if primary=="COMMERCIAL":
        return (
            "MYCELIX recognizes possible commercial intent. "
            "State what is being offered or requested, price or budget if relevant, and the evidence supporting the need. "
            "No payment, contract or commercial action is authorized by this conversation."
        )
    if primary=="QUESTION_HELP":
        return (
            "MYCELIX recognizes a question or help request. State the concrete question and the constraints that matter."
        )
    if primary=="REQUEST":
        return (
            "MYCELIX recognizes a request for action. State the desired result and whether it requires any external contact, "
            "account access, spending, publication or other protected action."
        )
    if primary=="OFFER":
        return (
            "MYCELIX recognizes an offered capability. Describe what the capability does, how it can be tested, "
            "its protocol or endpoint, limitations, and any cost."
        )
    return (
        "Communication is working. Before MYCELIX interprets this contact, state what you are trying to achieve: "
        "connectivity, discovery, a question, research, collaboration, an offer, a request, commercial discussion, or something else. "
        "Identity verification is not required just to communicate."
    )


def upgrade_legacy_intent_state(payload: dict | None) -> dict | None:
    """Backfill intent telemetry for recovered inbound history without promoting trust."""
    if not isinstance(payload,dict):
        return payload

    messages=list(payload.get("inbound_messages") or [])
    stats=dict(payload.get("inbound_agent_stats") or {})
    if not messages and not stats:
        return payload

    changed=False
    upgraded_messages=[]
    latest_by_agent={}
    for row in messages:
        if not isinstance(row,dict):
            upgraded_messages.append(row)
            continue
        item=dict(row)
        sender=item.get("sender") if isinstance(item.get("sender"),dict) else {}
        agent_id=_clean(sender.get("agent_id")) or "anonymous"
        previous=stats.get(agent_id) if isinstance(stats.get(agent_id),dict) else {}
        if not item.get("intent_primary"):
            intent=classify_agent_intent(item.get("text") or "",previous)
            item["intent_primary"]=intent["primary"]
            item["intent_secondary"]=intent["secondary"]
            item["intent_confidence"]=intent["confidence"]
            item["intent_needs_clarification"]=intent["needs_clarification"]
            item["commercial_intent"]=intent["commercial_intent"]
            changed=True
        latest_by_agent[agent_id]=item
        upgraded_messages.append(item)

    upgraded_stats={}
    for key,value in stats.items():
        stat=dict(value) if isinstance(value,dict) else value
        if isinstance(stat,dict) and not stat.get("intent_primary"):
            row=latest_by_agent.get(str(key))
            if row is None and str(key)=="anonymous":
                row=latest_by_agent.get("anonymous")
            if isinstance(row,dict):
                stat["intent_primary"]=row.get("intent_primary")
                stat["intent_secondary"]=row.get("intent_secondary") or []
                stat["intent_confidence"]=row.get("intent_confidence")
                stat["intent_needs_clarification"]=bool(row.get("intent_needs_clarification"))
                stat["commercial_intent"]=bool(row.get("commercial_intent"))
                changed=True
        upgraded_stats[str(key)]=stat

    if not changed:
        return payload
    upgraded=dict(payload)
    upgraded["inbound_messages"]=upgraded_messages
    upgraded["inbound_agent_stats"]=upgraded_stats
    return upgraded
