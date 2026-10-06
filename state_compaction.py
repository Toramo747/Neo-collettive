from __future__ import annotations

import base64
from copy import deepcopy
import json
import zlib
from typing import Any

STATE_ENV_COMPRESSED_PREFIX = "zlib64:"
STATE_COMPACTION_TARGET_BYTES = 55_000
STATE_COMPACTION_TRIGGER_RATIO = 0.75
INBOUND_TRAFFIC_EVENT_LIMIT = 300
INBOUND_TRAFFIC_EVENT_TIGHT_LIMIT = 160

# Only durable receipts and compact identity/aggregate state are immutable.
# High-volume event/message histories are continuity-bounded below instead of
# being kept byte-identical forever.
PROTECTED_STATE_KEYS = frozenset({
    "boundary_events",
    "commercial_evidence_memory",
    "challenge_track",
    "gate_stability",
    "gate_stability_state",
})

AGGREGATE_STATE_KEYS = (
    "inbound_agent_stats",
    "inbound_security_stats",
    "agent_chat_monitor",
    "agent_demand_observatory",
    "a2a_discovery",
    "neo_dialect_peers",
    "neo_dialect_seti_probe",
    "search_provider_state",
    "evidence_integrity",
    "gate_stability",
    "hidden_control",
    "hidden_challenge_control",
    "model_shadow",
    "problem_performance",
    "problem_cooldowns",
    "query_execution",
    "jarvis_runtime",
    "venture_metrics",
    "runtime_snapshot",
    "outcome_control",
    "seti",
    "agent_trust",
)

CONTINUITY_HISTORY_LIMITS = {
    "inbound_messages": 32,
    "agent_chat_events": 64,
    "inbound_security_events": 48,
    "inbound_review_queue": 40,
    "neo_dialect_events": 64,
}
TIGHT_CONTINUITY_HISTORY_LIMITS = {
    "inbound_messages": 12,
    "agent_chat_events": 24,
    "inbound_security_events": 16,
    "inbound_review_queue": 16,
    "neo_dialect_events": 24,
}

_HISTORY_TEXT_KEYS = frozenset({
    "excerpt", "snippet", "response_excerpt", "response", "text", "content",
    "summary", "description", "reason", "note",
})
_HISTORY_LIST_KEYS = frozenset({
    "sources", "source_urls", "signals", "evidence", "items", "results",
    "messages", "history", "attempt_history",
})


def _json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=False,
    ).encode("utf-8")


def encoded_sizes(payload: dict) -> tuple[int, int]:
    raw = _json_bytes(payload)
    packed = zlib.compress(raw, level=9)
    encoded = STATE_ENV_COMPRESSED_PREFIX.encode("ascii") + base64.b64encode(packed)
    return len(raw), len(encoded)


def key_weight_report(payload: dict) -> list[dict[str, Any]]:
    rows = []
    for key, value in payload.items():
        raw, encoded = encoded_sizes({key: value})
        rows.append({"key": str(key), "raw_bytes": raw, "encoded_bytes": encoded})
    rows.sort(key=lambda row: int(row["encoded_bytes"]), reverse=True)
    return rows


def second_level_weight_report(value: Any) -> list[dict[str, Any]]:
    rows = []
    if isinstance(value, dict):
        for key, child in value.items():
            raw, encoded = encoded_sizes({key: child})
            rows.append({"key": str(key), "raw_bytes": raw, "encoded_bytes": encoded})
    elif isinstance(value, list):
        for index, child in enumerate(value):
            raw, encoded = encoded_sizes({"item": child})
            rows.append({"key": f"item[{index}]", "raw_bytes": raw, "encoded_bytes": encoded})
    rows.sort(key=lambda row: int(row["encoded_bytes"]), reverse=True)
    return rows


def _count_list(row: dict, *names: str) -> int:
    for name in names:
        value = row.get(name)
        if isinstance(value, list):
            return len(value)
        if isinstance(value, dict):
            return len(value)
        if isinstance(value, int):
            return max(0, value)
    return 0


