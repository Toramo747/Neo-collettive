"""Bounded A2A peer client: explicit interfaces, strict replies, private context.

Remote text is untrusted. This module does not execute tools, authorize payments,
register accounts, or certify identity. Network requests have no ambient auth,
no proxies, pinned public DNS, no redirects, size limits and a shared budget.
"""
from __future__ import annotations

from dataclasses import dataclass
import ipaddress
import asyncio
import http.client
import json
import socket
import ssl
import re
from typing import Any
from urllib.parse import urlparse
from uuid import uuid4


@dataclass(frozen=True)
class Interface:
    url: str
    version: str
    tenant: str | None = None


def protocol_version(value: Any) -> str:
    match = re.fullmatch(r"(1\.0|0\.3)(?:\.\d+)?", str(value or ""))
    if not match:
        raise ValueError("unsupported_protocol_version")
    return match[1]


def _origin(url: str) -> tuple[str, int]:
    p = urlparse(url)
    host = (p.hostname or "").lower().rstrip(".")
    if p.scheme != "https" or not host or p.username or p.password or p.fragment or (p.port or 443) != 443:
        raise ValueError("unsafe_url")
    if host == "localhost" or host.endswith((".local", ".localhost")):
        raise ValueError("local_host")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None
    if address is not None and not address.is_global:
        raise ValueError("nonpublic_ip")
    return host, p.port or 443


def select_interface(card: dict, card_url: str) -> Interface:
    """Select a declared JSON-RPC endpoint; preserve server interface preference.

    This verifies URL syntax and same origin, NOT public DNS or peer identity.
    Unsupported modern cards do not silently fall back to an undeclared endpoint.
    """
    if not isinstance(card, dict):
        raise ValueError("invalid_card")
    _origin(card_url)
    if card.get("securityRequirements") or card.get("security"):
        raise ValueError("AUTH_REQUIRED")
    if "supportedInterfaces" in card:
        rows = card["supportedInterfaces"]
        if not isinstance(rows, list):
            raise ValueError("invalid_supported_interfaces")
    else:
        version = protocol_version(card.get("protocolVersion"))
        rows = [{"url": card.get("url"),
                 "protocolBinding": card.get("preferredTransport", "JSONRPC"),
                 "protocolVersion": version}]
        for row in card.get("additionalInterfaces") or []:
            if isinstance(row, dict):
                rows.append({"url": row.get("url"),
                             "protocolBinding": row.get("transport"),
                             "protocolVersion": version})
    for row in rows[:16]:
        if not isinstance(row, dict) or str(row.get("protocolBinding") or "").upper() != "JSONRPC":
            continue
        try:
            url = str(row.get("url") or "")
            version = protocol_version(row.get("protocolVersion"))
            _origin(url)
            if urlparse(url).path.endswith(("agent-card.json", "agent.json")):
                continue
            tenant = row.get("tenant")
            if tenant is not None:
                tenant = str(tenant).strip()
                if not tenant or len(tenant) > 256 or any(ord(c) < 32 for c in tenant):
                    continue
        except ValueError:
            continue
        return Interface(url, version, tenant)
    raise ValueError("no_safe_supported_jsonrpc_interface")


def send_request(interface: Interface, text: str, *, context_id: str | None = None,
                 task_id: str | None = None, message_id: str | None = None) -> tuple[dict, dict]:
    """Build one request. Caller must reuse a returned opaque context/task ID.

    Only an interrupted, non-terminal task may be continued with task_id.
    A caller cannot infer permission, identity or free execution from this object.
    """
    version = protocol_version(interface.version)
    if not isinstance(text, str) or not text.strip() or len(text) > 1800:
        raise ValueError("text_required_max_1800_chars")
    if task_id and not context_id:
        raise ValueError("prototype_requires_context_for_task_continuation")
    part = {"text": text} if version == "1.0" else {"kind": "text", "text": text}
    message = {"messageId": message_id or str(uuid4()),
               "role": "ROLE_USER" if version == "1.0" else "user", "parts": [part]}
    for key, value in (("contextId", context_id), ("taskId", task_id)):
        if value is not None:
            if not isinstance(value, str) or not value or len(value) > 512:
                raise ValueError("invalid_opaque_identifier")
            message[key] = value
    payload = {"jsonrpc": "2.0", "id": str(uuid4()),
               "method": "SendMessage" if version == "1.0" else "message/send",
               "params": {"message": message}}
    headers = {"A2A-Version": version, "Content-Type": "application/json",
               "Accept": "application/json"}
    return payload, headers


