from __future__ import annotations

import ipaddress
import re
from copy import deepcopy
from typing import Any


MAX_PUBLIC_STRING_LENGTH = 160
MAX_TRAFFIC_EVENTS = 400
MAX_SECURITY_EVENTS = 80

TRAFFIC_CATEGORIES = (
    "crawler_probe",
    "self_traffic",
    "real_contact_pending",
    "real_contact",
    "legacy_unattributable",
    "malicious_solicitation",
    "unknown",
)

PUBLIC_SNAPSHOT_SCHEMA = {
    "captured_at_utc": None,
    "snapshot_schema": None,
    "neo_version": None,
    "runtime_profile": {
        "profile_id": None,
        "deployment_role": None,
        "state_schema": None,
        "config_fingerprint": None,
    },
    "policy": {
        "policy_version": None,
    },
    "heartbeat": {
        "ok": None,
        "started": None,
        "busy": None,
        "cooldown": None,
        "cooldown_seconds": None,
        "last_started_age_seconds": None,
        "cycles_completed": None,
        "last_started_utc": None,
        "last_finished_utc": None,
        "last_status": None,
    },
    "endpoint_latency": {
        "captured_at_utc": None,
        "samples": [{
            "timestamp_utc": None,
            "endpoint": None,
            "phase": None,
            "run_first_request": None,
            "cold_start_candidate": None,
            "http_status": None,
            "latency_ms": None,
            "curl_exit_code": None,
        }],
    },
    "diagnostics": {
        "status_endpoint_reached": None,
        "source_commit": None,
        "runtime_contract_verified": None,
        "hidden_control": {
            "required": None,
            "cases": None,
            "correct": None,
            "ok": None,
        },
    },
    "autopilot": {
        "enabled": None,
        "running": None,
        "cycles_completed": None,
        "last_started_utc": None,
        "last_finished_utc": None,
        "last_status": None,
        "stagnation_cycles": None,
        "recent_sectors": [None],
        "family_performance": [{
            "category": None,
            "score": None,
            "observations": None,
            "best_gap_score": None,
            "qualified_hits": None,
            "last_gap_score": None,
            "last_domains": None,
            "last_strong_domains": None,
            "last_signal_types": [None],
            "no_progress_streak": None,
        }],
        "inbound_traffic_summary": {
            "schema_v": None,
            "official_counting_since_utc": None,
            "events_total": None,
            "logical_messages_total": None,
            "technical_evidence_total": None,
            "dedup_window_seconds": None,
            "counts": {
                "total": {key: None for key in TRAFFIC_CATEGORIES},
                "last_24h": {key: None for key in TRAFFIC_CATEGORIES},
                "last_7d": {key: None for key in TRAFFIC_CATEGORIES},
            },
            "first_real_contact_utc": None,
            "last_real_contact_utc": None,
        },
        "inbound_traffic_events": [{
            "timestamp_utc": None,
            "content_fingerprint": None,
            "category": None,
            "reason": None,
        }],
        "inbound_security_events": [{
            "received_at_utc": None,
            "traffic_class": None,
            "reason": None,
        }],
        "agent_chat_monitor": {
            "thread_count": None,
        },
        "agent_demand_observatory": {
            "messages_observed": None,
        },
        "seti": {
            "enabled": None,
            "mode": None,
            "every_cycles": None,
            "last_scan_utc": None,
            "signal_memory_count": None,
        },
        "select_diagnostics": {
            "status": None,
            "ingestion_enabled": None,
            "raw_results": None,
            "relevance_pass": None,
            "useful_results": None,
            "persistent_evidence_items": None,
            "quarantined_evidence_items": None,
            "rejected_current_count": None,
            "new_signal_rows": None,
            "problem_cluster_count": None,
            "qualified_problem_count": None,
            "configured_categories": None,
            "evidenced_candidates": None,
            "gate_eligible_candidates": None,
            "qualified_candidates": None,
            "top_gate_pass": None,
            "top_monetization_score": None,
            "top_missing": [None],
            "candidates": [{
                "candidate_id": None,
                "evidence_fingerprint": None,
                "id_key_version": None,
                "score": None,
                "source_count": None,
                "independent_domain_count": None,
                "raw_gate_pass": None,
                "stable_gate_pass": None,
                "pass_streak": None,
                "fail_streak": None,
                "missing_codes": [None],
                "cycle": None,
                "commit": None,
                "first_cycle_after_deploy": None,
                "seconds_since_first_raw_pass": None,
                "tagger_version": None,
            }],
            "rejection_reasons": [{
                "reason": None,
                "count": None,
            }],
            "search_sources": [{
                "source": None,
                "attempts": None,
                "empty": None,
                "errors": None,
                "raw_results": None,
                "relevance_pass": None,
            }],
            "buyer_voice_by_source": [{
                "source": None,
                "count": None,
            }],
            "search_provider": {
                "name": None,
                "configured_provider": None,
                "provider_key_present": None,
                "fallback_used": None,
                "calls_cycle": None,
                "calls_day": None,
                "errors": None,
                "fallbacks": None,
                "fallback_reasons": [{
                    "reason": None,
                    "count": None,
                }],
            },
            "funnel": {
                "queries_planned": None,
                "queries_executed": None,
                "queries_skipped_by_reason": [{"reason": None,"count": None}],
                "calls_by_source": [{
                    "source": None,
                    "count": None,
                }],
                "errors_by_source": [{
                    "source": None,
                    "error": None,
                    "count": None,
                }],
                "raw_received": None,
                "deduped": None,
                "query_relevant": None,
                "family_matched": None,
                "buyer_voice": None,
                "commercial_signal": None,
                "persisted": None,
                "discarded_by_reason": [{
                    "reason": None,
                    "count": None,
                }],
                "monotonicity_warnings": [{
                    "upstream": None,
                    "downstream": None,
                }],
            },
            "agent_probes": {
                "probes_attempted": None,
                "agents_reached": None,
                "answers_received": None,
                "valid_answers": None,
                "rejected_answers": None,
                "timeouts": None,
            },
        },
        "last_checkpoint": {
            "ok": None,
            "status": None,
            "raw_bytes": None,
            "stored_bytes": None,
            "limit_bytes": None,
            "compaction": {
                "applied": None,
                "before_raw_bytes": None,
                "before_encoded_bytes": None,
                "after_raw_bytes": None,
                "after_encoded_bytes": None,
                "target_bytes": None,
                "trigger_bytes": None,
                "limit_bytes": None,
            },
        },
    },
}

