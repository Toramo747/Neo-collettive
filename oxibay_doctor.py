# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Andrea Gava
"""OXIBAY Doctor v0.1.

Read-only diagnostic layer over the existing MCP endpoint verifier.
It never calls remote tools and never changes remote or production state.
Semantic checks are limited to declared tool metadata and are therefore
advisory, not proof that a remote tool behaves correctly.
"""
from __future__ import annotations

import re
from typing import Any

import mcp_endpoint_verifier as endpoint_verifier

SCHEMA_VERSION = 1
MAX_EXPECTED_CHARS = 500
MAX_FINDINGS = 20

_STOPWORDS = {
    "about","after","agent","and","are","con","che","come","dal","dalla","delle",
    "del","dei","degli","dell","for","from","gli","into","its","nel","nella","nelle",
    "per","the","this","tool","tools","una","uno","with","your",
}

_SAFETY_ERRORS = {
    "blocked_host","blocked_ip","blocked_resolved_ip","https_required",
    "userinfo_forbidden","nonstandard_port_forbidden","missing_host","invalid_url",
}
_UNREACHABLE_ERRORS = {
    "dns_error","dns_no_results","transport_error","request_error",
}


def _tokens(value: str) -> set[str]:
    text=str(value or "").lower()[:MAX_EXPECTED_CHARS]
    return {
        token for token in re.findall(r"[a-z0-9][a-z0-9._-]{2,}", text)
        if token not in _STOPWORDS
    }


def _declared_catalog(verification: dict[str, Any]) -> list[dict[str, str]]:
    checks=verification.get("checks") if isinstance(verification,dict) else {}
    tools=(checks or {}).get("tools_list") if isinstance(checks,dict) else {}
    rows=(tools or {}).get("declared_tools") if isinstance(tools,dict) else []
    out=[]
    for row in rows if isinstance(rows,list) else []:
        if not isinstance(row,dict):
            continue
        name=" ".join(str(row.get("name") or "").split())[:120]
        description=" ".join(str(row.get("description") or "").split())[:400]
        if name:
            out.append({"name":name,"description":description})
        if len(out)>=64:
            break
    return out


def semantic_declared_capability(
    verification: dict[str, Any],
    expected_capability: str = "",
) -> dict[str, Any]:
    expected=" ".join(str(expected_capability or "").split())[:MAX_EXPECTED_CHARS]
    if not expected:
        return {
            "status":"NOT_REQUESTED",
            "score":None,
            "matched_terms":[],
            "expected_terms":[],
            "basis":"declared_tool_metadata_only",
        }

    expected_terms=_tokens(expected)
    catalog=_declared_catalog(verification)
    if not expected_terms:
        return {
            "status":"INSUFFICIENT_QUERY",
            "score":0.0,
            "matched_terms":[],
            "expected_terms":[],
            "basis":"declared_tool_metadata_only",
        }
    if not catalog:
        return {
            "status":"UNAVAILABLE",
            "score":0.0,
            "matched_terms":[],
            "expected_terms":sorted(expected_terms),
            "basis":"declared_tool_metadata_only",
        }

    declared=" ".join(
        (row["name"]+" "+row["description"]).lower()
        for row in catalog
    )
    matched=sorted(term for term in expected_terms if term in declared)
    score=round(len(matched)/max(1,len(expected_terms)),3)
    if score>=0.5 or len(matched)>=2:
        status="MATCH_INDICATED"
    elif matched:
        status="WEAK_MATCH"
    else:
        status="NO_MATCH_IN_DECLARED_TOOLS"
    return {
        "status":status,
        "score":score,
        "matched_terms":matched[:20],
        "expected_terms":sorted(expected_terms)[:20],
        "basis":"declared_tool_metadata_only",
    }


