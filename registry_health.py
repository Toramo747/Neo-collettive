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
CLASSIFICATION_VERSION = 2

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
        elif other_remotes:
            access_class = "remote_unverifiable_transport"
        elif packages:
            access_class = "package_only"
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


def is_opted_out(server: dict[str, Any], values: set[str]) -> bool:
    if str(server.get("name") or "") in values:
        return True
    for remote in server.get("remotes") or []:
        if isinstance(remote, dict) and str(remote.get("url") or "") in values:
            return True
    return False


def classify_verification(result: dict[str, Any], classification_version: int = CLASSIFICATION_VERSION) -> str:
    """Versioned classification. v1 required discovery; v2 treats it as metadata."""
    version=int(classification_version)
    if version not in {1,2}:
        raise ValueError("unsupported_classification_version")
    checks=result.get("checks") if isinstance(result.get("checks"),dict) else {}
    init=checks.get("initialize") if isinstance(checks.get("initialize"),dict) else {}
    tools=checks.get("tools_list") if isinstance(checks.get("tools_list"),dict) else {}
    discovery=checks.get("discovery") if isinstance(checks.get("discovery"),dict) else {}
    status=init.get("http_status")
    if status is None:
        http=checks.get("http") if isinstance(checks.get("http"),dict) else {}
        status=http.get("status")
    try: code=int(status)
    except Exception: code=0
    if code in {401,403}: return "AUTH_REQUIRED"
    if 500 <= code <= 599: return "SERVER_ERROR"
    if init.get("ok") is True:
        invalid=int(tools.get("invalid_input_schemas") or 0)
        protocol_ok=tools.get("ok") is True and invalid==0 and not result.get("errors")
        if protocol_ok and (version==2 or discovery.get("present") is True):
            return "OK"
        return "OK_WITH_ISSUES"
    errors=set(str(x) for x in (result.get("errors") or []))
    unreachable={"dns_error","dns_no_results","transport_error","request_error","blocked_host","blocked_ip","blocked_resolved_ip"}
    if errors & unreachable or code==0: return "UNREACHABLE"
    return "NOT_MCP"


def classify_compact_probe(probe: dict[str, Any], classification_version: int) -> str:
    """Reclassify a persisted compact probe without network access."""
    version=int(classification_version)
    if version not in {1,2}: raise ValueError("unsupported_classification_version")
    checks=probe.get("checks") if isinstance(probe.get("checks"),dict) else {}
    init=checks.get("initialize") if isinstance(checks.get("initialize"),dict) else {}
    summary=probe.get("summary") if isinstance(probe.get("summary"),dict) else {}
    try: code=int(probe.get("http_status") or init.get("http_status") or 0)
    except Exception: code=0
    if code in {401,403}: return "AUTH_REQUIRED"
    if 500 <= code <= 599: return "SERVER_ERROR"
    errors=set(str(x) for x in (probe.get("errors") or []))
    if init.get("ok") is True:
        protocol_ok=int(summary.get("invalid_input_schemas") or 0)==0 and not errors
        if protocol_ok and (version==2 or summary.get("discovery_present") is True):
            return "OK"
        return "OK_WITH_ISSUES"
    unreachable={"dns_error","dns_no_results","transport_error","request_error","blocked_host","blocked_ip","blocked_resolved_ip"}
    if errors & unreachable or code==0: return "UNREACHABLE"
    return "NOT_MCP"


def final_category_for_version(probe1: dict[str, Any], probe2: dict[str, Any] | None, classification_version: int) -> str:
    first=classify_compact_probe(probe1,classification_version)
    if not probe2: return first
    second=classify_compact_probe(probe2,classification_version)
    return first if first==second else "INTERMITTENT"