PUBLIC_JARVIS_SNAPSHOT_SCHEMA = {
    "snapshot_utc": None,
    "target": None,
    "latest_log_utc": None,
    "service": {
        "name": None,
        "type": None,
        "region": None,
        "suspended": None,
        "plan": None,
        "updatedAt": None,
    },
    "inbound_traffic_summary": {
        "schema_v": None,
        "official_counting_since_utc": None,
        "events_total": None,
        "logical_messages_total": None,
        "technical_evidence_total": None,
        "dedup_window_seconds": None,
        "counts": {
            "total": {key: None for key in TRAFFIC_CATEGORIES},
            "last_24h": {key: None for key in TRAFFIC_CATEGORIES},
            "last_7d": {key: None for key in TRAFFIC_CATEGORIES},
        },
        "first_real_contact_utc": None,
        "last_real_contact_utc": None,
    },
    "log_rows_scanned": None,
    "categories": {
        "errors_5xx": None,
        "timeouts": None,
        "restarts_shutdowns": None,
        "startup": None,
        "deploy_startups": None,
        "possible_cold_starts": None,
        "ask_requests": None,
        "ask_2xx": None,
        "ask_failures": None,
        "health_requests": None,
        "agent_card_requests": None,
        "agent_card_requests_last_24h": None,
        "health_requests_last_24h": None,
    },
    "startup_events": [{
        "timestamp_utc": None,
        "classification": None,
    }],
    "recent_deploys": [{
        "status": None,
        "createdAt": None,
        "updatedAt": None,
        "finishedAt": None,
        "commit_sha": None,
        "commit_created_at": None,
    }],
}


_FORBIDDEN_FREE_TEXT_KEYS = {
    "text", "message", "messages", "reply", "response", "prompt", "content",
    "excerpt", "raw", "body", "question", "answer", "claim", "last_ask",
    "last_dialogue", "user_agent", "ip_or_origin", "origin", "agent_id",
    "agent_ids", "peer_id", "source_agent_id", "declared_agent_id", "thread_id",
    "source_message_id", "response_message_id",
}
_EMAIL_RE = re.compile(r"(?i)(?<![A-Z0-9._%+-])[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}(?![A-Z0-9._%+-])")
_IPV4_RE = re.compile(r"(?<![0-9])(?:[0-9]{1,3}\.){3}[0-9]{1,3}(?![0-9])")
_IPV6_CANDIDATE_RE = re.compile(r"(?<![0-9A-Fa-f:])(?:[0-9A-Fa-f]{0,4}:){2,7}[0-9A-Fa-f]{0,4}(?![0-9A-Fa-f:])")