def _agent_parts(message: Any, version: str) -> list[str]:
    if not isinstance(message, dict):
        return []
    role = "ROLE_AGENT" if version == "1.0" else "agent"
    if message.get("role") != role:
        return []
    return _parts(message.get("parts"))


def _parts(parts: Any) -> list[str]:
    if not isinstance(parts, list):
        return []
    out = []
    for part in parts[:20]:
        if not isinstance(part, dict):
            continue
        if isinstance(part.get("text"), str):
            out.append(part["text"])
        elif isinstance(part.get("data"), dict):
            # Explicit small domain-output envelope, not recursive dict scraping.
            data = part["data"]
            keys = [key for key in ("output", "text", "response") if key in data]
            if len(keys) == 1 and isinstance(data[keys[0]], str):
                out.append(data[keys[0]])
    return out


def parse_reply(body: Any, *, version: str, request_id: str, http_status: int) -> dict:
    """Separate transport/protocol state from substance; never scan user history.

    Deliberately handles text only. Structured domain output needs a separately
    allowlisted schema adapter, not recursive string scraping.
    """
    version = protocol_version(version)
    base = {"protocol_ok": False, "state": "TRANSPORT_ERROR", "text": "",
            "context_id": None, "task_id": None, "peer_validated": False}
    if http_status in (401, 403, 402, 429):
        base["state"] = {401: "AUTH_REQUIRED", 403: "AUTH_REQUIRED",
                         402: "PAYMENT_REQUIRED", 429: "RATE_LIMITED"}[http_status]
        return base
    if not 200 <= http_status < 300:
        return base
    base["state"] = "PROTOCOL_ERROR"
    if not isinstance(body, dict) or body.get("jsonrpc") != "2.0":
        return base
    if body.get("id") != request_id or "error" in body or "result" not in body:
        return base
    result = body["result"]
    if not isinstance(result, dict):
        return base
    if version == "1.0":
        present = [key for key in ("task", "message") if key in result]
        if len(present) != 1 or not isinstance(result[present[0]], dict):
            return base
        is_task = present[0] == "task"
        result = result[present[0]]
    else:
        is_task = result.get("kind") == "task" or isinstance(result.get("status"), dict)
        if not is_task and result.get("kind") != "message":
            return base
    base["context_id"] = result.get("contextId")
    if base["context_id"] is not None and not _valid_id(base["context_id"]):
        return base
    if is_task:
        base["task_id"] = result.get("id")
        status = result.get("status") or {}
        if not isinstance(status, dict) or not _valid_id(base["task_id"]):
            return base
        state = str(status.get("state") or "").removeprefix("TASK_STATE_").replace("-", "_").upper()
        if state not in {"SUBMITTED", "WORKING", "INPUT_REQUIRED", "AUTH_REQUIRED",
                         "COMPLETED", "CANCELED", "REJECTED", "FAILED"}:
            return base
        fragments = _agent_parts(status.get("message"), version)
        artifacts = result.get("artifacts") or []
        if not isinstance(artifacts, list):
            return base
        for artifact in artifacts[:20]:
            if isinstance(artifact, dict):
                fragments.extend(_parts(artifact.get("parts")))
        base.update(protocol_ok=True, state=state, text="\n".join(fragments)[:12000])
    else:
        fragments = _agent_parts(result, version)
        if not fragments:
            return base
        base.update(protocol_ok=True, state="MESSAGE", text="\n".join(fragments)[:12000])
    return base


def _valid_id(value: Any) -> bool:
    return isinstance(value, str) and 0 < len(value) <= 512 and not any(ord(c) < 32 for c in value)


def peer_priority(candidate: dict, prior: dict) -> tuple:
    # Useful unfinished exchanges first; otherwise new peers before blind retries.
    useful = bool(prior.get("quality_ok") and (prior.get("peer_context") or {}).get("context_id"))
    tier = 2 if useful else (1 if not prior else 0)
    return tier, int(candidate.get("max_score") or 0), int(candidate.get("scan_count") or 0)


@dataclass
class RequestBudget:
    limit: int = 9
    used: int = 0

    def take(self) -> None:
        if self.used >= self.limit:
            raise ValueError("REQUEST_BUDGET_EXHAUSTED")
        self.used += 1


def _public_ips(host: str, port: int) -> list[str]:
    values = list(dict.fromkeys(row[4][0] for row in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)))
    if not values or any(not ipaddress.ip_address(value).is_global for value in values):
        raise ValueError("NONPUBLIC_DNS_BLOCKED")
    return values


