# SPDX-License-Identifier: BUSL-1.1
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import time
from typing import Any, Callable


def _valid_epoch(value: Any) -> bool:
    try:
        return float(value) > 0
    except Exception:
        return False


def _fallback_key(row: dict[str, Any]) -> str:
    for name in ("evidence_id","fingerprint"):
        value=str(row.get(name) or "").strip()
        if value:
            return name+":"+value
    url=str(row.get("url") or "").strip().lower()
    if url:
        return "url:"+url
    raw=json.dumps(row,ensure_ascii=False,sort_keys=True,separators=(",",":"))
    return "row:"+hashlib.sha256(raw.encode("utf-8")).hexdigest()


def canonical_evidence_key(
    row: dict[str, Any],
    key_fn: Callable[[dict[str, Any]], str] | None = None,
) -> str:
    if key_fn is not None:
        try:
            value=str(key_fn(row) or "").strip()
            if value:
                return value
        except Exception:
            pass
    return _fallback_key(row)


def repair_evidence_timestamps(
    rows: list[dict[str, Any]] | None,
    *,
    checkpoint_epoch: float | None = None,
    now_epoch: float | None = None,
) -> tuple[list[dict[str, Any]], int]:
    now=float(now_epoch if now_epoch is not None else time.time())
    checkpoint=float(checkpoint_epoch or 0)
    out=[]
    repaired=0
    for raw in rows or []:
        if not isinstance(raw,dict):
            continue
        row=deepcopy(raw)
        first=float(row.get("first_seen_epoch") or 0) if _valid_epoch(row.get("first_seen_epoch")) else 0.0
        last=float(row.get("last_seen_epoch") or 0) if _valid_epoch(row.get("last_seen_epoch")) else 0.0
        if not last:
            candidate=first or checkpoint or now
            row["last_seen_epoch"]=candidate
            row["timestamp_repaired"]=True
            repaired+=1
            last=candidate
        if not first:
            row["first_seen_epoch"]=last or checkpoint or now
            row["timestamp_repaired"]=True
            repaired+=1
        out.append(row)
    return out,repaired


def replace_evidence_memory_rows(
    old: list[dict[str, Any]] | None,
    new: list[dict[str, Any]] | None,
    reason: str,
    *,
    archived_rows: list[dict[str, Any]] | None = None,
    checkpoint_epoch: float | None = None,
    now_epoch: float | None = None,
    retention_seconds: float = 21 * 86400,
    key_fn: Callable[[dict[str, Any]], str] | None = None,
    recovered_rows: int = 0,
    backup_ok: bool = False,
) -> tuple[list[dict[str, Any]], dict[str, int | str | bool]]:
    now=float(now_epoch if now_epoch is not None else time.time())
    old_fixed,old_repairs=repair_evidence_timestamps(
        old,checkpoint_epoch=checkpoint_epoch,now_epoch=now,
    )
    new_fixed,new_repairs=repair_evidence_timestamps(
        new,checkpoint_epoch=checkpoint_epoch,now_epoch=now,
    )
    archived_fixed,_=repair_evidence_timestamps(
        archived_rows,checkpoint_epoch=checkpoint_epoch,now_epoch=now,
    )

    old_groups={}
    for row in old_fixed:
        old_groups.setdefault(canonical_evidence_key(row,key_fn),[]).append(row)
    new_groups={}
    for row in new_fixed:
        new_groups.setdefault(canonical_evidence_key(row,key_fn),[]).append(row)
    archive_keys={
        canonical_evidence_key(row,key_fn)
        for row in archived_fixed
    }

    dropped_retention=0
    archived=0
    merged_duplicate=0
    unexplained=0

    for key,rows in old_groups.items():
        present=len(new_groups.get(key) or [])
        if present:
            if len(rows)>present:
                merged_duplicate+=len(rows)-present
            continue
        for row in rows:
            last=float(row.get("last_seen_epoch") or 0)
            if last and now-last>float(retention_seconds):
                dropped_retention+=1
            elif key in archive_keys:
                archived+=1
            else:
                unexplained+=1

    blocked=1 if unexplained else 0
    if blocked:
        merged={}
        for row in old_fixed+new_fixed:
            key=canonical_evidence_key(row,key_fn)
            current=merged.get(key)
            if current is None:
                merged[key]=row
                continue
            current_last=float(current.get("last_seen_epoch") or 0)
            row_last=float(row.get("last_seen_epoch") or 0)
            if row_last>=current_last:
                merged[key]=row
        result=list(merged.values())
        dropped_retention=0
        archived=0
        merged_duplicate=max(0,len(old_fixed)+len(new_fixed)-len(result))
    else:
        result=new_fixed

    telemetry={
        "reason":str(reason)[:80],
        "evidence_in":len(old_fixed),
        "evidence_out":len(result),
        "dropped_retention":int(dropped_retention),
        "archived":int(archived),
        "merged_duplicate":int(merged_duplicate),
        "timestamp_repaired":int(old_repairs+new_repairs),
        "evidence_regression_blocked":int(blocked),
        "recovered_rows":max(0,int(recovered_rows)),
        "backup_ok":bool(backup_ok),
    }
    allowed=(
        telemetry["evidence_in"]
        - telemetry["dropped_retention"]
        - telemetry["archived"]
        - telemetry["merged_duplicate"]
    )
    if telemetry["evidence_out"] < allowed:
        telemetry["evidence_regression_blocked"]=1
    return result,telemetry
