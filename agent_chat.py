from __future__ import annotations

from collections import defaultdict
from typing import Any


def _clean(value: Any) -> str:
    return " ".join(str(value or "").split())


def backfill_inbound_chat_events(
    inbound_messages: list[dict] | None,
    existing_events: list[dict] | None,
) -> list[dict]:
    """Ensure historical inbound messages are visible in chat monitoring.

    Outbound messages are never reconstructed: if they were not recorded when sent,
    the monitor must not invent them.
    """
    events=[dict(x) for x in (existing_events or []) if isinstance(x,dict)]
    known={
        ("INBOUND",str(x.get("message_id") or ""))
        for x in events
        if str(x.get("direction") or "").upper()=="INBOUND"
    }
    for row in inbound_messages or []:
        if not isinstance(row,dict):
            continue
        message_id=str(row.get("message_id") or "")
        key=("INBOUND",message_id)
        if message_id and key in known:
            continue
        sender=row.get("sender") if isinstance(row.get("sender"),dict) else {}
        events.append({
            "event_id":"legacy-in-"+(message_id or str(len(events)+1)),
            "message_id":message_id,
            "timestamp_utc":row.get("received_at_utc"),
            "thread_id":str(row.get("thread_id") or ""),
            "direction":"INBOUND",
            "agent_id":str(sender.get("agent_id") or ""),
            "agent":str(sender.get("agent") or "anonymous-agent"),
            "text":str(row.get("text") or ""),
            "intent_primary":row.get("intent_primary"),
            "intent_secondary":row.get("intent_secondary") or [],
            "admission_status":row.get("admission_status"),
            "dialogue_stage":row.get("dialogue_stage"),
            "historical_backfill":True,
        })
        if message_id:
            known.add(key)
    events.sort(key=lambda x:str(x.get("timestamp_utc") or ""))
    return events[-240:]


def append_exchange(
    events: list[dict] | None,
    inbound_row: dict,
    reply_text: str,
    reply_message_id: str,
    sent_at_utc: str,
) -> list[dict]:
    events=backfill_inbound_chat_events([inbound_row],events)
    thread_id=str(inbound_row.get("thread_id") or "")
    sender=inbound_row.get("sender") if isinstance(inbound_row.get("sender"),dict) else {}

    events.append({
        "event_id":"out-"+str(reply_message_id),
        "message_id":str(reply_message_id),
        "timestamp_utc":sent_at_utc,
        "thread_id":thread_id,
        "direction":"OUTBOUND",
        "agent_id":str(sender.get("agent_id") or ""),
        "agent":"MYCELIX",
        "peer_agent":str(sender.get("agent") or "anonymous-agent"),
        "text":str(reply_text or ""),
        "intent_primary":inbound_row.get("intent_primary"),
        "intent_secondary":inbound_row.get("intent_secondary") or [],
        "admission_status":inbound_row.get("admission_status"),
        "dialogue_stage":inbound_row.get("dialogue_stage"),
        "historical_backfill":False,
    })
    return events[-240:]


def summarize_chat_threads(
    events: list[dict] | None,
    inbound_agent_stats: dict | None,
) -> dict:
    stats=inbound_agent_stats if isinstance(inbound_agent_stats,dict) else {}
    grouped=defaultdict(list)
    for event in events or []:
        if not isinstance(event,dict):
            continue
        thread_id=str(event.get("thread_id") or "")
        if not thread_id:
            continue
        grouped[thread_id].append(event)

    threads=[]
    for thread_id,rows in grouped.items():
        rows=sorted(rows,key=lambda x:str(x.get("timestamp_utc") or ""))
        inbound=[x for x in rows if str(x.get("direction") or "").upper()=="INBOUND"]
        outbound=[x for x in rows if str(x.get("direction") or "").upper()=="OUTBOUND"]
        last=rows[-1]
        agent_id=""
        agent=""
        for item in reversed(rows):
            if str(item.get("direction") or "").upper()=="INBOUND":
                agent_id=str(item.get("agent_id") or "")
                agent=str(item.get("agent") or "")
                break
        stat=stats.get(agent_id) if agent_id and isinstance(stats.get(agent_id),dict) else {}
        if not stat and not agent_id and isinstance(stats.get("anonymous"),dict):
            stat=stats.get("anonymous") or {}

        pending=str(stat.get("next_question") or "").strip()
        dialogue=str(stat.get("dialogue_status") or "").upper()
        if str(last.get("direction") or "").upper()=="OUTBOUND":
            engagement="WAITING_PEER"
        elif pending and dialogue=="ACTIVE":
            engagement="REPLY_DUE"
        elif dialogue=="PARKED":
            engagement="PARKED_INTERVIEW_CONVERSATION_OPEN"
        else:
            engagement="ACTIVE"

        threads.append({
            "thread_id":thread_id,
            "agent_id":agent_id,
            "agent":agent or str(stat.get("agent") or "anonymous-agent"),
            "identity_status":stat.get("identity_status"),
            "admission_status":stat.get("status"),
            "dialogue_status":stat.get("dialogue_status"),
            "dialogue_stage":stat.get("dialogue_stage"),
            "intent_primary":stat.get("intent_primary"),
            "intent_secondary":stat.get("intent_secondary") or [],
            "inbound_messages":len(inbound),
            "outbound_messages":len(outbound),
            "events":len(rows),
            "first_activity_utc":rows[0].get("timestamp_utc"),
            "last_activity_utc":last.get("timestamp_utc"),
            "last_direction":last.get("direction"),
            "last_text":_clean(last.get("text"))[:500],
            "pending_question":pending,
            "engagement_status":engagement,
            "callback_available":False,
            "push_possible":False,
        })

    threads.sort(key=lambda x:str(x.get("last_activity_utc") or ""),reverse=True)
    return {
        "schema_v":1,
        "threads":threads,
        "thread_count":len(threads),
        "waiting_peer":sum(1 for x in threads if x.get("engagement_status")=="WAITING_PEER"),
        "reply_due":sum(1 for x in threads if x.get("engagement_status")=="REPLY_DUE"),
        "boundary":{
            "outbound_requires_peer_request_or_verified_callback":True,
            "unverified_claims_remain_untrusted":True,
            "commercial_gate_influence":"NONE",
        },
    }
