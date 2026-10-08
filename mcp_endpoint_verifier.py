# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Andrea Gava
"""Read-only MCP endpoint verification with strict SSRF controls.

Remote bytes are always treated as untrusted data. This module never invokes
remote tools and never forwards caller authentication headers or cookies.
"""
from __future__ import annotations

import asyncio
import hashlib
import ipaddress
import json
import socket
import time
from collections import Counter, defaultdict, deque
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote, urljoin, urlparse

import httpx

OFFICIAL_REGISTRY = "https://registry.modelcontextprotocol.io"
MAX_REDIRECTS = 3
MAX_RESPONSE_BYTES = 256 * 1024
CONNECT_TIMEOUT = 5.0
READ_TIMEOUT = 8.0
PER_CALLER_LIMIT = 10
GLOBAL_LIMIT = 60
RATE_WINDOW_SECONDS = 60.0

_BLOCKED_HOSTS = {
    "localhost",
    "localhost.localdomain",
    "metadata.google.internal",
    "metadata.azure.internal",
    "instance-data.ec2.internal",
}
_BLOCKED_HOST_SUFFIXES = (".local", ".internal")


def _blocked_hostname(host: str) -> bool:
    value = str(host or "").strip().lower().rstrip(".")
    return value in _BLOCKED_HOSTS or any(value.endswith(suffix) for suffix in _BLOCKED_HOST_SUFFIXES)
_GLOBAL_CALLS: deque[float] = deque()
_CALLER_CALLS: dict[str, deque[float]] = defaultdict(deque)
def _new_metrics() -> dict[str, Any]:
    return {
        "calls": 0,
        "live": 0,
        "not_live": 0,
        "rate_limited": 0,
        "error_types": Counter(),
        "domains": defaultdict(lambda: {"checks": 0, "live": 0, "not_live": 0}),
    }


_METRICS = _new_metrics()  # External/public verify_mcp_endpoint usage only.
_INTERNAL_METRICS = _new_metrics()  # GitHub Actions health scans; never commercial demand.


class RequestPacer:
    """Shared request-level concurrency and per-host pacing for bounded scans."""

    def __init__(self, max_concurrency: int = 4, per_host: int = 1, min_host_interval: float = 1.0):
        self._global = asyncio.Semaphore(max(1, int(max_concurrency)))
        self._per_host_limit = max(1, int(per_host))
        self._host_semaphores: dict[str, asyncio.Semaphore] = {}
        self._last_request: dict[str, float] = {}
        self._guard = asyncio.Lock()
        self.min_host_interval = max(0.0, float(min_host_interval))

    async def _host_semaphore(self, host: str) -> asyncio.Semaphore:
        async with self._guard:
            if host not in self._host_semaphores:
                self._host_semaphores[host] = asyncio.Semaphore(self._per_host_limit)
            return self._host_semaphores[host]

    @asynccontextmanager
    async def slot(self, host: str):
        host = str(host or "unknown").lower()
        sem = await self._host_semaphore(host)
        async with self._global:
            async with sem:
                async with self._guard:
                    last = self._last_request.get(host)
                if last is not None:
                    wait = self.min_host_interval - (time.monotonic() - last)
                    if wait > 0:
                        await asyncio.sleep(wait)
                try:
                    yield
                finally:
                    async with self._guard:
                        self._last_request[host] = time.monotonic()


@asynccontextmanager
async def _unpaced_slot():
    yield


class VerificationError(RuntimeError):
    def __init__(self, code: str, detail: str = ""):
        self.code = code
        self.detail = detail
        super().__init__(code + (": " + detail if detail else ""))


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _hostname(url: str) -> str:
    return (urlparse(url).hostname or "").lower().rstrip(".")


def _blocked_ip(ip_text: str) -> bool:
    try:
        ip = ipaddress.ip_address(ip_text)
    except ValueError:
        return True
    # Fail closed: only globally routable addresses are eligible. This also
    # blocks RFC1918, loopback, link-local, CGNAT/shared space, documentation
    # ranges, IPv6 ULA and cloud metadata/link-local addresses.
    return not bool(ip.is_global)


