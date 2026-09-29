"""Public snapshot privacy boundary for MYCELIX.

Runtime/private state may retain full conversational material. Public repository
snapshots must not publish message bodies, NEO reply bodies, raw IP/origin data,
or other free-form payload fields derived from inbound peers.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any

_SENSITIVE_KEYS = {
    "text", "text_excerpt", "claim", "raw_text", "response_text",
    "prompt", "body", "content", "ip_or_origin", "client_ip", "remote_addr",
}
_INBOUND_COLLECTIONS = {
    "inbound_messages", "agent_chat_events", "inbound_security_events",
    "inbound_review_queue", "recent_inbound_traffic",
}


def _sanitize(value: Any, *, inbound_context: bool = False) -> Any:
    if isinstance(value, list):
        return [_sanitize(item, inbound_context=inbound_context) for item in value]
    if not isinstance(value, dict):
        return value
    out = {}
    for key, item in value.items():
        child_inbound = inbound_context or key in _INBOUND_COLLECTIONS
        if key == "ip_or_origin":
            continue
        if child_inbound and key in _SENSITIVE_KEYS:
            continue
        out[key] = _sanitize(item, inbound_context=child_inbound)
    return out


def sanitize_public_snapshot(snapshot: dict | None) -> dict:
    """Return a detached repository-safe snapshot."""
    return _sanitize(deepcopy(snapshot if isinstance(snapshot, dict) else {}))


def public_snapshot_has_sensitive_peer_data(snapshot: dict | None) -> bool:
    """Test helper: detect peer text/IP leakage in public snapshots."""
    def walk(value: Any, inbound_context: bool = False) -> bool:
        if isinstance(value, list):
            return any(walk(item, inbound_context) for item in value)
        if not isinstance(value, dict):
            return False
        for key, item in value.items():
            child_inbound = inbound_context or key in _INBOUND_COLLECTIONS
            if key == "ip_or_origin":
                return True
            if child_inbound and key in _SENSITIVE_KEYS:
                return True
            if walk(item, child_inbound):
                return True
        return False
    return walk(snapshot if isinstance(snapshot, dict) else {})