def _request_sync(method: str, url: str, payload: dict | None, headers: dict, timeout: float) -> dict:
    """No proxy or ambient credentials; connect to the validated IP with original TLS SNI."""
    result = {"request_started": False, "response_received": False, "status": None, "body": None}
    connection = None
    raw_socket = None
    try:
        host, port = _origin(url)
        addresses = _public_ips(host, port)
        context = ssl.create_default_context()
        connection = http.client.HTTPSConnection(host, port, timeout=timeout, context=context)
        raw_socket = socket.create_connection((addresses[0], port), timeout=timeout)
        connection.sock = context.wrap_socket(raw_socket, server_hostname=host)
        raw_socket = None
        parsed = urlparse(url)
        path = (parsed.path or "/") + (("?" + parsed.query) if parsed.query else "")
        content = None if payload is None else json.dumps(payload, allow_nan=False).encode("utf-8")
        safe_headers = {"Accept": "application/json", "User-Agent": "MYCELIX-bounded-peer/0.94", "Accept-Encoding": "identity"}
        safe_headers.update({k: v for k, v in headers.items() if k in {"A2A-Version", "Content-Type"}})
        result["request_started"] = True
        connection.request(method, path, body=content, headers=safe_headers)
        response = connection.getresponse()
        result.update(response_received=True, status=response.status)
        if response.status in (401, 402, 403, 429) or 300 <= response.status < 400:
            return result
        if response.getheader("Content-Encoding", "identity") != "identity":
            raise ValueError("COMPRESSED_BODY_NOT_ACCEPTED")
        declared = response.getheader("Content-Length")
        if declared and int(declared) > 65536:
            raise ValueError("RESPONSE_TOO_LARGE")
        data = response.read(65537)
        if len(data) > 65536:
            raise ValueError("RESPONSE_TOO_LARGE")
        if "json" not in response.getheader("Content-Type", "").lower():
            raise ValueError("JSON_RESPONSE_REQUIRED")
        result["body"] = json.loads(data)
    except Exception as exc:
        result["error"] = str(exc)[:160] if isinstance(exc, ValueError) else type(exc).__name__
    finally:
        if connection is not None:
            connection.close()
        if raw_socket is not None:
            raw_socket.close()
    return result


async def public_json_request(method: str, url: str, budget: RequestBudget, payload: dict | None = None, headers: dict | None = None) -> dict:
    if method not in {"GET", "POST"}:
        raise ValueError("METHOD_NOT_ALLOWED")
    budget.take()
    try:
        return await asyncio.wait_for(asyncio.to_thread(_request_sync, method, url, payload, headers or {}, 10.0), timeout=12.0)
    except asyncio.TimeoutError:
        return {"request_started": None, "response_received": False, "status": None, "body": None, "error": "REQUEST_DEADLINE_DELIVERY_UNKNOWN"}


async def resolve_peer(candidate: dict, eligibility: dict, budget: RequestBudget | None = None) -> dict:
    budget = budget or RequestBudget()
    url = str(eligibility.get("url") or candidate.get("url") or "")
    try:
        _origin(url)
        mode = eligibility.get("contact_mode")
        if mode == "direct_a2a":
            interface = Interface(url, protocol_version(candidate.get("protocolVersion") or "0.3"))
            card = {}
        elif mode == "agent_card":
            fetched = await public_json_request("GET", url, budget)
            if fetched.get("error") or fetched.get("status") != 200:
                return {"ok": False, "reason": fetched.get("error") or "agent_card_http_" + str(fetched.get("status")), "post_started": False}
            card = fetched.get("body")
            interface = select_interface(card, url)
        else:
            raise ValueError("unsupported_contact_mode")
        return {"ok": True, "endpoint": interface.url, "mode": mode,
                "interface": {"url": interface.url, "version": interface.version, "tenant": interface.tenant},
                "card": {"name": str(card.get("name") or "")[:180], "protocolVersion": interface.version}}
    except (ValueError, TypeError) as exc:
        return {"ok": False, "reason": str(exc)[:160], "post_started": False}