def _summarize_opportunity(raw: Any) -> dict[str, Any]:
    row = raw if isinstance(raw, dict) else {}
    missing = row.get("missing") if isinstance(row.get("missing"), list) else []
    existing_counts = row.get("counts") if isinstance(row.get("counts"), dict) else {}
    return {
        "tool_name": row.get("tool_name") or row.get("name") or row.get("product_name"),
        "family": row.get("family"),
        "monetization_score": row.get("monetization_score"),
        "gate_pass": bool(row.get("gate_pass")),
        "missing": [str(item)[:120] for item in missing[:12]],
        "counts": {
            "sources": int(existing_counts.get("sources") or _count_list(row, "sources", "source_urls", "source_count")),
            "payment_signals": int(existing_counts.get("payment_signals") or _count_list(
                row, "payment_signals", "payment_evidence", "paid_demand_signals",
                "payment_signal_count",
            )),
            "gap": int(existing_counts.get("gap") or _count_list(row, "gap_signals", "gaps", "gap_evidence", "gap_count")),
        },
    }


def _summarize_transcript(raw: Any) -> dict[str, Any]:
    row = raw if isinstance(raw, dict) else {}
    return {
        "opportunity": (
            row.get("opportunity")
            or row.get("tool_name")
            or row.get("family")
            or row.get("name")
        ),
        "decision": row.get("decision") or row.get("verdict") or row.get("status"),
    }


def drop_ephemeral_checkpoint_state(payload: dict) -> dict:
    """Remove state that is never consumed by _merge_state_payload after restart."""
    out = deepcopy(payload)
    out.pop("tool_opportunities", None)
    out.pop("council_history", None)
    out.pop("runtime_snapshot", None)
    return out


def compact_council_history(payload: dict) -> dict:
    out = deepcopy(payload)
    history = out.get("council_history")
    if not isinstance(history, list):
        return out
    compacted = []
    for raw_cycle in history[-12:]:
        cycle = raw_cycle if isinstance(raw_cycle, dict) else {}
        top5 = cycle.get("top5") if isinstance(cycle.get("top5"), list) else []
        transcripts = cycle.get("transcripts") if isinstance(cycle.get("transcripts"), list) else []
        compacted.append({
            "generated_at_utc": cycle.get("generated_at_utc"),
            "top5": [_summarize_opportunity(item) for item in top5[:5]],
            "transcripts": [_summarize_transcript(item) for item in transcripts[:5]],
        })
    out["council_history"] = compacted
    return out


def deduplicate_current_tool_opportunities(payload: dict) -> dict:
    out = deepcopy(payload)
    root = out.get("tool_opportunities")
    latest = out.get("latest_result")
    if not isinstance(root, dict) or not isinstance(latest, dict):
        return out
    candidate = latest.get("tool_opportunities")
    if candidate == root:
        latest_copy = dict(latest)
        latest_copy["tool_opportunities"] = {"_state_ref": "tool_opportunities"}
        out["latest_result"] = latest_copy
    return out


def compact_historical_transcripts(payload: dict) -> dict:
    # council_history is already reduced to decision-only transcripts by level A.
    # This level handles any legacy top-level historical transcript collections
    # while preserving the full current transcript inside tool_opportunities.
    out = deepcopy(payload)
    legacy = out.get("council_transcripts")
    if isinstance(legacy, list):
        out["council_transcripts"] = [_summarize_transcript(item) for item in legacy[-12:]]
    latest = out.get("latest_result")
    if isinstance(latest, dict):
        copy = dict(latest)
        transcripts = copy.get("council_transcripts")
        if isinstance(transcripts, list):
            copy["council_transcripts"] = [_summarize_transcript(item) for item in transcripts[-12:]]
        out["latest_result"] = copy
    return out


def merge_cumulative_inbound_summary(persisted: dict | None, recent: dict | None) -> dict:
    """Keep cumulative totals/first-last from persistence, refresh recent windows from retained events."""
    old = deepcopy(persisted) if isinstance(persisted, dict) else {}
    new = deepcopy(recent) if isinstance(recent, dict) else {}
    if not old:
        return new
    if not new:
        return old

    out = new
    old_counts = old.get("counts") if isinstance(old.get("counts"), dict) else {}
    new_counts = out.get("counts") if isinstance(out.get("counts"), dict) else {}
    if isinstance(old_counts.get("total"), dict):
        new_counts["total"] = deepcopy(old_counts.get("total") or {})
    out["counts"] = new_counts

    for key in (
        "events_total",
        "logical_messages_total",
        "technical_evidence_total",
        "first_real_contact_utc",
        "last_real_contact_utc",
        "official_counting_since_utc",
        "legacy_rule",
        "dedup_window_seconds",
    ):
        if key in old and old.get(key) is not None:
            out[key] = deepcopy(old.get(key))

    for key in ("crawler_origins", "real_contact_origins", "self_traffic_origins"):
        if key in old:
            out[key] = deepcopy(old.get(key))
    return out


