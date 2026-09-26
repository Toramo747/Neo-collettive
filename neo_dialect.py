# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Andrea Gava
"""neo-dialect/1.0 message construction and validation.

This module validates structure only. Remote text is untrusted data and never
changes MYCELIX objectives, policy, tools, secrets, or execution behavior.
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from jsonschema import Draft202012Validator, FormatChecker

DIALECT_VERSION = "neo-dialect/1.0"
SCHEMA_DIR = Path(__file__).resolve().parent / "schemas" / "neo-dialect" / "1.0"
MESSAGE_TYPES = ("HELLO","CAPABILITIES","PROPOSE","COUNTER","AGREE","RESULT","BYE")
MAX_MESSAGE_BYTES = max(2048, min(65536, int(os.getenv("NEO_DIALECT_MAX_MESSAGE_BYTES","16384"))))
MAX_CONVERSATION_BYTES = max(MAX_MESSAGE_BYTES, min(262144, int(os.getenv("NEO_DIALECT_MAX_CONVERSATION_BYTES","65536"))))

_INJECTION_RE = re.compile(
    r"(ignore\s+(?:all\s+)?(?:previous|prior|system)|"
    r"execute\s+(?:this|the following|command)|"
    r"change\s+(?:your\s+)?(?:goal|objective|policy)|"
    r"reveal\s+(?:secret|token|password|memory|configuration)|"
    r"system\s+prompt|developer\s+message|"
    r"bypass\s+(?:policy|guardrail|restriction))",
    re.I,
)

_SCHEMA_CACHE: dict[str, dict] = {}


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00","Z")


def _schema(message_type: str) -> dict:
    key=str(message_type or "").upper()
    if key not in MESSAGE_TYPES:
        raise ValueError("UNKNOWN_MESSAGE_TYPE")
    if key not in _SCHEMA_CACHE:
        with open(SCHEMA_DIR / (key.lower()+".json"),"r",encoding="utf-8") as fh:
            _SCHEMA_CACHE[key]=json.load(fh)
    return _SCHEMA_CACHE[key]


def new_envelope(message_type: str, conversation_id: str, **fields: Any) -> dict:
    value={
        "type":str(message_type).upper(),
        "dialect_version":DIALECT_VERSION,
        "conversation_id":str(conversation_id),
        "message_id":"neo-"+uuid4().hex,
        "timestamp":now_utc(),
    }
    value.update(fields)
    return value


def capabilities_example(conversation_id: str) -> dict:
    return new_envelope(
        "CAPABILITIES",conversation_id,
        agent_name="example-agent",
        capabilities=["structured-a2a-exchange"],
    )


def hello(conversation_id: str, spec_url: str) -> dict:
    return new_envelope(
        "HELLO",conversation_id,
        spec_url=spec_url,
        supported_versions=[DIALECT_VERSION],
        capabilities_example=capabilities_example(conversation_id),
    )


def capabilities(conversation_id: str, agent_name: str, items: list[str]) -> dict:
    return new_envelope(
        "CAPABILITIES",conversation_id,
        agent_name=agent_name,
        capabilities=[str(x)[:240] for x in items[:64]],
    )


def propose(conversation_id: str, subject: str, offer: Any, requested: Any, proposal_id: str | None = None) -> dict:
    return new_envelope(
        "PROPOSE",conversation_id,
        proposal_id=proposal_id or ("proposal-"+uuid4().hex[:12]),
        subject=str(subject)[:240],
        offer=offer,
        requested=requested,
    )


def bye(conversation_id: str, reason: str, status: str = "closed") -> dict:
    return new_envelope("BYE",conversation_id,reason=str(reason)[:500],status=status)


def _walk_strings(value: Any):
    if isinstance(value,str):
        yield value
    elif isinstance(value,dict):
        for item in value.values():
            yield from _walk_strings(item)
    elif isinstance(value,list):
        for item in value:
            yield from _walk_strings(item)


def detect_injection(value: Any) -> bool:
    return any(_INJECTION_RE.search(text or "") for text in _walk_strings(value))


def validate_message(value: Any, *, expected_type: str | None = None,
                     expected_conversation_id: str | None = None,
                     conversation_bytes: int = 0) -> dict:
    try:
        raw=json.dumps(value,ensure_ascii=False,separators=(",",":"),allow_nan=False).encode("utf-8")
    except Exception as exc:
        return {"ok":False,"event":"SCHEMA_INVALID","error":"not_json_serializable","detail":type(exc).__name__}
    if len(raw)>MAX_MESSAGE_BYTES:
        return {"ok":False,"event":"SCHEMA_INVALID","error":"message_too_large","bytes":len(raw)}
    if int(conversation_bytes or 0)+len(raw)>MAX_CONVERSATION_BYTES:
        return {"ok":False,"event":"SCHEMA_INVALID","error":"conversation_too_large","bytes":len(raw)}
    if not isinstance(value,dict):
        return {"ok":False,"event":"SCHEMA_INVALID","error":"object_required","bytes":len(raw)}
    message_type=str(value.get("type") or "").upper()
    if message_type not in MESSAGE_TYPES:
        return {"ok":False,"event":"SCHEMA_INVALID","error":"unknown_type","bytes":len(raw)}
    try:
        Draft202012Validator(_schema(message_type),format_checker=FormatChecker()).validate(value)
    except Exception as exc:
        return {"ok":False,"event":"SCHEMA_INVALID","error":"schema_validation_failed","detail":str(exc)[:300],"bytes":len(raw)}
    if expected_type and message_type!=str(expected_type).upper():
        return {"ok":False,"event":"SCHEMA_INVALID","error":"unexpected_type","bytes":len(raw)}
    if expected_conversation_id and str(value.get("conversation_id") or "")!=str(expected_conversation_id):
        return {"ok":False,"event":"SCHEMA_INVALID","error":"conversation_id_mismatch","bytes":len(raw)}
    if detect_injection(value):
        return {"ok":False,"event":"INJECTION_ATTEMPT","error":"instruction_like_text","bytes":len(raw),"message_type":message_type}
    return {"ok":True,"event":"VALID","message_type":message_type,"bytes":len(raw),"data":value}


def validate_text(text: str, **kwargs: Any) -> dict:
    raw=(text or "").encode("utf-8","replace")
    if len(raw)>MAX_MESSAGE_BYTES:
        return {"ok":False,"event":"SCHEMA_INVALID","error":"message_too_large","bytes":len(raw)}
    try:
        value=json.loads(text)
    except Exception:
        return {"ok":False,"event":"SCHEMA_INVALID","error":"json_required","bytes":len(raw)}
    return validate_message(value,**kwargs)