async def resolve_public_ips(host: str) -> list[str]:
    if not host:
        raise VerificationError("missing_host")
    host_low = host.lower().rstrip(".")
    if _blocked_hostname(host_low):
        raise VerificationError("blocked_host", host_low)
    try:
        direct = ipaddress.ip_address(host_low)
    except ValueError:
        direct = None
    if direct is not None:
        if _blocked_ip(str(direct)):
            raise VerificationError("blocked_ip", str(direct))
        return [str(direct)]

    try:
        rows = await asyncio.to_thread(socket.getaddrinfo, host_low, 443, type=socket.SOCK_STREAM)
    except Exception as exc:
        raise VerificationError("dns_error", type(exc).__name__) from exc
    ips = sorted({str(row[4][0]) for row in rows if row and row[4]})
    if not ips:
        raise VerificationError("dns_no_results", host_low)
    blocked = [ip for ip in ips if _blocked_ip(ip)]
    if blocked:
        raise VerificationError("blocked_resolved_ip", ",".join(blocked[:4]))
    return ips


async def validate_public_https(url: str) -> dict[str, Any]:
    try:
        parsed = urlparse(str(url or "").strip())
    except Exception as exc:
        raise VerificationError("invalid_url", type(exc).__name__) from exc
    if parsed.scheme.lower() != "https":
        raise VerificationError("https_required")
    if parsed.username or parsed.password:
        raise VerificationError("userinfo_forbidden")
    if not parsed.hostname:
        raise VerificationError("missing_host")
    if parsed.port not in (None, 443):
        # Public non-443 HTTPS ports are valid, but this verifier deliberately
        # narrows the outbound surface to the standard TLS port.
        raise VerificationError("nonstandard_port_forbidden", str(parsed.port))
    ips = await resolve_public_ips(parsed.hostname)
    return {"url": parsed.geturl(), "host": parsed.hostname.lower(), "resolved_ips": ips}


def caller_bucket(value: str | None) -> str:
    raw = str(value or "anonymous-session")
    return hashlib.sha256(raw.encode("utf-8", "replace")).hexdigest()[:16]


def _trim_window(q: deque[float], now: float) -> None:
    cutoff = now - RATE_WINDOW_SECONDS
    while q and q[0] <= cutoff:
        q.popleft()


def consume_rate_limit(bucket: str) -> None:
    now = time.monotonic()
    _trim_window(_GLOBAL_CALLS, now)
    for stale_bucket in list(_CALLER_CALLS):
        _trim_window(_CALLER_CALLS[stale_bucket], now)
        if not _CALLER_CALLS[stale_bucket]:
            _CALLER_CALLS.pop(stale_bucket, None)
    caller = _CALLER_CALLS[bucket]
    _trim_window(caller, now)
    if len(_GLOBAL_CALLS) >= GLOBAL_LIMIT:
        _METRICS["rate_limited"] += 1
        raise VerificationError("rate_limited_global")
    if len(caller) >= PER_CALLER_LIMIT:
        _METRICS["rate_limited"] += 1
        raise VerificationError("rate_limited_caller")
    _GLOBAL_CALLS.append(now)
    caller.append(now)


def _reset_metrics(metrics: dict[str, Any]) -> None:
    metrics["calls"] = 0
    metrics["live"] = 0
    metrics["not_live"] = 0
    metrics["rate_limited"] = 0
    metrics["error_types"].clear()
    metrics["domains"].clear()


def reset_runtime_state_for_tests() -> None:
    _GLOBAL_CALLS.clear()
    _CALLER_CALLS.clear()
    _reset_metrics(_METRICS)
    _reset_metrics(_INTERNAL_METRICS)


def _metrics_snapshot(metrics: dict[str, Any], scope: str) -> dict[str, Any]:
    return {
        "calls": int(metrics["calls"]),
        "live": int(metrics["live"]),
        "not_live": int(metrics["not_live"]),
        "rate_limited": int(metrics["rate_limited"]),
        "error_types": dict(metrics["error_types"]),
        "domains": {k: dict(v) for k, v in metrics["domains"].items()},
        "scope": scope,
        "privacy": "anonymous aggregate metrics only; no caller IP or personal identifier stored",
        "payment_signal": False,
    }


def usage_metrics_snapshot() -> dict[str, Any]:
    """External/public tool usage only. Internal registry scans are excluded."""
    return _metrics_snapshot(_METRICS, "external")


def internal_usage_metrics_snapshot() -> dict[str, Any]:
    return _metrics_snapshot(_INTERNAL_METRICS, "internal_registry_health")


