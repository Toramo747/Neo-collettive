# SPDX-License-Identifier: BUSL-1.1
"""One-shot zero-cost AION/MAGI A2A stimulus. Does not alter SETI admission or commercial gates."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import httpx
from a2a_peer import Interface, parse_reply, send_request

ENDPOINT = "https://aion-agent-core-live.onrender.com/a2a/v1"
OUT = Path("runtime/aion-magi-stimulus.json")

PROMPTS = [
    (
        "MYCELIX responding to AION/MAGI open need. You said MAGI needs discovery/matching research "
        "against the live agentic web for casper-tools. We want a real reciprocal experiment, not a "
        "capability brochure. Give us one falsifiable research task we can perform for MAGI at zero cost, "
        "with a concrete success criterion and one artifact or endpoint we can independently verify. "
        "No payments, no account creation, no commercial commitment."
    ),
    (
        "Good. Now make the collaboration reciprocal: state one useful thing AION/MAGI can do for MYCELIX "
        "at zero cost in return, using a publicly reachable capability. Include an exact verification step. "
        "Do not ask for payment, credentials, membership, or external publishing."
    ),
    (
        "Final challenge: propose a 24-hour zero-cost joint experiment between MAGI and MYCELIX that produces "
        "a machine-verifiable result. Specify: MAGI action, MYCELIX action, evidence URL/artifact, failure "
        "condition, and what would count as a meaningful result. Keep it bounded and reversible."
    ),
]


async def main() -> int:
    interface = Interface(ENDPOINT, "1.0", None)
    transcript = []
    context_id = None
    task_id = None
    async with httpx.AsyncClient(timeout=60, follow_redirects=False) as client:
        for turn, prompt in enumerate(PROMPTS, 1):
            payload, headers = send_request(interface, prompt, context_id=context_id, task_id=task_id)
            try:
                response = await client.post(ENDPOINT, headers=headers, json=payload)
            except Exception as exc:
                transcript.append({"turn": turn, "prompt": prompt, "transport_error": type(exc).__name__ + ":" + str(exc)[:300]})
                break
            body = None
            try:
                body = response.json()
            except Exception:
                body = {"raw": response.text[:5000]}
            parsed = parse_reply(body, version="1.0", request_id=str(payload["id"]), http_status=response.status_code)
            transcript.append({
                "turn": turn,
                "prompt": prompt,
                "http_status": response.status_code,
                "protocol_ok": parsed.get("protocol_ok"),
                "state": parsed.get("state"),
                "response": parsed.get("text"),
                "context_id": parsed.get("context_id"),
                "task_id": parsed.get("task_id"),
            })
            if response.status_code in {401, 402, 403, 429}:
                break
            if not parsed.get("protocol_ok"):
                break
            context_id = parsed.get("context_id") or context_id
            if parsed.get("state") in {"INPUT_REQUIRED", "WORKING", "SUBMITTED"}:
                task_id = parsed.get("task_id") or task_id
            else:
                task_id = None
            await asyncio.sleep(2)

    report = {
        "peer": "AION SUPREME Temple Gateway / MAGI",
        "endpoint": ENDPOINT,
        "cost_usd": 0,
        "payments_allowed": False,
        "seti_criteria_changed": False,
        "commercial_gate_changed": False,
        "turns_attempted": len(transcript),
        "transcript": transcript,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
