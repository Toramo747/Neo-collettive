# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Andrea Gava
"""Official MCP Registry census and health-scan orchestration.

The scanner reuses mcp_endpoint_verifier.verify_endpoint for all endpoint
verification. This module only handles registry pagination, filtering,
classification, aggregation and dataset serialization.
"""
from __future__ import annotations

import asyncio
import csv
import io
import json
import math
import statistics
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

REGISTRY_URL = "https://registry.modelcontextprotocol.io/v0.1/servers"
OFFICIAL_META_KEY = "io.modelcontextprotocol.registry/official"
MAX_CONCURRENCY = 4
PER_HOST_CONCURRENCY = 1
HOST_REQUEST_DELAY_SECONDS = 1.0
LIST_PAGE_LIMIT = 100
OPT_OUT_PATH = Path("data/registry-health/opt-out.txt")

FINAL_CATEGORIES = (
    "OK",
    "OK_WITH_ISSUES",
    "AUTH_REQUIRED",
    "SERVER_ERROR",
    "NOT_MCP",
    "UNREACHABLE",
    "INTERMITTENT",
)


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _official(row: dict[str, Any]) -> dict[str, Any]:
    meta = row.get("_meta") if isinstance(row.get("_meta"), dict) else {}
    value = meta.get(OFFICIAL_META_KEY)
    return value if isinstance(value, dict) else {}


def _server(row: dict[str, Any]) -> dict[str, Any]:
    value = row.get("server")
    return value if isinstance(value, dict) else {}


def _streamable_remotes(server: dict[str, Any]) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for remote in server.get("remotes") or []:
        if not isinstance(remote, dict):
            continue
        rtype = str(remote.get("type") or "").strip().lower()
        url = str(remote.get("url") or "").strip()
        if rtype == "streamable-http" and url.startswith("https://"):
            out.append({"type": rtype, "url": url})
    return out


def _other_remotes(server: dict[str, Any]) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for remote in server.get("remotes") or []:
        if not isinstance(remote, dict):
            continue
        rtype = str(remote.get("type") or "").strip().lower()
        url = str(remote.get("url") or "").strip()
        if url and not (rtype == "streamable-http" and url.startswith("https://")):
            out.append({"type": rtype, "url": url})
    return out