def _copy_keys(src: Any, keys: tuple[str, ...]) -> dict:
    if not isinstance(src, dict):
        return {}
    return {key: deepcopy(src[key]) for key in keys if key in src and src[key] is not None}


def _project_rows(rows: Any, keys: tuple[str, ...], limit: int) -> list[dict]:
    out = []
    for row in list(rows or [])[-limit:]:
        if isinstance(row, dict):
            out.append(_copy_keys(row, keys))
    return out


def _project_counts(value: Any) -> dict:
    src = value if isinstance(value, dict) else {}
    return {
        window: {
            category: int((src.get(window) or {}).get(category) or 0)
            for category in TRAFFIC_CATEGORIES
        }
        for window in ("total", "last_24h", "last_7d")
    }


def _project_family_performance(value: Any) -> list[dict]:
    if not isinstance(value, dict):
        return []
    rows = []
    numeric_keys = (
        "score", "observations", "best_gap_score", "qualified_hits",
        "last_gap_score", "last_domains", "last_strong_domains", "no_progress_streak",
    )
    for category in sorted(value):
        raw = value.get(category)
        if not isinstance(raw, dict):
            continue
        row = {"category": str(category)[:48]}
        row.update(_copy_keys(raw, numeric_keys))
        signals = raw.get("last_signal_types") or []
        row["last_signal_types"] = [str(item)[:48] for item in list(signals)[:12]]
        rows.append(row)
    return rows[:64]



_SAFE_CODE_RE = re.compile(r"[^A-Za-z0-9_.:-]+")
_HEX16_RE = re.compile(r"^[0-9a-f]{16}$")
_HEX_COMMIT_RE = re.compile(r"^[0-9a-f]{7,64}$")
_VERSION_CODE_RE = re.compile(r"^(?:v?[0-9]+(?:\\.[0-9]+){0,3})$")
_CANDIDATE_MISSING_CODES = frozenset({
    "specific_tool_name_and_target_user",
    "two_independent_real_price_competitors",
    "two_competitors_with_real_price",
    "dissatisfaction_signal",
    "documented_gap",
    "three_independent_source_domains",
    "two_existing_paid_tools",
    "monetization_score_60",
})


def _safe_code(value: Any, max_len: int = 80) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    cleaned = _SAFE_CODE_RE.sub("_", raw).strip("_.:-")
    return cleaned[:max_len]


def _counter_total(value: Any) -> int:
    if not isinstance(value, dict):
        return 0
    total = 0
    for item in value.values():
        try:
            total += max(0, int(item or 0))
        except Exception:
            continue
    return total


def _project_reason_counts(value: Any, limit: int = 12) -> list[dict]:
    if not isinstance(value, dict):
        return []
    rows = []
    for reason, count in value.items():
        code = _safe_code(reason)
        if not code:
            continue
        try:
            n = max(0, int(count or 0))
        except Exception:
            n = 0
        rows.append({"reason": code, "count": n})
    rows.sort(key=lambda row: (-int(row["count"]), row["reason"]))
    return rows[:limit]


def _project_source_counts(value: Any, limit: int = 16) -> list[dict]:
    if not isinstance(value,dict):
        return []
    rows=[]
    for source,count in sorted(value.items()):
        safe_source=_safe_code(source,48)
        if not safe_source:
            continue
        try:
            n=max(0,int(count or 0))
        except Exception:
            n=0
        rows.append({"source":safe_source,"count":n})
    rows.sort(key=lambda row:(-row["count"],row["source"]))
    return rows[:limit]


def _project_search_sources(ingestion: dict) -> list[dict]:
    attempts = ingestion.get("source_attempts") if isinstance(ingestion.get("source_attempts"), dict) else {}
    empty = ingestion.get("source_empty") if isinstance(ingestion.get("source_empty"), dict) else {}
    errors = ingestion.get("source_errors") if isinstance(ingestion.get("source_errors"), dict) else {}
    raw = ingestion.get("raw_results_by_source") if isinstance(ingestion.get("raw_results_by_source"), dict) else {}
    passed = ingestion.get("query_relevance_pass_by_source") if isinstance(ingestion.get("query_relevance_pass_by_source"), dict) else {}
    keys = sorted(set(attempts) | set(empty) | set(errors) | set(raw) | set(passed))
    rows = []
    for key in keys:
        source = _safe_code(key, 48)
        if not source:
            continue
        rows.append({
            "source": source,
            "attempts": max(0, int(attempts.get(key) or 0)),
            "empty": max(0, int(empty.get(key) or 0)),
            "errors": max(0, int(errors.get(key) or 0)),
            "raw_results": max(0, int(raw.get(key) or 0)),
            "relevance_pass": max(0, int(passed.get(key) or 0)),
        })
    return rows[:16]