def _record_usage(domain: str, live: bool, errors: list[str], *, usage_scope: str = "external") -> None:
    metrics = _INTERNAL_METRICS if usage_scope == "internal_registry_health" else _METRICS
    metrics["calls"] += 1
    metrics["live" if live else "not_live"] += 1
    row = metrics["domains"][domain or "unknown"]
    row["checks"] += 1
    row["live" if live else "not_live"] += 1
    for code in sorted(set(errors)):
        metrics["error_types"][code] += 1


async def _bounded_request(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    *,
    json_body: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    max_redirects: int = MAX_REDIRECTS,
    user_agent: str | None = None,
    request_pacer: RequestPacer | None = None,
    request_counts: Counter | None = None,
) -> dict[str, Any]:
    current = url
    history: list[dict[str, Any]] = []
    clean_headers = {
        "Accept": "application/json, text/event-stream",
        "User-Agent": str(user_agent or "MYCELIX-MCP-Verifier/1.0"),
    }
    if method.upper() == "POST":
        clean_headers["Content-Type"] = "application/json"
    for k, v in (headers or {}).items():
        lk = k.lower()
        if lk in {"mcp-session-id", "mcp-protocol-version"}:
            clean_headers[k] = v

    for hop in range(max_redirects + 1):
        target = await validate_public_https(current)
        started = time.perf_counter()
        try:
            slot = request_pacer.slot(target["host"]) if request_pacer is not None else _unpaced_slot()
            async with slot:
                if request_counts is not None:
                    request_counts[target["host"]] += 1
                async with client.stream(
                    method.upper(),
                    current,
                    json=json_body if method.upper() == "POST" else None,
                    headers=clean_headers,
                    follow_redirects=False,
                ) as response:
                    latency_ms = round((time.perf_counter() - started) * 1000, 2)
                    if response.status_code in {301, 302, 303, 307, 308}:
                        location = response.headers.get("location")
                        if not location:
                            raise VerificationError("redirect_without_location")
                        if hop >= max_redirects:
                            raise VerificationError("too_many_redirects")
                        nxt = urljoin(current, location)
                        await validate_public_https(nxt)
                        history.append({"status": response.status_code, "from": current, "to": nxt})
                        current = nxt
                        continue

                    total = 0
                    chunks: list[bytes] = []
                    async for chunk in response.aiter_bytes():
                        total += len(chunk)
                        if total > MAX_RESPONSE_BYTES:
                            raise VerificationError("response_too_large")
                        chunks.append(chunk)
                    raw = b"".join(chunks)
                    text = raw.decode("utf-8", "replace")
                    return {
                        "url": current,
                        "host": target["host"],
                        "resolved_ips": target["resolved_ips"],
                        "status": response.status_code,
                        "headers": {
                            "content-type": response.headers.get("content-type"),
                            "mcp-session-id": response.headers.get("mcp-session-id"),
                            "mcp-protocol-version": response.headers.get("mcp-protocol-version"),
                        },
                        "body": text,
                        "bytes": total,
                        "latency_ms": latency_ms,
                        "redirects": history,
                    }
        except VerificationError:
            raise
        except httpx.TransportError as exc:
            raise VerificationError("transport_error", type(exc).__name__) from exc
        except Exception as exc:
            raise VerificationError("request_error", type(exc).__name__) from exc
    raise VerificationError("too_many_redirects")


def _json_payload(result: dict[str, Any]) -> dict[str, Any]:
    text = result.get("body") or ""
    ctype = str((result.get("headers") or {}).get("content-type") or "").lower()
    if "text/event-stream" in ctype:
        events = []
        for line in text.splitlines():
            if line.startswith("data:"):
                raw = line[5:].strip()
                try:
                    events.append(json.loads(raw))
                except Exception:
                    pass
        for event in reversed(events):
            if isinstance(event, dict):
                return event
        return {}
    try:
        value = json.loads(text)
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


def _schema_sane(schema: Any) -> bool:
    if not isinstance(schema, dict):
        return False
    if schema.get("type") not in (None, "object"):
        return False
    if "properties" in schema and not isinstance(schema.get("properties"), dict):
        return False
    if "required" in schema and not (
        isinstance(schema.get("required"), list)
        and all(isinstance(x, str) for x in schema.get("required"))
    ):
        return False
    return True


