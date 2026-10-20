# SPDX-License-Identifier: BUSL-1.1
"""Append-only hash chain of neo's signed receipts (transparency log).

Each entry holds only fingerprints (SHA-256), never quotes or URLs:
    [seq, ts, kind, item, extra]
    kind  = "receipt" | "correction" | "note"
    item  = sha256 of the canonical signed receipt (or of the correction body)
    extra = {} for receipts; {"ref", "reason", "version"} for corrections
The chain hash is h_n = sha256(bytes.fromhex(h_{n-1}) + canonical_json(entry)),
with h_0 = "0" * 64. Removing or changing any past entry changes every later
hash, so a published head pins the whole history. Mistakes are never edited
out: a correction entry is appended that points at the wrong one.
"""
from __future__ import annotations

import hashlib
import time
from typing import Any

from receipt_signing import canonical_json

GENESIS = "0" * 64
KINDS = ("receipt", "correction", "note")
KEEP_RECENT = 120          # entries kept in the live state; older ones live in the public archive


def entry_hash(prev: str, entry: list) -> str:
    return hashlib.sha256(bytes.fromhex(prev) + canonical_json(entry)).hexdigest()


def item_hash(obj: Any) -> str:
    return hashlib.sha256(canonical_json(obj)).hexdigest()


def empty() -> dict:
    return {"v": 1, "head": GENESIS, "count": 0, "entries": [], "base_seq": 0, "base_head": GENESIS}


def next_position(log: dict) -> dict:
    """What the next entry will be: put into a receipt BEFORE signing, so the signature covers it."""
    return {"seq": int(log.get("count") or 0) + 1, "prev": str(log.get("head") or GENESIS)}


def append(log: dict, kind: str, item: str, extra: dict | None = None, ts: int | None = None) -> dict:
    if kind not in KINDS:
        raise ValueError("bad kind")
    if len(item) != 64:
        raise ValueError("bad item")
    log = dict(log or empty())
    seq = int(log.get("count") or 0) + 1
    entry = [seq, int(ts if ts is not None else time.time()), kind, item, dict(extra or {})]
    head = entry_hash(str(log.get("head") or GENESIS), entry)
    entries = list(log.get("entries") or []) + [entry]
    if len(entries) > KEEP_RECENT:
        dropped = entries[:-KEEP_RECENT]
        entries = entries[-KEEP_RECENT:]
        # the head just before the first kept entry, so the kept part stays checkable
        base_head = str(log.get("base_head") or GENESIS)
        for e in dropped:
            base_head = entry_hash(base_head, e)
        log["base_head"] = base_head
        log["base_seq"] = int(dropped[-1][0])
    log.update(count=seq, head=head, entries=entries)
    return log


def verify_chain(entries: list, start_head: str = GENESIS, start_seq: int = 0) -> dict:
    """Recompute the chain; returns {"ok", "head", "count", "error"}. Copyable: hashlib + canonical JSON only."""
    head, seq = start_head, start_seq
    for e in entries:
        if not (isinstance(e, list) and len(e) == 5) or e[0] != seq + 1 or e[2] not in KINDS:
            return {"ok": False, "head": head, "count": seq, "error": f"bad entry after seq {seq}"}
        head, seq = entry_hash(head, e), e[0]
    return {"ok": True, "head": head, "count": seq, "error": None}


def public_view(log: dict, after: int = 0, limit: int = 200) -> dict:
    log = log or empty()
    entries = [e for e in (log.get("entries") or []) if int(e[0]) > int(after)][:max(1, min(int(limit), 200))]
    return {
        "v": 1, "head": log.get("head") or GENESIS, "count": int(log.get("count") or 0),
        "base_seq": int(log.get("base_seq") or 0), "base_head": log.get("base_head") or GENESIS,
        "entries": entries,
        "format": "[seq, unix_ts, kind, item_sha256, extra]; h_n = sha256(bytes.fromhex(h_{n-1}) + "
                  "canonical_json(entry)), h_0 = 64 zeros; canonical JSON = sorted keys, compact, UTF-8",
        "item": "receipt: sha256 of the canonical signed receipt (signature included); "
                "correction: sha256 of canonical_json(extra)",
        "archive": "docs/receipts-log/log.jsonl in the public repository",
    }