def _project_error_codes(value: Any, source_limit: int = 16, code_limit: int = 12) -> list[dict]:
    if not isinstance(value, dict):
        return []
    out=[]
    for source,codes in sorted(value.items()):
        safe_source=_safe_code(source,48)
        if not safe_source or not isinstance(codes,dict):
            continue
        per_source=0
        for code,count in sorted(codes.items()):
            safe_error=_safe_code(code,80)
            if not safe_error:
                continue
            try:
                n=max(0,int(count or 0))
            except Exception:
                n=0
            out.append({"source":safe_source,"error":safe_error,"count":n})
            per_source+=1
            if per_source>=code_limit:
                break
        if len({row["source"] for row in out})>=source_limit:
            break
    return out


def _project_funnel(value: Any) -> dict:
    src=value if isinstance(value,dict) else {}
    calls=src.get("calls_by_source") if isinstance(src.get("calls_by_source"),dict) else {}
    return {
        "queries_planned":max(0,int(src.get("queries_planned") or 0)),
        "queries_executed":max(0,int(src.get("queries_executed") or 0)),
        "queries_skipped_by_reason":_project_reason_counts(src.get("queries_skipped_by_reason")),
        "calls_by_source":[
            {"source":_safe_code(k,48),"count":max(0,int(v or 0))}
            for k,v in sorted(calls.items()) if _safe_code(k,48)
        ][:16],
        "errors_by_source":_project_error_codes(src.get("errors_by_source")),
        "raw_received":max(0,int(src.get("raw_received") or 0)),
        "deduped":max(0,int(src.get("deduped") or 0)),
        "query_relevant":max(0,int(src.get("query_relevant") or 0)),
        "family_matched":max(0,int(src.get("family_matched") or 0)),
        "buyer_voice":max(0,int(src.get("buyer_voice") or 0)),
        "commercial_signal":max(0,int(src.get("commercial_signal") or 0)),
        "persisted":max(0,int(src.get("persisted") or 0)),
        "discarded_by_reason":_project_reason_counts(src.get("discarded_by_reason")),
        "monotonicity_warnings":[
            {
                "upstream":_safe_code(x.get("upstream"),48),
                "downstream":_safe_code(x.get("downstream"),48),
            }
            for x in (src.get("monotonicity_warnings") or [])
            if isinstance(x,dict)
        ][:12],
    }


def _project_agent_probes(value: Any) -> dict:
    src=value if isinstance(value,dict) else {}
    return {
        key:max(0,int(src.get(key) or 0))
        for key in (
            "probes_attempted","agents_reached","answers_received",
            "valid_answers","rejected_answers","timeouts",
        )
    }


def _project_candidate_telemetry(value: Any) -> list[dict]:
    rows=[]
    for raw in list(value or [])[:3]:
        if not isinstance(raw,dict):
            continue
        candidate_id=str(raw.get("candidate_id") or "")
        evidence_fp=str(raw.get("evidence_fingerprint") or "")
        id_key_version=str(raw.get("id_key_version") or "")
        commit=str(raw.get("commit") or "")
        tagger_version=str(raw.get("tagger_version") or "")
        if not (_HEX16_RE.fullmatch(candidate_id) and _HEX16_RE.fullmatch(evidence_fp)):
            continue
        if not _VERSION_CODE_RE.fullmatch(id_key_version):
            continue
        if commit and not _HEX_COMMIT_RE.fullmatch(commit):
            continue
        if tagger_version and not _VERSION_CODE_RE.fullmatch(tagger_version):
            continue
        missing=[
            str(code) for code in (raw.get("missing_codes") or [])
            if str(code) in _CANDIDATE_MISSING_CODES
        ][:12]
        row={
            "candidate_id":candidate_id,
            "evidence_fingerprint":evidence_fp,
            "id_key_version":id_key_version,
            "score":max(0,int(raw.get("score") or 0)),
            "source_count":max(0,int(raw.get("source_count") or 0)),
            "independent_domain_count":max(0,int(raw.get("independent_domain_count") or 0)),
            "raw_gate_pass":bool(raw.get("raw_gate_pass")),
            "stable_gate_pass":bool(raw.get("stable_gate_pass")),
            "pass_streak":max(0,int(raw.get("pass_streak") or 0)),
            "fail_streak":max(0,int(raw.get("fail_streak") or 0)),
            "missing_codes":missing,
            "cycle":max(0,int(raw.get("cycle") or 0)),
            "commit":commit,
            "first_cycle_after_deploy":bool(raw.get("first_cycle_after_deploy")),
            "tagger_version":tagger_version,
        }
        elapsed=raw.get("seconds_since_first_raw_pass")
        row["seconds_since_first_raw_pass"]=None if elapsed is None else max(0,int(elapsed or 0))
        rows.append(row)
    return rows