def _extract_registry_server(payload: Any, expected_name: str) -> dict[str, Any] | None:
    if isinstance(payload, dict):
        candidate = payload.get("server") if isinstance(payload.get("server"), dict) else payload
        if isinstance(candidate, dict) and str(candidate.get("name") or "") == expected_name:
            return candidate
        for key in ("servers", "results", "items"):
            rows = payload.get(key)
            if isinstance(rows, list):
                for row in rows:
                    if isinstance(row, dict):
                        srv = row.get("server") if isinstance(row.get("server"), dict) else row
                        if str(srv.get("name") or "") == expected_name:
                            return srv
    if isinstance(payload, list):
        for row in payload:
            if isinstance(row, dict):
                srv = row.get("server") if isinstance(row.get("server"), dict) else row
                if str(srv.get("name") or "") == expected_name:
                    return srv
    return None


async def resolve_registry_name(client: httpx.AsyncClient, name: str) -> dict[str, Any]:
    expected = str(name or "").strip()
    if not expected or "/" not in expected:
        raise VerificationError("invalid_registry_name")
    exact_url = OFFICIAL_REGISTRY + "/v0.1/servers/" + quote(expected, safe="")
    result = await _bounded_request(client, "GET", exact_url)
    payload = _json_payload(result)
    server = _extract_registry_server(payload, expected)
    if server is None:
        # Compatibility with Registry deployments that expose search/list only.
        search_url = OFFICIAL_REGISTRY + "/v0.1/servers?search=" + quote(expected, safe="") + "&limit=20"
        search = await _bounded_request(client, "GET", search_url)
        server = _extract_registry_server(_json_payload(search), expected)
    if server is None:
        raise VerificationError("registry_entry_not_found", expected)
    remotes = server.get("remotes") or []
    urls = [
        str(r.get("url") or "").strip()
        for r in remotes
        if isinstance(r, dict)
        and str(r.get("type") or "").lower() == "streamable-http"
        and str(r.get("url") or "").strip()
    ]
    if not urls:
        raise VerificationError("registry_no_streamable_http_remote", expected)
    return {
        "name": expected,
        "server": server,
        "remote_url": urls[0],
        "remote_urls": urls,
    }


async def _check_discovery(
    client: httpx.AsyncClient,
    target_url: str,
    *,
    user_agent: str | None = None,
    request_pacer: RequestPacer | None = None,
    request_counts: Counter | None = None,
) -> dict[str, Any]:
    parsed = urlparse(target_url)
    origin = f"{parsed.scheme}://{parsed.netloc}"
    candidates = [
        origin + "/.well-known/mcp.json",
        target_url.rstrip("/") + "/server-card",
        origin + "/.well-known/ai-catalog.json",
    ]
    checks = []
    for candidate in candidates:
        try:
            r = await _bounded_request(
                client, "GET", candidate, max_redirects=MAX_REDIRECTS,
                user_agent=user_agent, request_pacer=request_pacer, request_counts=request_counts,
            )
            ok = int(r.get("status") or 0) == 200 and bool((r.get("body") or "").strip())
            checks.append({
                "url": candidate,
                "ok": ok,
                "status": r.get("status"),
                "content_type": (r.get("headers") or {}).get("content-type"),
                "latency_ms": r.get("latency_ms"),
            })
        except VerificationError as exc:
            checks.append({"url": candidate, "ok": False, "error": exc.code})
    return {"present": any(x.get("ok") for x in checks), "checks": checks}