def derived_classification_view(rows: list[dict[str, Any]], classification_version: int) -> dict[str, Any]:
    version=int(classification_version)
    categories=Counter()
    servers=[]
    for row in rows:
        if row.get("opted_out") or not isinstance(row.get("probe1"),dict): continue
        probe2=row.get("probe2") if isinstance(row.get("probe2"),dict) else None
        category=final_category_for_version(row["probe1"],probe2,version)
        categories[category]+=1
        probe=probe2 or row["probe1"]
        summary=probe.get("summary") if isinstance(probe.get("summary"),dict) else {}
        servers.append({
            "name":row.get("name"),"version":row.get("version"),"remote_url":row.get("remote_url"),
            "category":category,"classification_version":version,
            "discovery_present":summary.get("discovery_present") is True,"final":bool(row.get("final")),
        })
    total=len(servers)
    return {
        "classification_version":version,"scanned":total,
        "categories":{k:{"count":int(v),"percent_of_scanned":round(100.0*v/total,2) if total else 0.0} for k,v in sorted(categories.items())},
        "servers":servers,
    }

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
    initialize_latencies: list[float] = []
    tools_list_latencies: list[float] = []
    discovery_latencies: list[float] = []
    legacy_total_latencies: list[float] = []
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
        init_latency=summary.get("initialize_latency_ms")
        tools_latency=summary.get("tools_list_latency_ms")
        discovery_rows=summary.get("discovery_latency_ms") if isinstance(summary.get("discovery_latency_ms"),list) else []
        legacy_total=summary.get("total_observed_latency_ms")
        if isinstance(init_latency,(int,float)): initialize_latencies.append(float(init_latency))
        if isinstance(tools_latency,(int,float)): tools_list_latencies.append(float(tools_latency))
        discovery_latencies.extend(float(x) for x in discovery_rows if isinstance(x,(int,float)))
        if isinstance(legacy_total,(int,float)): legacy_total_latencies.append(float(legacy_total))
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
        "classification_version": CLASSIFICATION_VERSION,
        "categories": category_payload,
        "protocol_versions": dict(protocols),
        "invalid_input_schemas": broken_schemas,
        "discovery_present": discovery_present,
        "tls_failures": tls_failures,
        "latency_ms": {
            "metric":"initialize",
            "median":round(statistics.median(initialize_latencies),2) if initialize_latencies else None,
            "p90":percentile(initialize_latencies,0.90),"samples":len(initialize_latencies),
        },
        "latency_breakdown_ms": {
            "initialize":{"median":round(statistics.median(initialize_latencies),2) if initialize_latencies else None,"p90":percentile(initialize_latencies,0.90),"samples":len(initialize_latencies)},
            "tools_list":{"median":round(statistics.median(tools_list_latencies),2) if tools_list_latencies else None,"p90":percentile(tools_list_latencies,0.90),"samples":len(tools_list_latencies)},
            "discovery_request":{"median":round(statistics.median(discovery_latencies),2) if discovery_latencies else None,"p90":percentile(discovery_latencies,0.90),"samples":len(discovery_latencies)},
            "legacy_total_observed":{"median":round(statistics.median(legacy_total_latencies),2) if legacy_total_latencies else None,"p90":percentile(legacy_total_latencies,0.90),"samples":len(legacy_total_latencies)},
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


def _fmt_pct(count: int, total: int) -> str:
    return f"{(100.0*count/total):.1f}%" if total else "0.0%"


def render_report(summary: dict[str, Any], scan_date: str) -> str:
    """Render an aggregate-only English report draft."""
    scanned=int(summary.get("scanned") or 0)
    scope=str(summary.get("scope") or "FULL").upper()
    is_sample=scope=="SAMPLE"
    sample_size=int(summary.get("sample_size") or scanned)
    categories=summary.get("categories") if isinstance(summary.get("categories"),dict) else {}
    def count(name: str) -> int:
        row=categories.get(name)
        return int((row or {}).get("count") or 0) if isinstance(row,dict) else 0

    protocols=summary.get("protocol_versions") if isinstance(summary.get("protocol_versions"),dict) else {}
    protocol_rows=sorted(protocols.items(),key=lambda kv:(-int(kv[1]),str(kv[0])))
    protocol_text=", ".join(f"`{k}`: {int(v)}" for k,v in protocol_rows) or "No negotiated protocol version recorded."
    lat=summary.get("latency_ms") if isinstance(summary.get("latency_ms"),dict) else {}
    discovery=int(summary.get("discovery_present") or 0)
    invalid=int(summary.get("invalid_input_schemas") or 0)
    tls_failures=int(summary.get("tls_failures") or 0)

    category_lines=[]
    for name in FINAL_CATEGORIES:
        n=count(name)
        category_lines.append(f"| {name} | {n} | {_fmt_pct(n,scanned)} |")

    if is_sample:
        title=f"# MCP Registry Health Sample Report — {scan_date}"
        scope_notice=(
            f"**SAMPLE ONLY — {sample_size} Registry remotes. These results describe only the sampled servers "
            "and must not be interpreted or published as statistics for the entire MCP Registry.**"
        )
        census=f"""## Sample definition

- Scope: **SAMPLE**
- Sample size: **{sample_size}**
- Recorded random seed: **{summary.get('sample_seed')}**
- Remote population visible in the Registry snapshot: **{int(summary.get('sample_population_remote_count') or 0)}**
- Sampling method: randomized order with the recorded seed; observations stop at the configured time budget.
"""
        findings=[
            f"Within this {sample_size}-server sample, {count('OK')} were classified OK and {count('AUTH_REQUIRED')} required authentication.",
            f"Discovery metadata was observed for {discovery} of {scanned} sampled remotes ({_fmt_pct(discovery,scanned)}).",
            f"The sample observed {invalid} invalid tool input schemas and {tls_failures} TLS-validation failures.",
            f"Observed sample latency had a median of {lat.get('median')} ms and p90 of {lat.get('p90')} ms across {int(lat.get('samples') or 0)} samples.",
        ]
        category_heading="## Sample remote-health categories"
        share_heading="Share of sampled remotes"
    else:
        title=f"# MCP Registry Health Report — {scan_date}"
        scope_notice="This report summarizes a read-only GitHub Actions measurement of the official MCP Registry. It contains aggregate results only; no server is named negatively."
        census=f"""## Registry census

- Active/latest servers: **{int(summary.get('servers_total') or 0)}**
- HTTPS streamable-http remotes: **{int(summary.get('remote_verifiable') or 0)}**
- Package-only entries: **{int(summary.get('package_only') or 0)}**
- Other remote transports not verified: **{int(summary.get('remote_unverifiable_transport') or 0)}**
- Metadata-only entries: **{int(summary.get('metadata_only') or 0)}**
- Opted out of probing: **{int(summary.get('opted_out') or 0)}**
"""
        findings=[
            f"{int(summary.get('remote_verifiable') or 0)} of {int(summary.get('servers_total') or 0)} active/latest Registry servers declared a remotely verifiable HTTPS streamable-http endpoint.",
            f"{count('OK')} scanned remotes were classified OK after the two-probe policy; {count('AUTH_REQUIRED')} required authentication and were counted separately from downtime.",
            f"Discovery metadata was observed for {discovery} of {scanned} scanned remotes ({_fmt_pct(discovery,scanned)}).",
            f"The scan observed {invalid} invalid tool input schemas and {tls_failures} TLS-validation failures across the final observations.",
            f"Observed aggregate request latency had a median of {lat.get('median')} ms and p90 of {lat.get('p90')} ms across {int(lat.get('samples') or 0)} samples.",
        ]
        category_heading="## Final remote-health categories"
        share_heading="Share of scanned remotes"

    return f"""{title}

**Draft — not published externally.**

{scope_notice}

{census}
{category_heading}

| Category | Count | {share_heading} |
|---|---:|---:|
{chr(10).join(category_lines)}

## Protocol and conformance observations

- Negotiated protocol versions: {protocol_text}
- Invalid tool input schemas observed: **{invalid}**
- Discovery document present: **{discovery}/{scanned} ({_fmt_pct(discovery,scanned)})**
- TLS-validation failures: **{tls_failures}**
- Aggregate observed latency: median **{lat.get('median')} ms**, p90 **{lat.get('p90')} ms**

## Key findings

""" + "\n".join(f"- {x}" for x in findings) + f"""

## Methodology and data

- [Methodology](../registry-health/methodology.md)
- [JSON dataset](../../data/registry-health/{scan_date}/registry-health.json)
- [CSV dataset](../../data/registry-health/{scan_date}/registry-health.csv)
- [Registry snapshot](../../data/registry-health/{scan_date}/registry-snapshot.json)

Dataset license: CC BY 4.0, attribution to Andrea Gava / MYCELIX. Code remains under its existing BUSL-1.1 license.
"""


def render_social_draft(summary: dict[str, Any], scan_date: str) -> str:
    scanned=int(summary.get("scanned") or 0)
    scope=str(summary.get("scope") or "FULL").upper()
    if scope=="SAMPLE":
        size=int(summary.get("sample_size") or scanned)
        return "\n".join([
            f"MCP Registry Health SAMPLE — {scan_date} [DRAFT — NOT PUBLISHED]",
            f"Time-bounded randomized sample: {size} Registry remotes; seed recorded in the dataset.",
            f"{scanned} sampled remotes were evaluated read-only from GitHub Actions with no tool calls and no credentials.",
            "Results apply only to this sample and are not statistics for the entire MCP Registry.",
            "Non-OK results require a second observation at least six hours later before the sample becomes FINAL.",
        ]) + "\n"
    remote=int(summary.get("remote_verifiable") or 0)
    total=int(summary.get("servers_total") or 0)
    return "\n".join([
        f"MCP Registry Health Report — {scan_date} [DRAFT — NOT PUBLISHED]",
        f"We measured {total} active/latest Registry entries, including {remote} remotely verifiable HTTPS MCP servers.",
        f"{scanned} remotes were evaluated read-only from GitHub Actions with no tool calls and no credentials.",
        "Non-OK results use a second observation at least six hours later; authenticated endpoints are counted separately from downtime.",
        "Methodology and CC BY 4.0 dataset are prepared for review before any external publication.",
    ]) + "\n"