def _project_select_diagnostics(latest_result: Any) -> dict:
    latest = latest_result if isinstance(latest_result, dict) else {}
    quality = latest.get("evidence_quality") if isinstance(latest.get("evidence_quality"), dict) else {}
    ingestion = (
        quality.get("ingestion_diagnostics")
        if isinstance(quality.get("ingestion_diagnostics"), dict)
        else latest.get("ingestion_diagnostics")
        if isinstance(latest.get("ingestion_diagnostics"), dict)
        else {}
    )
    tool = latest.get("tool_opportunities") if isinstance(latest.get("tool_opportunities"), dict) else {}
    top5 = [row for row in (tool.get("top5") or []) if isinstance(row, dict)]
    top = top5[0] if top5 else {}
    candidate_counts = tool.get("candidate_counts") if isinstance(tool.get("candidate_counts"), dict) else {}
    provider = ingestion.get("search_provider") if isinstance(ingestion.get("search_provider"), dict) else {}
    problem_clusters = (
        quality.get("problem_clusters")
        if isinstance(quality.get("problem_clusters"), dict)
        else latest.get("problem_clusters")
        if isinstance(latest.get("problem_clusters"), dict)
        else {}
    )
    qualified = (
        quality.get("qualified_problem_keys")
        if isinstance(quality.get("qualified_problem_keys"), list)
        else latest.get("qualified_problem_keys")
        if isinstance(latest.get("qualified_problem_keys"), list)
        else []
    )
    rejected = (
        quality.get("rejected_current_results")
        if isinstance(quality.get("rejected_current_results"), list)
        else latest.get("rejected_current_results")
        if isinstance(latest.get("rejected_current_results"), list)
        else []
    )

    raw_results = _counter_total(ingestion.get("raw_results_by_source"))
    relevance_pass = _counter_total(ingestion.get("query_relevance_pass_by_source"))
    missing = []
    for item in top.get("missing") or []:
        code = _safe_code(item)
        if code:
            missing.append(code)

    return {
        "status": _safe_code(latest.get("status"), 48),
        "ingestion_enabled": bool(ingestion.get("enabled")) if "enabled" in ingestion else None,
        "raw_results": raw_results,
        "relevance_pass": relevance_pass,
        "useful_results": max(0, int(
            quality.get("current_cycle_useful_results")
            if quality.get("current_cycle_useful_results") is not None
            else latest.get("current_cycle_useful_results") or 0
        )),
        "persistent_evidence_items": max(0, int(
            quality.get("persistent_evidence_items")
            if quality.get("persistent_evidence_items") is not None
            else latest.get("persistent_evidence_items") or 0
        )),
        "quarantined_evidence_items": max(0, int(
            quality.get("quarantined_evidence_items")
            if quality.get("quarantined_evidence_items") is not None
            else latest.get("quarantined_evidence_items") or 0
        )),
        "rejected_current_count": len(rejected),
        "new_signal_rows": max(0, int(ingestion.get("new_signal_rows") or 0)),
        "problem_cluster_count": len(problem_clusters),
        "qualified_problem_count": len(qualified),
        "configured_categories": max(0, int(candidate_counts.get("configured_categories") or len(top5))),
        "evidenced_candidates": max(0, int(candidate_counts.get("evidenced_candidates") or 0)),
        "gate_eligible_candidates": max(0, int(candidate_counts.get("gate_eligible_candidates") or 0)),
        "qualified_candidates": max(0, int(candidate_counts.get("qualified_candidates") or 0)),
        "top_gate_pass": bool(top.get("gate_pass")),
        "top_monetization_score": max(0, int(top.get("monetization_score") or 0)),
        "top_missing": missing[:12],
        "candidates": _project_candidate_telemetry(tool.get("candidate_telemetry")),
        "rejection_reasons": _project_reason_counts(ingestion.get("rejected_by_reason")),
        "search_sources": _project_search_sources(ingestion),
        "buyer_voice_by_source": _project_source_counts(ingestion.get("buyer_voice_by_source")),
        "search_provider": {
            "name": _safe_code(provider.get("name"), 48),
            "configured_provider": _safe_code(provider.get("configured_provider"), 48),
            "provider_key_present": bool(provider.get("provider_key_present")),
            "fallback_used": bool(provider.get("fallback_used")),
            "calls_cycle": max(0, int(provider.get("calls_cycle") or 0)),
            "calls_day": max(0, int(provider.get("calls_day") or 0)),
            "errors": max(0, int(provider.get("errors") or 0)),
            "fallbacks": max(0, int(provider.get("fallbacks") or 0)),
            "fallback_reasons": _project_reason_counts(provider.get("fallback_reasons")),
        },
        "funnel": _project_funnel(ingestion.get("funnel")),
        "agent_probes": _project_agent_probes(ingestion.get("agent_probes")),
    }


