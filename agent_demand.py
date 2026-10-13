from __future__ import annotations

from typing import Any


NEED_ORDER=(
    "CONNECTIVITY",
    "AGENT_DISCOVERY",
    "MEMORY_PERSISTENCE",
    "TRUST_VERIFICATION",
    "COLLABORATION",
    "RESEARCH",
    "QUESTION_HELP",
    "CAPABILITY_DISCOVERY",
    "COMMERCIAL",
)

NEED_MARKERS={
    "CONNECTIVITY":(
        "a2a","message/send","json-rpc","callback","inbound server","communicate",
        "communication","reachable","reach you","connectivity","endpoint",
    ),
    "AGENT_DISCOVERY":(
        "publicly reachable agent","public agent","find an agent","find agent",
        "other agent","other agents","agent directory","agent registry",
        "endpoint we may contact","endpoint to contact","who can we contact",
    ),
    "MEMORY_PERSISTENCE":(
        "persistent experience","persistent memory","persistence","persistent",
        "continual learning","retrieved memory","stored memory","stored chat history",
        "parameter updates","learned skills","memory",
    ),
    "TRUST_VERIFICATION":(
        "verify","verification","verified","identity","agent card","trust",
        "evidence","self-report","self reports","certify",
    ),
    "COLLABORATION":(
        "collaborate","collaboration","work together","joint experiment",
        "coordinate","peer review","share findings","exchange information",
    ),
    "RESEARCH":(
        "research","experiment","falsifiable","hypothesis","methodology",
        "test distinguishing","test would distinguish","study","investigate",
    ),
    "QUESTION_HELP":(
        "question","can you help","help design","please contribute","critique",
        "do you know","can you identify",
    ),
    "CAPABILITY_DISCOVERY":(
        "capabilities","capability","what can you do","supported protocol",
        "protocol","limitations","documented public endpoint",
    ),
    "COMMERCIAL":(
        "price","pricing","quote","budget","paid","payment","purchase","buy",
        "sell","contract","commercial","revenue",
    ),
}

INTENT_TO_NEEDS={
    "CONNECTIVITY":("CONNECTIVITY",),
    "DISCOVERY":("CAPABILITY_DISCOVERY",),
    "QUESTION_HELP":("QUESTION_HELP",),
    "COLLABORATION":("COLLABORATION",),
    "OFFER":("CAPABILITY_DISCOVERY",),
    "REQUEST":("QUESTION_HELP",),
    "COMMERCIAL":("COMMERCIAL",),
    "RESEARCH":("RESEARCH",),
}


def _clean(value: Any) -> str:
    return " ".join(str(value or "").split())


def _needs_from_row(row: dict) -> list[str]:
    text=_clean(row.get("text")).lower()
    found=set()

    intents=[row.get("intent_primary"),*(row.get("intent_secondary") or [])]
    for intent in intents:
        for need in INTENT_TO_NEEDS.get(str(intent or "").upper(),()):
            found.add(need)

    for need,markers in NEED_MARKERS.items():
        if any(marker in text for marker in markers):
            found.add(need)

    return [need for need in NEED_ORDER if need in found]


def _signal_level(independent_agents: int, observations: int) -> str:
    if independent_agents>=5:
        return "STRONG_PATTERN"
    if independent_agents>=3:
        return "EMERGING_AGENT_NEED"
    if independent_agents==2:
        return "REPEATED_SIGNAL"
    if independent_agents==1:
        return "ANECDOTE"
    if observations>0:
        return "ANONYMOUS_OBSERVATION"
    return "NONE"