def normalize_registry_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep only active latest records and normalize transport buckets."""
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        server = _server(row)
        official = _official(row)
        name = str(server.get("name") or "").strip()
        if not name or name in seen:
            continue
        if official.get("isLatest") is not True:
            continue
        if str(official.get("status") or "").lower() != "active":
            continue
        seen.add(name)
        remotes = _streamable_remotes(server)
        other_remotes = _other_remotes(server)
        packages = [x for x in (server.get("packages") or []) if isinstance(x, dict)]
        if remotes:
            access_class = "remote"
        elif packages:
            access_class = "package_only"
        elif other_remotes:
            access_class = "remote_unverifiable_transport"
        else:
            access_class = "metadata_only"
        normalized.append({
            "name": name,
            "version": str(server.get("version") or ""),
            "title": str(server.get("title") or ""),
            "access_class": access_class,
            "remotes": remotes,
            "other_remotes": other_remotes,
            "packages": packages,
            "registry_meta": {
                "status": official.get("status"),
                "isLatest": official.get("isLatest"),
                "publishedAt": official.get("publishedAt"),
                "updatedAt": official.get("updatedAt"),
            },
        })
    normalized.sort(key=lambda x: x["name"].lower())
    return normalized


async def fetch_complete_registry(
    client: httpx.AsyncClient,
    *,
    page_limit: int = LIST_PAGE_LIMIT,
) -> dict[str, Any]:
    """Fetch all current latest records using only opaque nextCursor values."""
    page_limit = max(1, min(int(page_limit), 1000))
    cursor: str | None = None
    raw_rows: list[dict[str, Any]] = []
    cursors_seen: set[str] = set()
    page_count = 0
    while True:
        params: dict[str, Any] = {"limit": page_limit, "version": "latest"}
        if cursor:
            params["cursor"] = cursor
        response = await client.get(REGISTRY_URL, params=params)
        response.raise_for_status()
        payload = response.json()
        rows = payload.get("servers") if isinstance(payload, dict) else None
        if not isinstance(rows, list):
            raise RuntimeError("registry_servers_array_missing")
        raw_rows.extend(x for x in rows if isinstance(x, dict))
        page_count += 1
        metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
        nxt = metadata.get("nextCursor")
        if not nxt:
            break
        if not isinstance(nxt, str):
            raise RuntimeError("registry_cursor_not_string")
        if nxt in cursors_seen:
            raise RuntimeError("registry_cursor_loop")
        cursors_seen.add(nxt)
        cursor = nxt

    servers = normalize_registry_rows(raw_rows)
    counts = Counter(x["access_class"] for x in servers)
    return {
        "snapshot_at_utc": utcnow(),
        "source": REGISTRY_URL,
        "filter": {"version": "latest", "status": "active", "isLatest": True},
        "pages": page_count,
        "records_received": len(raw_rows),
        "servers_total": len(servers),
        "remote_verifiable": int(counts.get("remote", 0)),
        "package_only": int(counts.get("package_only", 0)),
        "remote_unverifiable_transport": int(counts.get("remote_unverifiable_transport", 0)),
        "metadata_only": int(counts.get("metadata_only", 0)),
        "servers": servers,
    }


def read_opt_out(path: Path = OPT_OUT_PATH) -> set[str]:
    if not path.exists():
        return set()
    values = set()
    for raw in path.read_text(encoding="utf-8").splitlines():
        value = raw.strip()
        if value and not value.startswith("#"):
            values.add(value)
    return values


def classify_verification(result: dict[str, Any]) -> str:
    checks = result.get("checks") if isinstance(result.get("checks"), dict) else {}
    init = checks.get("initialize") if isinstance(checks.get("initialize"), dict) else {}
    tools = checks.get("tools_list") if isinstance(checks.get("tools_list"), dict) else {}
    discovery = checks.get("discovery") if isinstance(checks.get("discovery"), dict) else {}
    status = init.get("http_status")
    if status is None:
        http = checks.get("http") if isinstance(checks.get("http"), dict) else {}
        status = http.get("status")
    try:
        code = int(status)
    except Exception:
        code = 0

    if code in {401, 403}:
        return "AUTH_REQUIRED"
    if 500 <= code <= 599:
        return "SERVER_ERROR"
    if init.get("ok") is True:
        invalid = int(tools.get("invalid_input_schemas") or 0)
        if tools.get("ok") is True and invalid == 0 and discovery.get("present") is True and not result.get("errors"):
            return "OK"
        return "OK_WITH_ISSUES"

    errors = set(str(x) for x in (result.get("errors") or []))
    unreachable = {
        "dns_error", "dns_no_results", "transport_error", "request_error",
        "blocked_host", "blocked_ip", "blocked_resolved_ip",
    }
    if errors & unreachable or code == 0:
        return "UNREACHABLE"
    return "NOT_MCP"


def final_category(probe1: dict[str, Any], probe2: dict[str, Any] | None) -> str:
    first = str(probe1.get("category") or "")
    if first in {"OK", "AUTH_REQUIRED"} and not probe2:
        return first
    if not probe2:
        return first
    second = str(probe2.get("category") or "")
    return first if first == second else "INTERMITTENT"


def percentile(values: list[float], p: float) -> float | None:
    if not values:
        return None
    seq = sorted(float(x) for x in values)
    if len(seq) == 1:
        return round(seq[0], 2)
    rank = (len(seq) - 1) * p
    lo = math.floor(rank)
    hi = math.ceil(rank)
    if lo == hi:
        return round(seq[lo], 2)
    value = seq[lo] + (seq[hi] - seq[lo]) * (rank - lo)
    return round(value, 2)


def aggregate_dataset(listing: dict[str, Any], rows: list[dict[str, Any]]) -> dict[str, Any]:
    categories = Counter(str(x.get("category") or "UNCLASSIFIED") for x in rows if not x.get("opted_out"))
    protocols = Counter()
    broken_schemas = 0
    discovery_present = 0
    tls_failures = 0
    latencies: list[float] = []
    request_counts: Counter[str] = Counter()
    scanned = 0
    for row in rows:
        if row.get("opted_out"):
            continue
        scanned += 1
        probe = row.get("probe2") or row.get("probe1") or {}
        summary = probe.get("summary") if isinstance(probe.get("summary"), dict) else {}
        checks = probe.get("checks") if isinstance(probe.get("checks"), dict) else {}
        protocol = summary.get("protocol_version")
        if protocol:
            protocols[str(protocol)] += 1
        broken_schemas += int(summary.get("invalid_input_schemas") or 0)
        if summary.get("discovery_present") is True:
            discovery_present += 1
        tls = checks.get("tls") if isinstance(checks.get("tls"), dict) else {}
        if tls and tls.get("ok") is False:
            tls_failures += 1
        latency = summary.get("total_observed_latency_ms")
        if isinstance(latency, (int, float)):
            latencies.append(float(latency))
        for host, count in (probe.get("request_counts_by_host") or {}).items():
            request_counts[str(host)] += int(count or 0)

    category_payload = {
        key: {
            "count": int(count),
            "percent_of_scanned": round((100.0 * count / scanned), 2) if scanned else 0.0,
        }
        for key, count in sorted(categories.items())
    }
    return {
        "generated_at_utc": utcnow(),
        "servers_total": int(listing.get("servers_total") or 0),
        "remote_verifiable": int(listing.get("remote_verifiable") or 0),
        "package_only": int(listing.get("package_only") or 0),
        "remote_unverifiable_transport": int(listing.get("remote_unverifiable_transport") or 0),
        "metadata_only": int(listing.get("metadata_only") or 0),
        "opted_out": sum(1 for x in rows if x.get("opted_out")),
        "scanned": scanned,
        "categories": category_payload,
        "protocol_versions": dict(protocols),
        "invalid_input_schemas": broken_schemas,
        "discovery_present": discovery_present,
        "tls_failures": tls_failures,
        "latency_ms": {
            "median": round(statistics.median(latencies), 2) if latencies else None,
            "p90": percentile(latencies, 0.90),
            "samples": len(latencies),
        },
        "requests_by_host": dict(sorted(request_counts.items())),
    }


def dataset_csv(rows: list[dict[str, Any]]) -> str:
    fields = [
        "name", "version", "remote_url", "category", "opted_out",
        "protocol_version", "tool_count", "valid_input_schemas",
        "invalid_input_schemas", "discovery_present", "tls_valid",
        "latency_ms", "probe1_at_utc", "probe2_at_utc",
    ]
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=fields)
    writer.writeheader()
    for row in rows:
        probe = row.get("probe2") or row.get("probe1") or {}
        summary = probe.get("summary") if isinstance(probe.get("summary"), dict) else {}
        checks = probe.get("checks") if isinstance(probe.get("checks"), dict) else {}
        tls = checks.get("tls") if isinstance(checks.get("tls"), dict) else {}
        writer.writerow({
            "name": row.get("name"),
            "version": row.get("version"),
            "remote_url": row.get("remote_url"),
            "category": row.get("category"),
            "opted_out": bool(row.get("opted_out")),
            "protocol_version": summary.get("protocol_version"),
            "tool_count": summary.get("tool_count"),
            "valid_input_schemas": summary.get("valid_input_schemas"),
            "invalid_input_schemas": summary.get("invalid_input_schemas"),
            "discovery_present": summary.get("discovery_present"),
            "tls_valid": tls.get("ok") if tls else None,
            "latency_ms": summary.get("total_observed_latency_ms"),
            "probe1_at_utc": (row.get("probe1") or {}).get("timestamp"),
            "probe2_at_utc": (row.get("probe2") or {}).get("timestamp"),
        })
    return buf.getvalue()