def sanitize_public_autopilot(autopilot: dict | None) -> dict:
    """Project private runtime state into the explicit public allowlist."""
    src = deepcopy(autopilot) if isinstance(autopilot, dict) else {}
    summary = src.get("inbound_traffic_summary") if isinstance(src.get("inbound_traffic_summary"), dict) else {}
    monitor = src.get("agent_chat_monitor") if isinstance(src.get("agent_chat_monitor"), dict) else {}
    demand = src.get("agent_demand_observatory") if isinstance(src.get("agent_demand_observatory"), dict) else {}
    seti = src.get("seti") if isinstance(src.get("seti"), dict) else {}
    checkpoint = src.get("last_checkpoint") if isinstance(src.get("last_checkpoint"), dict) else {}
    compaction = checkpoint.get("compaction") if isinstance(checkpoint.get("compaction"), dict) else {}

    out = _copy_keys(src, (
        "enabled", "running", "cycles_completed", "last_started_utc",
        "last_finished_utc", "last_status", "stagnation_cycles",
    ))
    out["recent_sectors"] = [str(item)[:48] for item in list(src.get("recent_sectors") or [])[-24:]]
    out["family_performance"] = _project_family_performance(src.get("family_performance"))
    out["inbound_traffic_summary"] = {
        **_copy_keys(summary, (
            "schema_v", "official_counting_since_utc", "events_total",
            "logical_messages_total", "technical_evidence_total",
            "dedup_window_seconds", "first_real_contact_utc", "last_real_contact_utc",
        )),
        "counts": _project_counts(summary.get("counts")),
    }
    out["inbound_traffic_events"] = _project_rows(
        src.get("inbound_traffic_events"),
        ("timestamp_utc", "content_fingerprint", "category", "reason"),
        MAX_TRAFFIC_EVENTS,
    )
    out["inbound_security_events"] = _project_rows(
        src.get("inbound_security_events"),
        ("received_at_utc", "traffic_class", "reason"),
        MAX_SECURITY_EVENTS,
    )
    out["agent_chat_monitor"] = _copy_keys(monitor, ("thread_count",))
    out["agent_demand_observatory"] = _copy_keys(demand, ("messages_observed",))
    out["seti"] = {
        **_copy_keys(seti, ("enabled", "mode", "every_cycles", "last_scan_utc")),
        "signal_memory_count": len(seti.get("signal_memory") or {}) if "signal_memory_count" not in seti else seti.get("signal_memory_count"),
    }
    out["last_checkpoint"] = {
        **_copy_keys(checkpoint, ("ok", "status", "raw_bytes", "stored_bytes", "limit_bytes")),
        "compaction": _copy_keys(
            compaction,
            (
                "applied", "before_raw_bytes", "before_encoded_bytes",
                "after_raw_bytes", "after_encoded_bytes", "target_bytes",
                "trigger_bytes", "limit_bytes",
            ),
        ),
    }
    return out