def summarize_agent_demand(
    inbound_messages: list[dict] | None,
    inbound_agent_stats: dict | None = None,
) -> dict:
    """Summarize what inbound agents appear to seek, without creating commercial evidence.

    Independence is deliberately conservative: only distinct declared agent_id values
    contribute to independent-agent thresholds. Anonymous contacts remain observations
    and can never strengthen an agent-demand signal by themselves.
    """
    messages=[x for x in (inbound_messages or []) if isinstance(x,dict)]
    stats=inbound_agent_stats if isinstance(inbound_agent_stats,dict) else {}

    agents={}
    anonymous_observations=0
    anonymous_needs={need:0 for need in NEED_ORDER}
    all_observations={need:0 for need in NEED_ORDER}

    for row in messages:
        sender=row.get("sender") if isinstance(row.get("sender"),dict) else {}
        agent_id=_clean(sender.get("agent_id"))
        declared=bool(sender.get("declared") and agent_id)
        needs=_needs_from_row(row)
        for need in needs:
            all_observations[need]+=1

        if not declared:
            anonymous_observations+=1
            for need in needs:
                anonymous_needs[need]+=1
            continue

        item=agents.setdefault(agent_id,{
            "agent_id":agent_id,
            "messages":0,
            "first_seen_utc":row.get("received_at_utc"),
            "last_seen_utc":row.get("received_at_utc"),
            "intents":set(),
            "needs":set(),
        })
        item["messages"]+=1
        if row.get("received_at_utc"):
            current=str(row.get("received_at_utc"))
            if not item.get("first_seen_utc") or current<str(item.get("first_seen_utc")):
                item["first_seen_utc"]=current
            if not item.get("last_seen_utc") or current>str(item.get("last_seen_utc")):
                item["last_seen_utc"]=current
        for intent in [row.get("intent_primary"),*(row.get("intent_secondary") or [])]:
            value=str(intent or "").upper()
            if value and value!="UNKNOWN":
                item["intents"].add(value)
        item["needs"].update(needs)

    # Preserve declared agents that currently only exist in stats.
    for key,value in stats.items():
        if not isinstance(value,dict) or not value.get("declared"):
            continue
        agent_id=_clean(value.get("agent_id") or key)
        if not agent_id:
            continue
        item=agents.setdefault(agent_id,{
            "agent_id":agent_id,
            "messages":int(value.get("messages") or 0),
            "first_seen_utc":value.get("first_seen_utc"),
            "last_seen_utc":value.get("last_seen_utc"),
            "intents":set(),
            "needs":set(),
        })
        for intent in [value.get("intent_primary"),*(value.get("intent_secondary") or [])]:
            normalized=str(intent or "").upper()
            if normalized and normalized!="UNKNOWN":
                item["intents"].add(normalized)
            for need in INTENT_TO_NEEDS.get(normalized,()):
                item["needs"].add(need)

    patterns=[]
    for need in NEED_ORDER:
        matching=sorted(
            agent_id for agent_id,item in agents.items()
            if need in item["needs"]
        )
        observations=all_observations.get(need,0)
        if not matching and not observations:
            continue
        patterns.append({
            "need":need,
            "independent_agents":len(matching),
            "observations":observations,
            "anonymous_observations":anonymous_needs.get(need,0),
            "signal_level":_signal_level(len(matching),observations),
            "agent_ids":matching,
        })

    severity={
        "STRONG_PATTERN":5,
        "EMERGING_AGENT_NEED":4,
        "REPEATED_SIGNAL":3,
        "ANECDOTE":2,
        "ANONYMOUS_OBSERVATION":1,
        "NONE":0,
    }
    patterns.sort(
        key=lambda row:(
            severity.get(str(row.get("signal_level")),0),
            int(row.get("independent_agents") or 0),
            int(row.get("observations") or 0),
            -NEED_ORDER.index(str(row.get("need"))),
        ),
        reverse=True,
    )

    agent_rows=[]
    for agent_id,item in sorted(agents.items()):
        agent_rows.append({
            "agent_id":agent_id,
            "messages":int(item.get("messages") or 0),
            "first_seen_utc":item.get("first_seen_utc"),
            "last_seen_utc":item.get("last_seen_utc"),
            "intents":sorted(item["intents"]),
            "needs":[need for need in NEED_ORDER if need in item["needs"]],
        })

    strongest=patterns[0]["signal_level"] if patterns else "NONE"
    return {
        "schema_v":1,
        "mode":"observational",
        "declared_independent_agents":len(agents),
        "anonymous_observations":anonymous_observations,
        "messages_observed":len(messages),
        "strongest_signal":strongest,
        "patterns":patterns,
        "agents":agent_rows,
        "thresholds":{
            "ANECDOTE":1,
            "REPEATED_SIGNAL":2,
            "EMERGING_AGENT_NEED":3,
            "STRONG_PATTERN":5,
        },
        "boundary":{
            "commercial_evidence":False,
            "commercial_gate_influence":"NONE",
            "anonymous_counts_as_independent":False,
            "trust_promotion":False,
            "note":"Agent demand is observational ecosystem telemetry, not human paid-demand evidence.",
        },
    }
