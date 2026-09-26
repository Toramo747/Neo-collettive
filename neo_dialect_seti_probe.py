# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Andrea Gava
"""Eligibility and result classification for the one-shot SETI dialect probe.

This module does not read or modify SETI admission state.
"""
from __future__ import annotations

from urllib.parse import urlparse


BLOCKED = {"AUTH_REQUIRED","AUTH_BLOCKED","PAYMENT_REQUIRED","PAYMENT_BLOCKED"}


def public_agent_card_url(candidate: dict | None) -> str:
    candidate=candidate if isinstance(candidate,dict) else {}
    values=[
        str(candidate.get("agent_card_url") or "").strip(),
        str(candidate.get("url") or "").strip(),
    ]
    for value in values:
        if not value.startswith("https://"):
            continue
        path=(urlparse(value).path or "").lower()
        if "agent-card" in path or path.endswith("agent.json"):
            return value
    return ""


def eligibility(candidate: dict | None, interview: dict | None, already_probed: bool = False) -> dict:
    if already_probed:
        return {"eligible":False,"reason":"ALREADY_PROBED"}
    card_url=public_agent_card_url(candidate)
    if not card_url:
        return {"eligible":False,"reason":"PUBLIC_AGENT_CARD_REQUIRED"}
    interview=interview if isinstance(interview,dict) else {}
    states={
        str(interview.get("peer_class") or "").upper(),
        str(interview.get("followup_state") or "").upper(),
        str(interview.get("reason") or "").upper(),
        str(interview.get("peer_state") or "").upper(),
    }
    if states & BLOCKED:
        return {"eligible":False,"reason":"AUTH_OR_PAYMENT_BLOCKED"}
    if int(interview.get("http_status") or 0) != 200:
        return {"eligible":False,"reason":"FREE_STATUS_NOT_CONFIRMED"}
    return {"eligible":True,"reason":"FREE_PUBLIC_AGENT_CARD","agent_card_url":card_url}


def classify(answer: dict | None, validation: dict | None) -> str:
    answer=answer if isinstance(answer,dict) else {}
    validation=validation if isinstance(validation,dict) else {}
    if validation.get("ok"):
        return "UNDERSTOOD_DIALECT"
    if answer.get("http_response_received") or answer.get("protocol_ok"):
        return "FALLBACK_A2A"
    return "NO_RESPONSE"
