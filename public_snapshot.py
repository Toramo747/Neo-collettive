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
    src["inbound_traffic_events"]=_project(src.get("inbound_traffic_events"),_PUBLIC_TRAFFIC_KEYS,1200)
    src["inbound_security_events"]=_project(src.get("inbound_security_events"),_PUBLIC_SECURITY_KEYS,80)
    return src
