# SPDX-License-Identifier: BUSL-1.1
"""Private, conservative continuity check for restored commercial evidence.

Only verified predecessor identities, trusted archive rows, and the existing
21-day retention rule may justify disappearance from a newer generation.
A missing or damaged referenced predecessor puts the store in read-only hold.
No raw evidence or identifying keys are returned in telemetry.
"""
from __future__ import annotations

import math
import time
from typing import Any, Callable

DEFAULT_RETENTION_SECONDS = 21 * 86400


def verify_restart_continuity(
    payload: dict[str, Any] | None,
    *,
    decode_previous: Callable[[dict[str, Any]], list[dict[str, Any]] | None],
    evidence_key: Callable[[dict[str, Any]], str],
    now_epoch: float | None = None,
    retention_seconds: float = DEFAULT_RETENTION_SECONDS,
    restore_status: str = "ok",
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    if not isinstance(payload, dict):
        return payload, {"status": "no_payload"}
    out = dict(payload)
    reference = out.get("commercial_evidence_store_reference")
    if not isinstance(reference, dict):
        return out, {"status": "no_external_reference"}
    current = out.get("commercial_evidence_memory")
    if not isinstance(current, list) or out.get("evidence_store_degraded"):
        return out, {"status": "existing_degraded"}

    def hold(reason: str, *, expected_count: int = 0, missing_count: int = 0):
        out["evidence_store_degraded"] = True
        status = dict(out.get("evidence_store_status") or {})
        status.update({
            "status": reason,
            "active_count": len(out.get("commercial_evidence_memory") or []),
            "expected_active_count": max(0, expected_count),
            "missing_from_new_generation": missing_count,
        })
        out["evidence_store_status"] = status
        return out, {
            "status": reason,
            "expected_count": max(0, expected_count),
            "current_count": len(current),
            "missing_count": missing_count,
        }

    # Fallback after corrupt/absent latest generation must never be
    # automatically promoted to a new authoritative checkpoint.
    if restore_status in {
        "recovered_previous_generation",
        "recovered_orphan_generation",
        "recovered_previous_generations",
    }:
        return hold("continuity_unverified", expected_count=len(current))

    predecessor = reference.get("previous_generation")
    if not isinstance(predecessor, dict):
        # First-generation baselines cannot be verified without independent
        # private inventory; do not falsely report success.
        return out, {"status": "no_predecessor"}

    previous = decode_previous(predecessor)
    if previous is None:
        return hold(
            "continuity_unverified",
            expected_count=int(predecessor.get("evidence_count") or 0),
        )

    def keyed(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        found: dict[str, dict[str, Any]] = {}
        for row in rows:
            if isinstance(row, dict):
                key = str(evidence_key(row) or "").strip()
                if key:
                    found[key] = row
        return found

    old_keys = keyed(previous)
    current_keys = keyed(current)
    archive = keyed(out.get("commercial_evidence_archive_rows") or [])
    missing = old_keys.keys() - current_keys.keys()
    now = time.time() if now_epoch is None else float(now_epoch)

    unexplained = set()
    archived_count = 0
    expired_count = 0
    for key in missing:
        if key in archive:
            archived_count += 1
            continue
        try:
            last_seen = float(old_keys[key].get("last_seen_epoch") or 0)
        except (ValueError, TypeError, OverflowError):
            last_seen = 0
        if (
            math.isfinite(last_seen)
            and last_seen > 0
            and math.isfinite(now)
            and now >= last_seen
            and now - last_seen > retention_seconds
        ):
            expired_count += 1
            continue
        unexplained.add(key)

    meta = {
        "previous_count": len(old_keys),
        "current_count": len(current_keys),
        "missing_count": len(unexplained),
        "archived_count": archived_count,
        "expired_count": expired_count,
    }
    if not unexplained:
        return out, {"status": "verified", **meta}

    # No deletion, no promotion: restore known records in RAM while retaining
    # original external reference for investigation and rollback.
    recovered = list(current)
    recovered.extend(old_keys[key] for key in sorted(unexplained))
    out["commercial_evidence_memory"] = recovered
    payload, blocked = hold(
        "continuity_blocked",
        expected_count=len(old_keys),
        missing_count=len(unexplained),
    )
    return payload, {"status": "continuity_blocked", **meta}