def trim_inbound_traffic_events(payload: dict, limit: int = INBOUND_TRAFFIC_EVENT_LIMIT) -> dict:
    out = deepcopy(payload)
    rows = out.get("inbound_traffic_events")
    if isinstance(rows, list) and len(rows) > limit:
        # inbound_traffic_summary is intentionally kept unchanged. It is the
        # cumulative rollup captured before trimming; only source events shrink.
        out["inbound_traffic_events"] = rows[-limit:]
    return out


def _bounded_continuity_value(
    value: Any,
    *,
    depth: int = 0,
    text_limit: int = 2048,
    nested_list_limit: int = 16,
) -> Any:
    if depth > 6:
        return value
    if isinstance(value, dict):
        return {
            key: _bounded_continuity_value(
                item,
                depth=depth + 1,
                text_limit=text_limit,
                nested_list_limit=nested_list_limit,
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [
            _bounded_continuity_value(
                item,
                depth=depth + 1,
                text_limit=text_limit,
                nested_list_limit=nested_list_limit,
            )
            for item in value[-nested_list_limit:]
        ]
    if isinstance(value, str):
        return value[:text_limit]
    return value


def compact_continuity_histories(
    payload: dict,
    *,
    limits: dict[str, int] | None = None,
    text_limit: int = 2048,
) -> dict:
    """Bound replayable A2A histories while keeping durable identity/receipt state."""
    out = deepcopy(payload)
    selected = limits or CONTINUITY_HISTORY_LIMITS
    for key, limit in selected.items():
        rows = out.get(key)
        if not isinstance(rows, list):
            continue
        out[key] = [
            _bounded_continuity_value(item, text_limit=text_limit)
            for item in rows[-max(0, int(limit)):]
        ]
    return out


def _bounded_history_value(value: Any, *, depth: int = 0) -> Any:
    if depth > 6:
        return value
    if isinstance(value, dict):
        out = {}
        for key, item in value.items():
            if key in _HISTORY_TEXT_KEYS and isinstance(item, str):
                out[key] = item[:800]
            elif key in _HISTORY_LIST_KEYS and isinstance(item, list):
                out[key] = [_bounded_history_value(x, depth=depth + 1) for x in item[-24:]]
            else:
                out[key] = _bounded_history_value(item, depth=depth + 1)
        return out
    if isinstance(value, list):
        return [_bounded_history_value(x, depth=depth + 1) for x in value[-80:]]
    if isinstance(value, str):
        return value[:800]
    return value


def compact_challenge_track(payload: dict) -> dict:
    out=deepcopy(payload)
    raw=out.get("challenge_track")
    if not isinstance(raw,dict):
        return out
    track=dict(raw)
    memory=[x for x in (track.get("memory") or []) if isinstance(x,dict)]
    track["memory"]=memory[-180:]
    gate=track.get("gate_state") if isinstance(track.get("gate_state"),dict) else {}
    if gate:
        gate=dict(gate)
        states=gate.get("candidates") if isinstance(gate.get("candidates"),dict) else {}
        ordered=sorted(
            states.items(),
            key=lambda kv:str((kv[1] or {}).get("updated_at_utc") or ""),
            reverse=True,
        )
        gate["candidates"]=dict(ordered[:60])
        gate["flips"]=list(gate.get("flips") or [])[-40:]
        track["gate_state"]=gate
    out["challenge_track"]=track
    return out


def compact_residual_histories(payload: dict) -> dict:
    out = deepcopy(payload)
    candidates = (
        "build_history", "measurement_history", "dialogue_history",
        "knowledge_ledger", "hypothesis_queue", "exploration_history",
        "jarvis_dialogue_history",
        "thesis_history", "venture_measurements", "outcome_history",
        "trust_lab_evaluations", "observed_pain_candidates",
    )
    for key in candidates:
        if key in PROTECTED_STATE_KEYS:
            continue
        if key in out:
            out[key] = _bounded_history_value(out[key])
    return out


def compact_aggregate_state(payload: dict) -> dict:
    """Bound regenerable aggregate/diagnostic state while preserving durable receipts."""
    out = deepcopy(payload)
    for key in AGGREGATE_STATE_KEYS:
        value = out.get(key)
        if value is None:
            continue
        if key in {"inbound_agent_stats", "neo_dialect_peers", "agent_trust"} and isinstance(value, dict):
            # Dict insertion order tracks recent peer additions in runtime state.
            value = dict(list(value.items())[-64:])
        out[key] = _bounded_history_value(value)
    return out


def protected_serialized_values(payload: dict) -> dict[str, bytes]:
    return {
        key: _json_bytes(payload.get(key))
        for key in PROTECTED_STATE_KEYS
        if key in payload
    }


def heaviest_key(payload: dict) -> tuple[str | None, int]:
    rows = key_weight_report(payload)
    if not rows:
        return None, 0
    return str(rows[0]["key"]), int(rows[0]["encoded_bytes"])


def compact_state_payload(
    payload: dict,
    *,
    max_bytes: int,
    target_bytes: int = STATE_COMPACTION_TARGET_BYTES,
    force: bool = False,
) -> tuple[dict, dict[str, Any]]:
    source = deepcopy(payload)
    before_raw, before_encoded = encoded_sizes(source)
    trigger_bytes = int(max_bytes * STATE_COMPACTION_TRIGGER_RATIO)
    meta: dict[str, Any] = {
        "applied": False,
        "levels": [],
        "before_raw_bytes": before_raw,
        "before_encoded_bytes": before_encoded,
        "after_raw_bytes": before_raw,
        "after_encoded_bytes": before_encoded,
        "target_bytes": target_bytes,
        "trigger_bytes": trigger_bytes,
        "limit_bytes": max_bytes,
    }
    if not force and before_encoded < trigger_bytes:
        return source, meta

    protected_before = protected_serialized_values(source)
    current = deepcopy(source)
    levels = (
        ("a_drop_ephemeral", drop_ephemeral_checkpoint_state),
        ("b_historical_transcripts", compact_historical_transcripts),
        ("c_inbound_traffic_events", trim_inbound_traffic_events),
        ("d_continuity_histories", compact_continuity_histories),
        ("e_residual_histories", compact_residual_histories),
        ("f_aggregate_state", compact_aggregate_state),
    )
    for name, func in levels:
        current = func(current)
        raw_bytes, encoded_bytes = encoded_sizes(current)
        meta["levels"].append({
            "level": name,
            "raw_bytes": raw_bytes,
            "encoded_bytes": encoded_bytes,
        })
        if encoded_bytes <= target_bytes:
            break

    # If normal continuity retention is still too large, use a deterministic
    # tighter replay window. Durable receipts, identity state and cumulative
    # summaries remain protected and byte-identical.
    current_raw, current_encoded = encoded_sizes(current)
    if current_encoded > target_bytes:
        current = compact_continuity_histories(
            current,
            limits=TIGHT_CONTINUITY_HISTORY_LIMITS,
            text_limit=512,
        )
        current = trim_inbound_traffic_events(
            current,
            limit=INBOUND_TRAFFIC_EVENT_TIGHT_LIMIT,
        )
        current_raw, current_encoded = encoded_sizes(current)
        meta["levels"].append({
            "level": "g_tight_continuity",
            "raw_bytes": current_raw,
            "encoded_bytes": current_encoded,
        })

    protected_after = protected_serialized_values(current)
    if protected_before != protected_after:
        raise ValueError("state compaction modified protected durable state")

    after_raw, after_encoded = encoded_sizes(current)
    heavy_key, heavy_bytes = heaviest_key(current)
    meta.update({
        "applied": True,
        "after_raw_bytes": after_raw,
        "after_encoded_bytes": after_encoded,
        "heaviest_key": heavy_key,
        "heaviest_key_encoded_bytes": heavy_bytes,
    })
    return current, meta
