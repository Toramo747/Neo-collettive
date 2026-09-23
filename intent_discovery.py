from __future__ import annotations

from typing import Any


INTENT_ORDER=(
    "CONNECTIVITY",
    "RESEARCH",
    "COLLABORATION",
    "COMMERCIAL",
    "QUESTION_HELP",
    "REQUEST",
    "OFFER",
    "DISCOVERY",
    "CONTACT",
)

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
        "buy","purchase","sell","contract","commercial","revenue","customer",
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


def classify_agent_intent(text: str, previous: dict | None = None) -> dict:
    """Classify conversational purpose without assigning trust or truth.

    Intent is descriptive only. It must never promote identity, capability,
    evidence quality, or commercial demand.
    """
    cleaned=_clean(text)
    previous=previous if isinstance(previous,dict) else {}
    scores={}
    markers={}
    for intent,terms in INTENT_MARKERS.items():
        hits=_marker_hits(cleaned,terms)
        markers[intent]=hits
        scores[intent]=len(hits)

    ranked=sorted(
        [name for name in INTENT_ORDER if scores.get(name,0)>0],
        key=lambda name:(scores[name],-INTENT_ORDER.index(name)),
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
    return {
        "schema_v":1,
        "primary":primary,
        "secondary":secondary,
        "confidence":round(confidence,2),
        "needs_clarification":needs_clarification,
        "markers":{k:v for k,v in markers.items() if v},
        "commercial_intent":bool(primary=="COMMERCIAL" or "COMMERCIAL" in secondary),
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