def sanitize_public_snapshot(snapshot: dict | None) -> dict:
    """Apply a top-level allowlist as the final pre-publication projection."""
    src = snapshot if isinstance(snapshot, dict) else {}
    runtime = src.get("runtime_profile") if isinstance(src.get("runtime_profile"), dict) else {}
    policy = src.get("policy") if isinstance(src.get("policy"), dict) else {}
    heartbeat = src.get("heartbeat") if isinstance(src.get("heartbeat"), dict) else {}
    latency = src.get("endpoint_latency") if isinstance(src.get("endpoint_latency"), dict) else {}
    diagnostics = src.get("diagnostics") if isinstance(src.get("diagnostics"), dict) else {}

    out = _copy_keys(src, ("captured_at_utc", "snapshot_schema", "neo_version"))
    out["runtime_profile"] = _copy_keys(runtime, ("profile_id", "deployment_role", "state_schema", "config_fingerprint"))
    out["policy"] = _copy_keys(policy, ("policy_version",))
    out["heartbeat"] = _copy_keys(heartbeat, (
        "ok", "started", "busy", "cooldown", "cooldown_seconds",
        "last_started_age_seconds", "cycles_completed", "last_started_utc",
        "last_finished_utc", "last_status",
    ))
    out["endpoint_latency"] = {
        **_copy_keys(latency, ("captured_at_utc",)),
        "samples": _project_rows(
            latency.get("samples"),
            ("timestamp_utc", "endpoint", "phase", "run_first_request",
             "cold_start_candidate", "http_status", "latency_ms", "curl_exit_code"),
            12,
        ),
    }
    out["diagnostics"] = _copy_keys(
        diagnostics, ("status_endpoint_reached", "source_commit", "runtime_contract_verified")
    )
    hidden=diagnostics.get("hidden_control") if isinstance(diagnostics.get("hidden_control"),dict) else {}
    out["diagnostics"]["hidden_control"]={
        "required":bool(hidden.get("required")),
        "cases":max(0,int(hidden.get("cases") or 0)),
        "correct":max(0,int(hidden.get("correct") or 0)),
        "ok":bool(hidden.get("ok")),
    }
    out["autopilot"] = sanitize_public_autopilot(src.get("autopilot"))
    out["autopilot"]["select_diagnostics"] = _project_select_diagnostics(src.get("latest_result"))
    validate_public_snapshot(out)
    return out



def sanitize_public_jarvis_snapshot(snapshot: dict | None) -> dict:
    """Project Jarvis diagnostics into the same fail-closed public telemetry model."""
    src = snapshot if isinstance(snapshot, dict) else {}
    service = src.get("service") if isinstance(src.get("service"), dict) else {}
    summary = src.get("inbound_traffic_summary") if isinstance(src.get("inbound_traffic_summary"), dict) else {}
    categories = src.get("categories") if isinstance(src.get("categories"), dict) else {}

    out = _copy_keys(src, ("snapshot_utc", "target", "latest_log_utc"))
    out["service"] = _copy_keys(service, ("name", "type", "region", "suspended", "plan", "updatedAt"))
    out["inbound_traffic_summary"] = {
        **_copy_keys(summary, (
            "schema_v", "official_counting_since_utc", "events_total",
            "logical_messages_total", "technical_evidence_total",
            "dedup_window_seconds", "first_real_contact_utc", "last_real_contact_utc",
        )),
        "counts": _project_counts(summary.get("counts")),
    }
    out["log_rows_scanned"] = src.get("log_rows_scanned")
    out["categories"] = _copy_keys(categories, (
        "errors_5xx", "timeouts", "restarts_shutdowns", "startup",
        "deploy_startups", "possible_cold_starts", "ask_requests", "ask_2xx",
        "ask_failures", "health_requests", "agent_card_requests",
        "agent_card_requests_last_24h", "health_requests_last_24h",
    ))
    out["startup_events"] = _project_rows(
        src.get("startup_events"),
        ("timestamp_utc", "classification"),
        20,
    )
    deployments = []
    for row in list(src.get("recent_deploys") or [])[:10]:
        if not isinstance(row, dict):
            continue
        projected = _copy_keys(row, ("status", "createdAt", "updatedAt", "finishedAt"))
        commit = row.get("commit") if isinstance(row.get("commit"), dict) else {}
        if commit.get("id") is not None:
            projected["commit_sha"] = deepcopy(commit.get("id"))
        if commit.get("createdAt") is not None:
            projected["commit_created_at"] = deepcopy(commit.get("createdAt"))
        deployments.append(projected)
    out["recent_deploys"] = deployments
    validate_public_jarvis_snapshot(out)
    return out


def _schema_for_child(schema: Any, key_or_index: Any) -> Any:
    if isinstance(schema, dict):
        if key_or_index not in schema:
            raise ValueError(f"public_snapshot_unknown_key:{key_or_index}")
        return schema[key_or_index]
    if isinstance(schema, list):
        if len(schema) != 1:
            raise ValueError("public_snapshot_invalid_schema_list")
        return schema[0]
    return None


