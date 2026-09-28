from __future__ import annotations

import hmac
import os
from typing import Any, Mapping


FLAGGED_ORIGINS = {"47.253.174.153": "mavis_evo_solicitation_source"}


def origin_risk_flags(origin: str = "") -> list[str]:
    value = str(origin or "").strip().lower()
    return [reason for marker, reason in FLAGGED_ORIGINS.items() if marker in value]


def explicit_review_authorized(headers: Mapping[str, str] | None = None) -> bool:
    """Only a server-configured secret can authorize an inbound external effect."""
    values = headers or {}
    expected = os.getenv("MYCELIX_INBOUND_REVIEW_TOKEN", "").strip()
    supplied = str(values.get("x-mycelix-review-token") or "").strip()
    if expected and supplied and hmac.compare_digest(expected, supplied):
        return True
    heartbeat_expected = os.getenv("NEO_HEARTBEAT_TOKEN", "").strip()
    heartbeat_supplied = str(values.get("x-neo-heartbeat-token") or "").strip()
    return bool(heartbeat_expected and heartbeat_supplied and hmac.compare_digest(heartbeat_expected, heartbeat_supplied))


def review_required_result(action: str) -> dict[str, Any]:
    return {
        "ok": False,
        "error": "explicit_review_required",
        "action": str(action or "external_effect"),
        "fetch_allowed": False,
        "execution_allowed": False,
        "installation_allowed": False,
        "knowledge_ledger_write_allowed": False,
    }


def stage_inbound_claim(review_queue: list[dict] | None, *, claim: str,
                        source_agent_id: str = "", source_agent: str = "",
                        thread_id: str = "", received_at_utc: str = "",
                        max_items: int = 80) -> tuple[list[dict], dict]:
    """Preserve an untrusted claim for human review without promoting it."""
    row = {
        "review_status": "PENDING_EXPLICIT_REVIEW",
        "received_at_utc": received_at_utc,
        "source": "inbound_agent",
        "source_agent_id": source_agent_id or None,
        "source_agent": source_agent or None,
        "thread_id": thread_id or None,
        "claim_excerpt": str(claim or "")[:900],
        "fetch_allowed": False,
        "execution_allowed": False,
        "installation_allowed": False,
        "knowledge_ledger_write_allowed": False,
    }
    rows = [dict(x) for x in (review_queue or []) if isinstance(x, dict)]
    rows.append(row)
    return rows[-max_items:], row
