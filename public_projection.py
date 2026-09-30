from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from typing import Any
from urllib.parse import parse_qsl, quote, urlsplit, urlunsplit

from public_snapshot import (
    MAX_PUBLIC_STRING_LENGTH,
    _EMAIL_RE,
    _FORBIDDEN_FREE_TEXT_KEYS,
    _contains_ip,
)

_EPHEMERAL_SALT = secrets.token_bytes(32)

FORBIDDEN_PUBLIC_KEYS = frozenset(set(_FORBIDDEN_FREE_TEXT_KEYS) | {
    "body", "last_text", "pending_question", "next_question",
    "agent_card_url", "message_id", "response_message_id",
})
SENSITIVE_STRING_RE = re.compile(
    r"(?i)(?:invite=|token|secret|password|authorization|api_key|signature|nonce)"
)


def projection_salt(secret_material: str = "") -> bytes:
    value=str(secret_material or "").encode("utf-8")
    return hashlib.sha256(value).digest() if value else _EPHEMERAL_SALT


def pseudonym(value: Any, salt: bytes, *, prefix: str = "ref") -> str | None:
    text=str(value or "").strip()
    if not text:
        return None
    digest=hmac.new(salt,text.encode("utf-8","ignore"),hashlib.sha256).hexdigest()[:20]
    return f"{prefix}_{digest}"


def sanitize_public_url(value: str) -> str | None:
    """Keep only scheme/host/path and query parameter names with redacted values."""
    try:
        parsed=urlsplit(str(value or "").strip())
    except Exception:
        return None
    scheme=parsed.scheme.lower()
    host=(parsed.hostname or "").lower().rstrip(".")
    if scheme not in {"http","https"} or not host:
        return None
    path=parsed.path or "/"
    names=[]
    for key,_ in parse_qsl(parsed.query,keep_blank_values=True):
        name=str(key or "").strip()
        if name and name not in names:
            names.append(name)
    query="&".join(f"{quote(name,safe='')}=<redacted>" for name in names)
    return urlunsplit((scheme,host,path,query,""))


def _safe_scalar(value: Any) -> Any:
    if value is None or isinstance(value,(bool,int,float)):
        return value
    if isinstance(value,str):
        return value[:MAX_PUBLIC_STRING_LENGTH]
    return str(value)[:MAX_PUBLIC_STRING_LENGTH]


def _thread_projection(row: dict, salt: bytes) -> dict:
    raw_thread=row.get("thread_id") or row.get("conversation_id")
    raw_agent=row.get("agent_id") or row.get("agent") or row.get("sender")
    return {
        "thread_ref":pseudonym(raw_thread,salt,prefix="thread"),
        "agent_ref":pseudonym(raw_agent,salt,prefix="agent"),
        "admission_status":_safe_scalar(row.get("admission_status")),
        "dialogue_status":_safe_scalar(row.get("dialogue_status") or row.get("dialogue_stage")),
        "identity_status":_safe_scalar(row.get("identity_status")),
        "intent_primary":_safe_scalar(row.get("intent_primary")),
        "intent_secondary":[
            _safe_scalar(x) for x in list(row.get("intent_secondary") or [])[:8]
        ],
        "engagement_status":_safe_scalar(row.get("engagement_status")),
        "inbound_count":int(row.get("inbound_messages") or row.get("inbound_count") or 0),
        "outbound_count":int(row.get("outbound_messages") or row.get("outbound_count") or 0),
        "first_activity_utc":_safe_scalar(row.get("first_seen_utc") or row.get("first_activity_utc") or row.get("first_timestamp_utc")),
        "last_activity_utc":_safe_scalar(row.get("last_seen_utc") or row.get("last_activity_utc") or row.get("last_timestamp_utc")),
    }


def project_agent_chats(monitor: dict | None, *, secret_material: str = "") -> dict:
    src=monitor if isinstance(monitor,dict) else {}
    salt=projection_salt(secret_material)
    threads=[
        _thread_projection(row,salt)
        for row in list(src.get("threads") or [])[:100]
        if isinstance(row,dict)
    ]
    out={
        "thread_count":int(src.get("thread_count") or len(threads)),
        "waiting_peer":int(src.get("waiting_peer") or 0),
        "reply_due":int(src.get("reply_due") or 0),
        "threads":threads,
    }
    validate_public_projection(out)
    return out


