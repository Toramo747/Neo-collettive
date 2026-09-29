from __future__ import annotations

from copy import deepcopy
from typing import Any


_PUBLIC_TRAFFIC_KEYS = (
    "timestamp_utc",
    "content_fingerprint",
    "category",
    "reason",
)
_PUBLIC_SECURITY_KEYS = (
    "received_at_utc",
    "traffic_class",
    "reason",
)


_PUBLIC_IDENTIFIER_KEYS={
    "agent_id","agent_ids","peer_id","source_agent_id","declared_agent_id","thread_id",
}


def _strip_public_identifiers(value: Any) -> Any:
    if isinstance(value,dict):
        return {
            key:_strip_public_identifiers(item)
            for key,item in value.items()
            if key not in _PUBLIC_IDENTIFIER_KEYS
        }
    if isinstance(value,list):
        return [_strip_public_identifiers(item) for item in value]
    return value


def _project(rows: Any, allowed: tuple[str, ...], limit: int) -> list[dict]:
    out=[]
    for row in list(rows or [])[-limit:]:
        if not isinstance(row,dict):
            continue
        out.append({key:row.get(key) for key in allowed if row.get(key) is not None})
    return out


def sanitize_public_autopilot(autopilot: dict | None) -> dict:
    """Return a public-repository-safe runtime view.

    Full inbound text, replies, peer/thread identifiers, UA/origin/IP data and
    review claims remain only in non-public runtime storage. Public snapshots
    expose bounded fingerprints, categories, counts and reason codes.
    """
    src=deepcopy(autopilot) if isinstance(autopilot,dict) else {}
    src["inbound_messages"]=[]
    src["agent_chat_events"]=[]
    monitor=src.get("agent_chat_monitor") if isinstance(src.get("agent_chat_monitor"),dict) else {}
    src["agent_chat_monitor"]={key:value for key,value in monitor.items() if key!="threads"}
    src["inbound_review_queue"]=[]
    src["inbound_agent_stats"]={}
    src["trust_lab_evaluations"]=[]
    demand=src.get("agent_demand_observatory") if isinstance(src.get("agent_demand_observatory"),dict) else {}
    if demand:
        src["agent_demand_observatory"]={key:deepcopy(value) for key,value in demand.items() if key!="agents"}
        src["agent_demand_observatory"]["agents"]=[]
    src["inbound_traffic_events"]=_project(src.get("inbound_traffic_events"),_PUBLIC_TRAFFIC_KEYS,1200)
    src["inbound_security_events"]=_project(src.get("inbound_security_events"),_PUBLIC_SECURITY_KEYS,80)
    return _strip_public_identifiers(src)
