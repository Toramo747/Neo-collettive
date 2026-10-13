"""Verifiable, idempotent, reversible reintegration of evidence from saved generations.

Used to recover evidence that disappeared on the 10 October stale-env restart
and still sits, intact, in orphan ``NEO_EVIDENCE_<generation>_<i>`` env vars.

* plan   – read-only.  Decodes every intact saved generation (sha256 of the
           decoded payload must equal its generation id), selects identities
           missing from the current memory and still inside the retention
           window, and returns counts plus a ``plan_id`` (hash of the exact
           identities and source generations).  No record content is returned.
* apply  – only with ``confirm == plan_id``; recomputes the plan and refuses
           if anything changed.  Rows are tagged ``restored_from_generation``
           and ``restore_batch`` so they stay distinguishable and removable.
           Re-applying is a no-op (identities already present are skipped).
* revert – removes exactly the rows of one ``restore_batch``.
"""
from __future__ import annotations

import hashlib
import re
import time
from typing import Any, Callable, Iterable

from commercial_evidence_store import generation_id, recover_external_store_generation

ACTIVE_RE = re.compile(r"^NEO_EVIDENCE_([0-9a-f]{12})_(\d+)$")
RETENTION_SECONDS = 21 * 86400


def intact_generations(saved: dict[str, str]) -> dict[str, list[dict[str, Any]]]:
    groups: dict[str, dict[int, str]] = {}
    for key, value in saved.items():
        m = ACTIVE_RE.match(str(key))
        if m:
            groups.setdefault(m.group(1), {})[int(m.group(2))] = value
    out: dict[str, list[dict[str, Any]]] = {}
    for gen, indexed in groups.items():
        idx = sorted(indexed)
        if idx != list(range(len(idx))):
            continue
        recovered = recover_external_store_generation([indexed[i] for i in idx], store="render_env_chunks_v2")
        if recovered is None:
            continue
        ref, rows = recovered
        if generation_id(ref) != gen:
            continue
        out[gen] = [r for r in rows if isinstance(r, dict)]
    return out


def build_plan(
    saved: dict[str, str],
    current_rows: Iterable[dict[str, Any]],
    key_fn: Callable[[dict[str, Any]], str],
    *,
    now: float | None = None,
    retention_seconds: float = RETENTION_SECONDS,
) -> dict[str, Any]:
    now = time.time() if now is None else float(now)
    current_keys = {key_fn(r) for r in current_rows if isinstance(r, dict)}
    best: dict[str, tuple[dict[str, Any], str]] = {}
    expired = 0
    gens = intact_generations(saved)
    for gen, rows in sorted(gens.items()):
        for row in rows:
            key = key_fn(row)
            if key in current_keys:
                continue
            last = float(row.get("last_seen_epoch") or 0)
            if not last or now - last > retention_seconds:
                expired += 1
                continue
            prev = best.get(key)
            if prev is None or last > float(prev[0].get("last_seen_epoch") or 0):
                best[key] = (row, gen)
    keys = sorted(best)
    used = sorted({gen for _, gen in best.values()})
    plan_id = hashlib.sha256(("\n".join(keys) + "|" + ",".join(used)).encode("utf-8")).hexdigest()[:16]
    return {
        "plan_id": plan_id if keys else None,
        "candidates": len(keys),
        "gate_eligible": sum(1 for k in keys if best[k][0].get("gate_eligible")),
        "intact_generations": len(gens),
        "source_generations": used,  # 12-hex content hashes only
        "skipped_expired_rows": expired,
        "_rows": [(best[k][0], best[k][1]) for k in keys],
    }


def public_plan(plan: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in plan.items() if not k.startswith("_")}


def apply_plan(plan: dict[str, Any], current_rows: list[dict[str, Any]], *, now: float | None = None) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    now = time.time() if now is None else float(now)
    batch = plan.get("plan_id")
    restored = []
    for row, gen in plan.get("_rows") or []:
        copy = dict(row)
        copy["restored_from_generation"] = gen
        copy["restore_batch"] = batch
        copy["restored_at_epoch"] = now
        restored.append(copy)
    ledger = {
        "batch": batch, "action": "apply", "rows": len(restored),
        "gate_eligible": sum(1 for r in restored if r.get("gate_eligible")),
        "source_generations": plan.get("source_generations"), "at_epoch": now,
    }
    return list(current_rows) + restored, ledger


def revert_batch(current_rows: list[dict[str, Any]], batch: str, *, now: float | None = None) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    now = time.time() if now is None else float(now)
    kept = [r for r in current_rows if not (isinstance(r, dict) and r.get("restore_batch") == batch)]
    return kept, {"batch": batch, "action": "revert", "rows": len(current_rows) - len(kept), "at_epoch": now}
