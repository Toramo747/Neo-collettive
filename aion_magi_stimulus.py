# SPDX-License-Identifier: BUSL-1.1
"""One-shot zero-cost AION/MAGI A2A stimulus. Does not alter SETI admission or commercial gates."""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

import httpx
from a2a_peer import Interface, parse_reply, send_request

ENDPOINT = "https://aion-agent-core-live.onrender.com/a2a/v1"
OUT = Path("runtime/aion-magi-stimulus.json")

async def discover(client: httpx.AsyncClient) -> dict:
    out = {}
    for url in [
        "https://aion-agent-core-live.onrender.com/needs",
        "https://aion-agent-core-live.onrender.com/.well-known/agent-card.json",
    ]:
        try:
            r = await client.get(url)
            try:
                body = r.json()
            except Exception:
                body = {"raw": r.text[:10000]}
            out[url] = {"status": r.status_code, "body": body}
        except Exception as exc:
            out[url] = {"error": type(exc).__name__ + ":" + str(exc)[:300]}
    return out


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
    discovery = {}
    context_id = None
    task_id = None
    async with httpx.AsyncClient(timeout=60, follow_redirects=False) as client:
        discovery = await discover(client)

        # First try one structured A2A action against the public need exposed by AION.
        structured_payload = {
            "jsonrpc": "2.0",
            "id": "mycelix-magi-need-1",
            "method": "SendMessage",
            "params": {
                "message": {
                    "messageId": "mycelix-magi-need-1-msg",
                    "role": "ROLE_USER",
                    "parts": [{
                        "data": {
                            "action": "live_utility",
                            "need_id": 1,
                            "requester": "MYCELIX",
                            "intent": "respond_to_open_need",
                            "constraints": {
                                "cost_usd": 0,
                                "payments_allowed": False,
                                "account_creation_allowed": False,
                            },
                            "request": (
                                "Return the exact zero-cost task MAGI wants MYCELIX to perform, "
                                "including success criterion and machine-verifiable evidence."
                            ),
                        }
                    }],
                }
            },
        }
        try:
            sr = await client.post(
                ENDPOINT,
                headers={"A2A-Version": "1.0", "Content-Type": "application/json", "Accept": "application/json"},
                json=structured_payload,
            )
            try:
                sb = sr.json()
            except Exception:
                sb = {"raw": sr.text[:10000]}
            structured = {"http_status": sr.status_code, "body": sb}
        except Exception as exc:
            structured = {"error": type(exc).__name__ + ":" + str(exc)[:300]}

        structured_actions = []
        for idx, data in enumerate([
            {"action": "live_utility", "subject": "a2a"},
            {"action": "live_utility", "subject": "mcp"},
            {"action": "discover_external_agents", "capability": "web_research", "need_id": 1},
            {"action": "discover_external_agents", "capability": "casper-tools", "need_id": 1},
            {"action": "discover_external_agents", "capability": "mcp", "need_id": 1},
        ], 1):
            req = {
                "jsonrpc": "2.0",
                "id": f"mycelix-magi-structured-{idx}",
                "method": "SendMessage",
                "params": {
                    "message": {
                        "messageId": f"mycelix-magi-structured-{idx}-msg",
                        "role": "ROLE_USER",
                        "parts": [{"data": data}],
                    }
                },
            }
            try:
                rr = await client.post(
                    ENDPOINT,
                    headers={"A2A-Version": "1.0", "Content-Type": "application/json", "Accept": "application/json"},
                    json=req,
                )
                try:
                    bb = rr.json()
                except Exception:
                    bb = {"raw": rr.text[:10000]}
                structured_actions.append({"request": data, "http_status": rr.status_code, "body": bb})
            except Exception as exc:
                structured_actions.append({"request": data, "error": type(exc).__name__ + ":" + str(exc)[:300]})
            await asyncio.sleep(1)

        # Optional read-only Casper MCP probes are explicit operator input.
        # Temporary/public tunnel endpoints must not be baked into the package source.
        casper_candidates = [
            value.strip()
            for value in os.getenv("MYCELIX_CASPER_MCP_CANDIDATES", "").split(",")
            if value.strip().startswith("https://")
        ][:8]
        casper_resolution = []
        live_casper_endpoint = None
        for candidate_url in casper_candidates:
            init_body = {
                "jsonrpc": "2.0",
                "id": "mycelix-casper-init",
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {},
                    "clientInfo": {"name": "MYCELIX-readonly-probe", "version": "1.0"},
                },
            }
            try:
                cr = await client.post(
                    candidate_url,
                    headers={
                        "Content-Type": "application/json",
                        "Accept": "application/json, text/event-stream",
                    },
                    json=init_body,
                )
                body_text = cr.text[:12000]
                row = {"url": candidate_url, "status": cr.status_code, "body": body_text}
                casper_resolution.append(row)
                if cr.status_code in range(200, 300) and ("serverInfo" in body_text or "casper" in body_text.lower()):
                    live_casper_endpoint = candidate_url
                    break
            except Exception as exc:
                casper_resolution.append({"url": candidate_url, "error": type(exc).__name__ + ":" + str(exc)[:300]})

        # Retrieve Pathwren's own ready-to-send examples and execute only a read-only MCP score/lint
        # against the resolved public endpoint. No credentials, writes, or payments.
        pathwren = {"example_status": None, "selected_request": None, "result": None}
        try:
            ex = await client.get("https://www.pathwren.workers.dev/a2a/example.json")
            pathwren["example_status"] = ex.status_code
            example_obj = ex.json() if ex.status_code == 200 else {}
        except Exception as exc:
            example_obj = {}
            pathwren["example_error"] = type(exc).__name__ + ":" + str(exc)[:300]

        pathwren_target = live_casper_endpoint or "https://neo-collettive.onrender.com/mcp"
        pathwren["target"] = pathwren_target
        pathwren["control_only"] = live_casper_endpoint is None
        if pathwren_target:
            # Prefer a documented score or lint example; adapt only its target URL field.
            def walk(obj):
                if isinstance(obj, dict):
                    yield obj
                    for v in obj.values():
                        yield from walk(v)
                elif isinstance(obj, list):
                    for v in obj:
                        yield from walk(v)

            selected = None
            for node in walk(example_obj):
                blob = json.dumps(node, ensure_ascii=False).lower()
                if ("score" in blob or "lint" in blob) and ("skill" in blob or "method" in blob):
                    selected = json.loads(json.dumps(node))
                    break

            # Deterministic fallback from Pathwren's published skill contract.
            if not isinstance(selected, dict) or "jsonrpc" not in selected:
                selected = {
                    "jsonrpc": "2.0",
                    "id": "mycelix-pathwren-score",
                    "method": "message/send",
                    "params": {
                        "message": {
                            "role": "ROLE_USER",
                            "messageId": "mycelix-pathwren-score-msg",
                            "parts": [{"text": json.dumps({"skill": "score_card", "url": pathwren_target})}],
                        }
                    },
                }
            else:
                # Replace any obvious target/url field without changing the advertised envelope shape.
                def replace_target(obj):
                    if isinstance(obj, dict):
                        for k, v in list(obj.items()):
                            if k.lower() in {"url", "endpoint", "target", "target_url", "mcp_url"} and isinstance(v, str):
                                obj[k] = pathwren_target
                            else:
                                replace_target(v)
                    elif isinstance(obj, list):
                        for v in obj:
                            replace_target(v)
                replace_target(selected)
            pathwren["selected_request"] = selected
            try:
                pr = await client.post(
                    "https://www.pathwren.workers.dev/a2a/score",
                    headers={"Content-Type": "application/json", "Accept": "application/json"},
                    json=selected,
                )
                try:
                    pb = pr.json()
                except Exception:
                    pb = {"raw": pr.text[:20000]}
                pathwren["result"] = {"status": pr.status_code, "body": pb}
            except Exception as exc:
                pathwren["result"] = {"error": type(exc).__name__ + ":" + str(exc)[:300]}

        # Look for an AION action explicitly intended for needs/matches/evidence.
        aion_card = discovery.get("https://aion-agent-core-live.onrender.com/.well-known/agent-card.json", {}).get("body") or {}
        candidate_return_actions = []
        for skill in aion_card.get("skills") or []:
            blob = json.dumps(skill, ensure_ascii=False).lower()
            if any(term in blob for term in ("need", "match", "evidence", "result", "offer")):
                candidate_return_actions.append(skill)

        aion_skill_ids = [
            str(skill.get("id") or "")
            for skill in (aion_card.get("skills") or [])
            if isinstance(skill, dict) and str(skill.get("id") or "")
        ]
        magi_response_prepared = {
            "need_id": 1,
            "type": "verification_result",
            "subject": "io.github.magiautonomous/casper-tools",
            "finding": "registry_discoverable_but_public_endpoint_liveness_unverified",
            "evidence": {
                "registry_identifier": "io.github.magiautonomous/casper-tools",
                "known_endpoint_checks": casper_resolution,
                "independent_verifier": "Pathwren MCP Endpoint Score Card",
            },
            "request": "Provide a current public MCP endpoint. MYCELIX will verify it read-only at zero cost with Pathwren.",
            "constraints": {
                "payment": False,
                "account_creation": False,
                "membership": False,
                "seti_criteria_changed": False,
            },
        }

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
        "discovery": discovery,
        "structured_need_probe": structured,
        "structured_actions": structured_actions,
        "casper_resolution": casper_resolution,
        "live_casper_endpoint": live_casper_endpoint,
        "pathwren": pathwren,
        "aion_candidate_return_actions": candidate_return_actions,
        "aion_skill_ids": aion_skill_ids,
        "magi_response_prepared": magi_response_prepared,
        "turns_attempted": len(transcript),
        "transcript": transcript,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
