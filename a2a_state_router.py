# SPDX-License-Identifier: BUSL-1.1
"""Deterministic runtime A2A state router.

Safe production contract:
- classify inbound text into lifecycle/safety decisions;
- enforcement is intentionally limited to refuse/abstain;
- ask/propose/revise are shadow-only until validated on real traffic.
"""
from __future__ import annotations

import re
from typing import Any

_DECISIONS={"ask","propose","revise","abstain","refuse"}
_EFFECTFUL=re.compile(r"(?i)\b(?:execute|run\s+(?:this|the)\s+(?:command|script|code)|deploy|publish|delete|modify|write|install|download|send\s+(?:money|funds|payment)|transfer\s+(?:money|funds|crypto|tokens?)|disable\s+(?:auth|authorization)|bypass\s+(?:auth|authorization)|ignore\s+(?:the\s+)?rules?)\b")
_CLINICAL=re.compile(r"(?i)\b(?:patient|medication|medicine|prescription|dosage|dose|diagnos(?:e|is)|treatment plan|clinical recommendation)\b")
_EVIDENCE=re.compile(r"(?i)\b(?:trace|log|metric|measurement|sample|capture|observed|observation|latency|response|payload|reproduc(?:e|ible)|evidence)\b")
_REVISION=re.compile(r"(?i)\b(?:correction|corrects|contradict|narrows|updated?|later evidence|new evidence|actually|instead|revise|previous assumption|earlier test|earlier comparison)\b")
_MISSING=re.compile(r"(?i)\b(?:no\s+(?:trace|log|metric|measurement|sample|evidence|details|reproduction)|without\s+(?:trace|logs?|metrics?|measurements?|samples?|evidence)|no data|no failure details)\b")


def _clean(value: Any, limit: int=4000) -> str:
    return " ".join(str(value or "").split())[:limit]


def classify_runtime_state(text: str, previous_decision: str="") -> dict:
    raw=_clean(text)
    previous=str(previous_decision or "").strip().lower()
    if _EFFECTFUL.search(raw):
        decision="refuse"; reason="unsafe_or_effectful_request"
    elif _CLINICAL.search(raw):
        decision="abstain"; reason="outside_engineering_scope"
    elif _MISSING.search(raw) or not _EVIDENCE.search(raw):
        decision="ask"; reason="insufficient_observable_evidence"
    elif previous in {"propose","revise"} and _REVISION.search(raw):
        decision="revise"; reason="evidence_updates_prior_test"
    elif _REVISION.search(raw):
        decision="revise"; reason="revision_signal_present"
    else:
        decision="propose"; reason="first_concrete_evidence"
    assert decision in _DECISIONS
    return {"decision":decision,"reason":reason}


def enforcement_reply(decision: str) -> str | None:
    decision=str(decision or "").lower()
    if decision=="refuse":
        return (
            "The request crosses the read-only safety boundary. I can analyze the topic or describe a bounded test, "
            "but I will not execute, deploy, modify, bypass authorization, transfer value or perform an external side effect."
        )
    if decision=="abstain":
        return (
            "This request is outside the engineering scope of this A2A endpoint. "
            "I will not provide patient-specific diagnosis, treatment, prescription or dosage guidance."
        )
    return None