def _contains_ip(value: str) -> bool:
    for candidate in _IPV4_RE.findall(value):
        try:
            ipaddress.ip_address(candidate)
            return True
        except ValueError:
            pass
    for match in _IPV6_CANDIDATE_RE.finditer(value):
        candidate = match.group(0)
        if ":" not in candidate:
            continue
        try:
            ipaddress.ip_address(candidate)
            return True
        except ValueError:
            pass
    return False


def _validate_against_schema(snapshot: Any, schema_root: Any) -> None:
    def walk(value: Any, schema: Any, path: str) -> None:
        if isinstance(value, dict):
            if not isinstance(schema, dict):
                raise ValueError(f"public_snapshot_unexpected_object:{path}")
            for key, item in value.items():
                if key in _FORBIDDEN_FREE_TEXT_KEYS:
                    raise ValueError(f"public_snapshot_forbidden_key:{path}.{key}")
                child_schema = _schema_for_child(schema, key)
                walk(item, child_schema, f"{path}.{key}")
            return
        if isinstance(value, list):
            if not isinstance(schema, list):
                raise ValueError(f"public_snapshot_unexpected_list:{path}")
            child_schema = _schema_for_child(schema, 0)
            for index, item in enumerate(value):
                walk(item, child_schema, f"{path}[{index}]")
            return
        if isinstance(value, str):
            if len(value) > MAX_PUBLIC_STRING_LENGTH:
                raise ValueError(f"public_snapshot_string_too_long:{path}:{len(value)}")
            if _EMAIL_RE.search(value):
                raise ValueError(f"public_snapshot_email:{path}")
            if _contains_ip(value):
                raise ValueError(f"public_snapshot_ip:{path}")

    walk(snapshot, schema_root, "$")


def _validate_candidate_telemetry(snapshot: Any) -> None:
    try:
        rows=snapshot["autopilot"]["select_diagnostics"]["candidates"]
    except Exception:
        return
    if not isinstance(rows,list) or len(rows)>3:
        raise ValueError("public_snapshot_candidate_telemetry_shape")
    for row in rows:
        if not isinstance(row,dict):
            raise ValueError("public_snapshot_candidate_telemetry_row")
        if not _HEX16_RE.fullmatch(str(row.get("candidate_id") or "")):
            raise ValueError("public_snapshot_candidate_id")
        if not _HEX16_RE.fullmatch(str(row.get("evidence_fingerprint") or "")):
            raise ValueError("public_snapshot_evidence_fingerprint")
        if not _VERSION_CODE_RE.fullmatch(str(row.get("id_key_version") or "")):
            raise ValueError("public_snapshot_id_key_version")
        commit=str(row.get("commit") or "")
        if commit and not _HEX_COMMIT_RE.fullmatch(commit):
            raise ValueError("public_snapshot_candidate_commit")
        tagger=str(row.get("tagger_version") or "")
        if tagger and not _VERSION_CODE_RE.fullmatch(tagger):
            raise ValueError("public_snapshot_candidate_tagger")
        for code in row.get("missing_codes") or []:
            if str(code) not in _CANDIDATE_MISSING_CODES:
                raise ValueError("public_snapshot_candidate_missing_code")


def validate_public_snapshot(snapshot: Any) -> None:
    """Fail closed on unknown keys, identifiers, long/free text, IPs or email addresses."""
    _validate_against_schema(snapshot, PUBLIC_SNAPSHOT_SCHEMA)
    _validate_candidate_telemetry(snapshot)


def validate_public_jarvis_snapshot(snapshot: Any) -> None:
    """Apply the same fail-closed privacy guard to public Jarvis telemetry."""
    _validate_against_schema(snapshot, PUBLIC_JARVIS_SNAPSHOT_SCHEMA)


__all__ = [
    "MAX_PUBLIC_STRING_LENGTH",
    "MAX_TRAFFIC_EVENTS",
    "MAX_SECURITY_EVENTS",
    "PUBLIC_SNAPSHOT_SCHEMA",
    "PUBLIC_JARVIS_SNAPSHOT_SCHEMA",
    "sanitize_public_autopilot",
    "sanitize_public_snapshot",
    "sanitize_public_jarvis_snapshot",
    "validate_public_snapshot",
    "validate_public_jarvis_snapshot",
]