async def exchange_peer(interface: Interface, question: str, prior: dict | None = None, budget: RequestBudget | None = None) -> dict:
    budget = budget or RequestBudget()
    prior = prior or {}
    base = {"ok": False, "quality_ok": False, "response": {"text": ""}, "transport": "direct_a2a_" + interface.version,
            "protocol_version": interface.version, "protocol_ok": False, "peer_state": "NOT_SENT", "post_started": False,
            "http_response_received": False, "peer_context": {}, "delivery_unknown": False}
    try:
        _origin(interface.url)
        same = (
            prior.get("endpoint") == interface.url
            and prior.get("protocol_version") == interface.version
            and prior.get("tenant") == interface.tenant
        )
        context_id = prior.get("context_id") if same and _valid_id(prior.get("context_id")) else None
        task_id = prior.get("task_id") if same and _valid_id(prior.get("task_id")) else None
        state = prior.get("state") if same else None
        if state in {"AUTH_REQUIRED", "PAYMENT_REQUIRED"}:
            base["peer_state"] = state
            return base
        polling = bool(task_id and state in {"SUBMITTED", "WORKING"})
        if polling:
            payload = {"jsonrpc": "2.0", "id": str(uuid4()), "method": "GetTask" if interface.version == "1.0" else "tasks/get", "params": {"id": task_id, "historyLength": 0}}
            headers = {"A2A-Version": interface.version, "Content-Type": "application/json"}
        else:
            payload, headers = send_request(interface, question, context_id=context_id,
                                            task_id=task_id if state == "INPUT_REQUIRED" else None)
        base["rpc_method"] = payload["method"]
        base["request_id"] = payload["id"]
        base["sent_context_id"] = context_id
        base["sent_task_id"] = task_id if state == "INPUT_REQUIRED" or polling else None
        response = await public_json_request("POST", interface.url, budget, payload, headers)
        base.update(post_started=response.get("request_started") is True, http_response_received=bool(response.get("response_received")),
                    status=response.get("status"), delivery_unknown=response.get("request_started") is None or (bool(response.get("request_started")) and not response.get("response_received")))
        if response.get("error"):
            base.update(peer_state="TRANSPORT_ERROR", quality_reason=response["error"])
            return base
        body = response.get("body")
        if polling and interface.version == "1.0" and isinstance(body, dict) and isinstance(body.get("result"), dict):
            body = {**body, "result": {"task": body["result"]}}
        parsed = parse_reply(body, version=interface.version, request_id=payload["id"], http_status=response.get("status") or 0)
        if parsed.get("protocol_ok") and context_id and parsed.get("context_id") and parsed["context_id"] != context_id:
            parsed.update(protocol_ok=False, state="CONTEXT_MISMATCH", text="")
        if polling and parsed.get("protocol_ok") and parsed.get("task_id") != task_id:
            parsed.update(protocol_ok=False, state="TASK_MISMATCH", text="")
        refusal = explicit_peer_refusal(parsed["text"]) if parsed["protocol_ok"] else None
        if refusal:
            parsed["state"] = refusal
        base.update(protocol_ok=parsed["protocol_ok"], peer_state=parsed["state"], response={"text": parsed["text"]})
        if parsed["protocol_ok"] or parsed["state"] in {"AUTH_REQUIRED", "PAYMENT_REQUIRED"}:
            base["peer_context"] = {"endpoint": interface.url, "protocol_version": interface.version,
                                    "tenant": interface.tenant,
                                    "context_id": parsed.get("context_id") or context_id,
                                    "task_id": parsed.get("task_id"), "state": parsed["state"]}
        base["ok"] = parsed["protocol_ok"] and parsed["state"] in {"MESSAGE", "COMPLETED", "INPUT_REQUIRED"}
        text = parsed["text"].strip()
        echo = bool(text and (text == question.strip() or (len(question) > 60 and question.strip() in text)))
        base["quality_ok"] = bool(base["ok"] and len(text) >= 40 and not echo)
        base["quality_reason"] = "candidate_response_requires_existing_interview_gate" if base["quality_ok"] else ("prompt_echo" if echo else parsed["state"])
        return base
    except (ValueError, TypeError) as exc:
        base["quality_reason"] = str(exc)[:160]
        return base


def explicit_peer_refusal(text: str) -> str | None:
    """Recognize an explicit refusal, including the observed JSON-as-text envelope.

    A peer's payment claim is not an independently verified price. It is still a
    stop condition. General research mentioning payments does not trigger this.
    """
    value=str(text or "").strip()
    try:
        data=json.loads(value)
    except (ValueError,TypeError):
        data=None
    if isinstance(data,dict):
        fields=[k for k in ("output","text","response") if isinstance(data.get(k),str)]
        if len(fields)==1:
            value=data[fields[0]].strip()
    match=re.match(r"^(PAYMENT_REQUIRED|AUTH_REQUIRED)\b",value,re.I)
    return match[1].upper() if match else None
