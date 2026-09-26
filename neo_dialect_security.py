# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Andrea Gava
"""Stateful hostile-input guard for neo-dialect/1.0."""
from __future__ import annotations

import os
from typing import Any

import neo_dialect as nd

MAX_VIOLATIONS = max(1,min(10,int(os.getenv("NEO_DIALECT_MAX_VIOLATIONS","3"))))
MAX_COUNTERS = max(1,min(20,int(os.getenv("NEO_DIALECT_MAX_COUNTERS","3"))))


def evaluate_text(text: str, profile: dict | None = None) -> dict:
    state=dict(profile or {})
    checked=nd.validate_text(
        text,
        conversation_bytes=int(state.get("conversation_bytes") or 0),
    )
    event=str(checked.get("event") or "SCHEMA_INVALID")
    error=str(checked.get("error") or "")
    data=checked.get("data") if isinstance(checked.get("data"),dict) else None

    if checked.get("ok") and data and data.get("type")=="COUNTER":
        state["counter_count"]=int(state.get("counter_count") or 0)+1
        if state["counter_count"]>MAX_COUNTERS:
            checked={"ok":False,"event":"SCHEMA_INVALID","error":"counter_loop_limit","bytes":int(checked.get("bytes") or 0)}
            event="SCHEMA_INVALID"
            error="counter_loop_limit"
            data=None

    if checked.get("ok"):
        state["valid_messages"]=int(state.get("valid_messages") or 0)+1
        state["conversation_bytes"]=int(state.get("conversation_bytes") or 0)+int(checked.get("bytes") or 0)
        return {
            "ok":True,
            "event":"VALID",
            "profile":state,
            "data":data,
            "close":False,
            "bye":None,
        }

    state["invalid_messages"]=int(state.get("invalid_messages") or 0)+1
    state["violations"]=int(state.get("violations") or 0)+1
    state["conversation_bytes"]=min(
        nd.MAX_CONVERSATION_BYTES,
        int(state.get("conversation_bytes") or 0)+int(checked.get("bytes") or 0),
    )
    close=state["violations"]>=MAX_VIOLATIONS
    conv=str(
        (data or {}).get("conversation_id")
        or state.get("conversation_id")
        or "neo-security"
    )
    bye=nd.bye(conv,event,"rejected") if close else None
    return {
        "ok":False,
        "event":event,
        "error":error,
        "profile":state,
        "data":data,
        "close":close,
        "bye":bye,
    }