def diagnose_verification(
    verification: dict[str, Any],
    expected_capability: str = "",
) -> dict[str, Any]:
    data=verification if isinstance(verification,dict) else {}
    checks=data.get("checks") if isinstance(data.get("checks"),dict) else {}
    errors=[str(x) for x in (data.get("errors") or []) if str(x)]
    findings=[]

    dns=checks.get("dns_ssrf") if isinstance(checks.get("dns_ssrf"),dict) else {}
    init=checks.get("initialize") if isinstance(checks.get("initialize"),dict) else {}
    tools=checks.get("tools_list") if isinstance(checks.get("tools_list"),dict) else {}
    discovery=checks.get("discovery") if isinstance(checks.get("discovery"),dict) else {}

    init_status=int(init.get("http_status") or 0)
    invalid_schemas=int(tools.get("invalid_input_schemas") or 0)

    if dns and dns.get("ok") is False:
        err=str(dns.get("error") or (errors[0] if errors else ""))
        if err in _SAFETY_ERRORS:
            status="SAFETY_BLOCKED"
            findings.append("endpoint rejected by outbound safety policy")
        else:
            status="UNREACHABLE"
            findings.append("endpoint could not be reached safely")
    elif init_status in {401,403}:
        status="AUTH_REQUIRED"
        findings.append("endpoint requires authentication before MCP initialize")
    elif init.get("ok") is not True:
        if init_status>=500:
            status="SERVER_ERROR"
            findings.append("server error during MCP initialize")
        elif any(err in _UNREACHABLE_ERRORS for err in errors):
            status="UNREACHABLE"
            findings.append("transport or DNS failure during verification")
        else:
            status="NOT_MCP"
            findings.append("endpoint did not complete a valid MCP initialize")
    elif tools.get("ok") is not True or invalid_schemas>0:
        status="COMPATIBILITY_ISSUE"
        if invalid_schemas:
            findings.append(f"{invalid_schemas} invalid tool input schema(s)")
        else:
            findings.append("tools/list failed or returned an incompatible response")
    else:
        status="HEALTHY_TECHNICAL"

    if discovery and discovery.get("present") is False:
        findings.append("optional discovery metadata not found")

    semantic=semantic_declared_capability(data,expected_capability)
    if status=="HEALTHY_TECHNICAL":
        if semantic["status"]=="NO_MATCH_IN_DECLARED_TOOLS":
            findings.append("declared tools do not visibly match the requested capability")
            recommendation="HOLD_SEMANTIC_REVIEW"
        elif semantic["status"] in {"WEAK_MATCH","UNAVAILABLE","INSUFFICIENT_QUERY"}:
            recommendation="REVIEW_DECLARED_CAPABILITY"
        else:
            recommendation="READY_FOR_BOUNDED_USE"
    else:
        recommendation="HOLD_TECHNICAL"

    return {
        "schema_v":SCHEMA_VERSION,
        "doctor":"OXIBAY Doctor",
        "doctor_version":"0.1",
        "status":status,
        "recommendation":recommendation,
        "findings":findings[:MAX_FINDINGS],
        "semantic":semantic,
        "technical":{
            "live":bool(data.get("live")),
            "ok":bool(data.get("ok")),
            "protocol_version":((data.get("summary") or {}).get("protocol_version") if isinstance(data.get("summary"),dict) else None),
            "tool_count":int(((data.get("summary") or {}).get("tool_count") or 0) if isinstance(data.get("summary"),dict) else 0),
            "invalid_input_schemas":invalid_schemas,
            "discovery_present":discovery.get("present") if discovery else None,
        },
        "boundary":{
            "read_only":True,
            "remote_tools_called":False,
            "credentials_forwarded":False,
            "semantic_result_is_advisory":True,
            "production_gate_influence":"NONE",
            "commercial_gate_influence":"NONE",
        },
    }


async def diagnose_endpoint(
    *,
    url: str | None = None,
    registry_name: str | None = None,
    caller: str | None = None,
    client_version: str = "unknown",
    expected_capability: str = "",
) -> dict[str, Any]:
    verification=await endpoint_verifier.verify_endpoint(
        url=url,
        registry_name=registry_name,
        caller=caller,
        client_version=client_version,
    )
    diagnosis=diagnose_verification(verification,expected_capability)
    diagnosis["verification"]=verification
    return diagnosis