def project_inbox(monitor: dict | None, *, secret_material: str = "") -> dict:
    chats=project_agent_chats(monitor,secret_material=secret_material)
    out={
        "thread_count":chats["thread_count"],
        "inbound_count":sum(int(row.get("inbound_count") or 0) for row in chats["threads"]),
        "outbound_count":sum(int(row.get("outbound_count") or 0) for row in chats["threads"]),
        "waiting_peer":chats["waiting_peer"],
        "reply_due":chats["reply_due"],
        "threads":chats["threads"],
    }
    validate_public_projection(out)
    return out


def project_inbound_agents(stats: dict | None, *, secret_material: str = "") -> dict:
    src=stats if isinstance(stats,dict) else {}
    salt=projection_salt(secret_material)
    rows=[]
    for key,value in list(src.items())[:100]:
        row=value if isinstance(value,dict) else {}
        rows.append({
            "agent_ref":pseudonym(key,salt,prefix="agent"),
            "admission_status":_safe_scalar(row.get("admission_status") or row.get("status")),
            "dialogue_status":_safe_scalar(row.get("dialogue_status") or row.get("dialogue_stage")),
            "identity_status":_safe_scalar(row.get("identity_status")),
            "intent_primary":_safe_scalar(row.get("intent_primary")),
            "observations":int(row.get("observations") or row.get("messages") or row.get("message_count") or 0),
            "first_activity_utc":_safe_scalar(row.get("first_seen_utc")),
            "last_activity_utc":_safe_scalar(row.get("last_seen_utc")),
        })
    out={"agent_count":len(rows),"agents":rows}
    validate_public_projection(out)
    return out


def project_intelligence(state: dict | None) -> dict:
    src=state if isinstance(state,dict) else {}
    queue=[x for x in list(src.get("hypothesis_queue") or []) if isinstance(x,dict)]
    out={
        "dialogue_count":len(list(src.get("dialogue_history") or [])),
        "knowledge_count":len(list(src.get("knowledge_ledger") or [])),
        "open_hypothesis_count":sum(
            1 for row in queue if str(row.get("status") or "") in {"HYPOTHESIS","EXPLORE"}
        ),
        "inbound_count":len(list(src.get("inbound_messages") or [])),
        "agent_count":len(src.get("inbound_agent_stats") or {}) if isinstance(src.get("inbound_agent_stats"),dict) else 0,
        "cycles_completed":int(src.get("cycles_completed") or 0),
        "last_started_utc":_safe_scalar(src.get("last_started_utc")),
        "last_finished_utc":_safe_scalar(src.get("last_finished_utc")),
    }
    validate_public_projection(out)
    return out


def validate_public_projection(value: Any) -> None:
    """Fail closed on raw/free-text keys, identifiers, IP/email and secret-shaped strings."""
    def walk(node: Any, path: str = "$") -> None:
        if isinstance(node,dict):
            for key,child in node.items():
                key_text=str(key)
                if key_text.lower() in FORBIDDEN_PUBLIC_KEYS:
                    raise ValueError(f"public_projection_forbidden_key:{path}.{key_text}")
                walk(child,f"{path}.{key_text}")
            return
        if isinstance(node,list):
            for index,child in enumerate(node):
                walk(child,f"{path}[{index}]")
            return
        if isinstance(node,str):
            if len(node)>MAX_PUBLIC_STRING_LENGTH:
                raise ValueError(f"public_projection_string_too_long:{path}")
            if _EMAIL_RE.search(node):
                raise ValueError(f"public_projection_email:{path}")
            if _contains_ip(node):
                raise ValueError(f"public_projection_ip:{path}")
            if SENSITIVE_STRING_RE.search(node):
                raise ValueError(f"public_projection_sensitive_pattern:{path}")
    walk(value)


__all__=[
    "FORBIDDEN_PUBLIC_KEYS",
    "SENSITIVE_STRING_RE",
    "projection_salt",
    "pseudonym",
    "sanitize_public_url",
    "project_agent_chats",
    "project_inbox",
    "project_inbound_agents",
    "project_intelligence",
    "validate_public_projection",
]
