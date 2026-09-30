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
    out["autopilot"] = sanitize_public_autopilot(src.get("autopilot"))
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


def validate_public_snapshot(snapshot: Any) -> None:
    """Fail closed on unknown keys, identifiers, long/free text, IPs or email addresses."""
    _validate_against_schema(snapshot, PUBLIC_SNAPSHOT_SCHEMA)


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
