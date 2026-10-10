# SPDX-License-Identifier: BUSL-1.1
"""Conservative, private cross-restart evidence continuity check.

A structurally valid external generation may still be a strict subset of its
immediate predecessor. Do not silently accept or checkpoint that regression.
The original external reference is retained for private forensic recovery.
"""
from __future__ import annotations

from typing import Any, Callable


def verify_restart_continuity(
    payload: dict[str, Any] | None,
    *,
    decode_previous: Callable[[dict[str, Any]], list[dict[str, Any]] | None],
    evidence_key: Callable[[dict[str, Any]], str],
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    if not isinstance(payload, dict):
        return payload, {"status": "no_payload"}
    out = dict(payload)
    reference = out.get("commercial_evidence_store_reference")
    if not isinstance(reference, dict):
        return out, {"status": "no_external_reference"}
    predecessor = reference.get("previous_generation")
    if not isinstance(predecessor, dict):
        return out, {"status": "no_predecessor"}
    current = out.get("commercial_evidence_memory")
    if not isinstance(current, list) or out.get("evidence_store_degraded"):
        return out, {"status": "existing_degraded"}
    previous = decode_previous(predecessor)
    if previous is None:
        # A missing predecessor cannot prove continuity. Never claim success.
        return out, {"status": "predecessor_unavailable"}

    def keyed(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        result: dict[str, dict[str, Any]] = {}
        for row in rows:
            if not isinstance(row, dict):
                continue
            key = str(evidence_key(row) or "").strip()
            if key:
                result[key] = row
        return result

    old_keys = keyed(previous)
    current_keys = keyed(current)
    missing = old_keys.keys() - current_keys.keys()
    if not missing:
        return out, {
            "status": "verified",
            "previous_count": len(old_keys),
            "current_count": len(current_keys),
            "missing_count": 0,
        }

    # Keep all known evidence in memory; block updates to persistent state until
    # an operator verifies legitimate retention/archival and reauthorizes.
    recovered = list(current)
    recovered.extend(old_keys[k] for k in sorted(missing))
    out["commercial_evidence_memory"] = recovered
    out["evidence_store_degraded"] = True
    status = dict(out.get("evidence_store_status") or {})
    status.update({
        "status": "continuity_blocked",
        "active_count": len(recovered),
        "expected_active_count": len(old_keys),
        "missing_from_new_generation": len(missing),
    })
    out["evidence_store_status"] = status
    return out, {
        "status": "continuity_blocked",
        "previous_count": len(old_keys),
        "current_count": len(current_keys),
        "missing_count": len(missing),
    }