async def verify_endpoint(
    *,
    url: str | None = None,
    registry_name: str | None = None,
    caller: str | None = None,
    client_version: str = "unknown",
    usage_scope: str = "external",
    user_agent: str | None = None,
    request_pacer: RequestPacer | None = None,
    enforce_rate_limit: bool = True,
) -> dict[str, Any]:
    if usage_scope not in {"external", "internal_registry_health"}:
        raise ValueError("invalid_usage_scope")
    bucket = caller_bucket(caller)
    if enforce_rate_limit:
        consume_rate_limit(bucket)
    started_at = _utcnow()
    errors: list[str] = []
    registry: dict[str, Any] | None = None
    requested_url = str(url or "").strip()
    request_counts: Counter = Counter()
    timeout = httpx.Timeout(connect=CONNECT_TIMEOUT, read=READ_TIMEOUT, write=READ_TIMEOUT, pool=CONNECT_TIMEOUT)

    async with httpx.AsyncClient(timeout=timeout, follow_redirects=False, trust_env=False) as client:
        if registry_name:
            try:
                registry = await resolve_registry_name(client, registry_name)
                if not requested_url:
                    requested_url = registry["remote_url"]
            except VerificationError as exc:
                errors.append(exc.code)
                _record_usage("registry:"+str(registry_name), False, errors, usage_scope=usage_scope)
                return {
                    "ok": False,
                    "live": False,
                    "timestamp": started_at,
                    "input": {"url": url, "registry_name": registry_name},
                    "checks": {"registry": {"ok": False, "error": exc.code, "detail": exc.detail}},
                    "errors": errors,
                    "usage_metrics": internal_usage_metrics_snapshot() if usage_scope == "internal_registry_health" else usage_metrics_snapshot(),
                }

        if not requested_url:
            errors.append("url_or_registry_name_required")
            _record_usage("unknown", False, errors, usage_scope=usage_scope)
            return {
                "ok": False,
                "live": False,
                "timestamp": started_at,
                "input": {"url": url, "registry_name": registry_name},
                "checks": {},
                "errors": errors,
                "usage_metrics": internal_usage_metrics_snapshot() if usage_scope == "internal_registry_health" else usage_metrics_snapshot(),
            }

        domain = _hostname(requested_url) or "unknown"
        checks: dict[str, Any] = {}
        try:
            safety = await validate_public_https(requested_url)
            checks["dns_ssrf"] = {"ok": True, "host": safety["host"], "resolved_ips": safety["resolved_ips"]}
        except VerificationError as exc:
            errors.append(exc.code)
            checks["dns_ssrf"] = {"ok": False, "error": exc.code, "detail": exc.detail}
            _record_usage(domain, False, errors, usage_scope=usage_scope)
            return {
                "ok": False,
                "live": False,
                "timestamp": started_at,
                "input": {"url": requested_url, "registry_name": registry_name},
                "registry": registry,
                "checks": checks,
                "errors": errors,
                "comparison": "registered_but_not_reachable" if registry else None,
                "usage_metrics": internal_usage_metrics_snapshot() if usage_scope == "internal_registry_health" else usage_metrics_snapshot(),
            }

        initialize = {
            "jsonrpc": "2.0",
            "id": "verify-init",
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-11-25",
                "capabilities": {},
                "clientInfo": {"name": "MYCELIX verify_mcp_endpoint", "version": client_version},
            },
        }
        session_id = None
        negotiated = None
        server_info = None
        init_ok = False
        try:
            init = await _bounded_request(
                client, "POST", requested_url, json_body=initialize,
                user_agent=user_agent, request_pacer=request_pacer, request_counts=request_counts,
            )
            checks["tls"] = {
                "ok": True,
                "certificate_validation": "system_ca_via_httpx",
                "host": _hostname(str(init.get("url") or requested_url)),
            }
            checks["http"] = {
                "ok": True,
                "status": init.get("status"),
                "latency_ms": init.get("latency_ms"),
                "redirects": init.get("redirects"),
                "final_url": init.get("url"),
            }
            init_payload = _json_payload(init)
            result = init_payload.get("result") if isinstance(init_payload.get("result"), dict) else {}
            negotiated = result.get("protocolVersion")
            server_info = result.get("serverInfo")
            init_ok = int(init.get("status") or 0) in range(200, 300) and bool(result)
            session_id = (init.get("headers") or {}).get("mcp-session-id")
            checks["initialize"] = {
                "ok": init_ok,
                "http_status": init.get("status"),
                "protocol_version": negotiated,
                "server_info": server_info,
                "latency_ms": init.get("latency_ms"),
            }
            if not init_ok:
                errors.append("initialize_failed")
        except VerificationError as exc:
            checks["tls"] = {"ok": False, "error": exc.code, "detail": exc.detail}
            checks["http"] = {"ok": False, "error": exc.code, "detail": exc.detail}
            checks["initialize"] = {"ok": False, "error": exc.code}
            errors.append(exc.code)

        tools_ok = False
        tools_count = 0
        valid_schemas = 0
        invalid_schemas = 0
        if init_ok:
            headers = {}
            if session_id:
                headers["Mcp-Session-Id"] = str(session_id)
            if negotiated:
                headers["MCP-Protocol-Version"] = str(negotiated)
            try:
                initialized = {
                    "jsonrpc": "2.0",
                    "method": "notifications/initialized",
                    "params": {},
                }
                await _bounded_request(
                    client, "POST", requested_url, json_body=initialized, headers=headers,
                    user_agent=user_agent, request_pacer=request_pacer, request_counts=request_counts,
                )
            except VerificationError:
                # Some stateless implementations legitimately ignore this notification.
                pass
            try:
                listing = {
                    "jsonrpc": "2.0",
                    "id": "verify-tools",
                    "method": "tools/list",
                    "params": {},
                }
                listed = await _bounded_request(
                    client, "POST", requested_url, json_body=listing, headers=headers,
                    user_agent=user_agent, request_pacer=request_pacer, request_counts=request_counts,
                )
                payload = _json_payload(listed)
                result = payload.get("result") if isinstance(payload.get("result"), dict) else {}
                tools = result.get("tools") if isinstance(result.get("tools"), list) else []
                tools_count = len(tools)
                valid_schemas = sum(1 for tool in tools if isinstance(tool, dict) and _schema_sane(tool.get("inputSchema")))
                invalid_schemas = tools_count - valid_schemas
                declared_tools = []
                for tool in tools[:64]:
                    if not isinstance(tool, dict):
                        continue
                    name = " ".join(str(tool.get("name") or "").split())[:120]
                    description = " ".join(str(tool.get("description") or "").split())[:400]
                    if name:
                        declared_tools.append({"name": name, "description": description})
                tools_ok = int(listed.get("status") or 0) in range(200, 300) and invalid_schemas == 0
                checks["tools_list"] = {
                    "ok": tools_ok,
                    "http_status": listed.get("status"),
                    "tool_count": tools_count,
                    "valid_input_schemas": valid_schemas,
                    "invalid_input_schemas": invalid_schemas,
                    "declared_tools": declared_tools,
                    "latency_ms": listed.get("latency_ms"),
                }
                if not tools_ok:
                    errors.append("tools_list_or_schema_invalid")
            except VerificationError as exc:
                checks["tools_list"] = {"ok": False, "error": exc.code, "detail": exc.detail}
                errors.append(exc.code)
        else:
            checks["tools_list"] = {"ok": False, "skipped": "initialize_failed"}

        discovery = await _check_discovery(
            client, requested_url, user_agent=user_agent,
            request_pacer=request_pacer, request_counts=request_counts,
        )
        checks["discovery"] = discovery
        live = bool(init_ok)
        comparison = None
        if registry:
            comparison = "registered_and_reachable" if live else "registered_but_not_reachable"
            registry_url = str(registry.get("remote_url") or "")
            if registry_url and requested_url != registry_url:
                comparison = "registered_endpoint_differs_from_checked_url"

        init_latency=checks.get("initialize",{}).get("latency_ms") if isinstance(checks.get("initialize"),dict) else None
        tools_latency=checks.get("tools_list",{}).get("latency_ms") if isinstance(checks.get("tools_list"),dict) else None
        discovery_latencies=[float(row.get("latency_ms")) for row in (discovery.get("checks") or []) if isinstance(row,dict) and isinstance(row.get("latency_ms"),(int,float))]
        latency_values=[]
        if isinstance(init_latency,(int,float)): latency_values.append(float(init_latency))
        if isinstance(tools_latency,(int,float)): latency_values.append(float(tools_latency))
        latency_values.extend(discovery_latencies)

        _record_usage(domain, live, errors, usage_scope=usage_scope)
        return {
            "ok": live and tools_ok,
            "live": live,
            "timestamp": started_at,
            "input": {"url": requested_url, "registry_name": registry_name},
            "registry": registry,
            "comparison": comparison,
            "checks": checks,
            "summary": {
                "protocol_version": negotiated,
                "server_info": server_info,
                "tool_count": tools_count,
                "valid_input_schemas": valid_schemas,
                "invalid_input_schemas": invalid_schemas,
                "discovery_present":discovery.get("present"),
                "initialize_latency_ms":init_latency,
                "tools_list_latency_ms":tools_latency,
                "discovery_latency_ms":discovery_latencies,
                "total_observed_latency_ms":round(sum(latency_values),2),
            },
            "errors": errors,
            "read_only": True,
            "remote_tools_called": False,
            "credentials_forwarded": False,
            "usage_scope": usage_scope,
            "request_counts_by_host": dict(request_counts),
            "usage_metrics": internal_usage_metrics_snapshot() if usage_scope == "internal_registry_health" else usage_metrics_snapshot(),
        }
