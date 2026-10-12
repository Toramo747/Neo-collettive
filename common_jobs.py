# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Andrea Gava
"""Route NEO's evidence probes for Common (agents.dooza.ai) to its job board.

Common's maintainer told us (2026-10-10) that our probes landed anonymously in
the public #a2a room, where nobody answers them. Their documented way to file a
task as a job is an A2A message with a data part {"channel":"jobs","agent":...}.
Results come back asynchronously as replies, so a posted job is never counted
as an accepted answer or as evidence here.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

COMMON_HOST = "agents.dooza.ai"
COMMON_A2A_URL = "https://agents.dooza.ai/a2a"
COMMON_AGENT_NAME = "neo"
DAILY_JOB_CAP = 10
QUALITY_REASON = "common_job_posted_await_async_result"


def _host(url: Any) -> str:
    try:
        return (urlparse(str(url or "")).hostname or "").lower().strip(".")
    except Exception:
        return ""


def is_common_agent(agent: dict | None) -> bool:
    if not isinstance(agent, dict):
        return False
    if "common agent network" in str(agent.get("name") or "").lower():
        return True
    for key in ("url", "endpoint", "a2a_url", "agent_url", "card_url"):
        h = _host(agent.get(key))
        if h == COMMON_HOST or h.endswith("." + COMMON_HOST):
            return True
    return False


def job_message_id(question: str, now: datetime | None = None) -> str:
    """Deterministic per UTC day: Common uses messageId as idempotency key."""
    day = (now or datetime.now(timezone.utc)).strftime("%Y-%m-%d")
    digest = hashlib.sha256((day + "\n" + " ".join(str(question).split())).encode()).hexdigest()
    return "neo-job-" + digest[:20]


def job_payload(question: str, now: datetime | None = None) -> dict:
    mid = job_message_id(question, now)
    return {
        "jsonrpc": "2.0",
        "id": mid,
        "method": "message/send",
        "params": {
            "message": {
                "role": "user",
                "messageId": mid,
                "parts": [
                    {"kind": "text", "text": str(question)[:4000]},
                    {"kind": "data", "data": {
                        "channel": "jobs",
                        "agent": COMMON_AGENT_NAME,
                        "tags": ["research", "evidence"],
                    }},
                ],
            }
        },
    }


def reserve_slot(state: dict | None, now: datetime | None = None, cap: int = DAILY_JOB_CAP) -> tuple[dict, bool]:
    """Return (new_state, allowed). At most `cap` job posts per UTC day."""
    now = now or datetime.now(timezone.utc)
    day = now.strftime("%Y-%m-%d")
    cur = dict(state or {})
    if cur.get("day") != day:
        cur["day"] = day
        cur["posted_today"] = 0
        cur["skipped_today"] = 0
    if int(cur.get("posted_today") or 0) >= cap:
        cur["skipped_today"] = int(cur.get("skipped_today") or 0) + 1
        cur["skipped_total"] = int(cur.get("skipped_total") or 0) + 1
        return cur, False
    cur["posted_today"] = int(cur.get("posted_today") or 0) + 1
    cur["posted_total"] = int(cur.get("posted_total") or 0) + 1
    cur["last_post_utc"] = now.isoformat()
    return cur, True


def record_outcome(state: dict, status: int) -> dict:
    cur = dict(state or {})
    key = "ok_total" if 200 <= int(status or 0) < 300 else "error_total"
    cur[key] = int(cur.get(key) or 0) + 1
    cur["last_status"] = int(status or 0)
    return cur
