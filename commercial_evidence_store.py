from __future__ import annotations

import base64
import hashlib
import json
import lzma
from typing import Any

STORE_SCHEMA_V = 2
STORE_PREFIX = "xz64:"
DEFAULT_CHUNK_BYTES = 60_000
DEFAULT_ACTIVE_LIMIT = 3000


def _canonical_rows(rows: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    return [row for row in (rows or []) if isinstance(row, dict)]


def _raw_bytes(rows: list[dict[str, Any]] | None) -> bytes:
    return json.dumps(
        _canonical_rows(rows),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=False,
    ).encode("utf-8")


def evidence_hash(rows: list[dict[str, Any]] | None) -> str:
    return hashlib.sha256(_raw_bytes(rows)).hexdigest()


def generation_id(reference: dict[str, Any] | None) -> str:
    ref=reference if isinstance(reference,dict) else {}
    return str(ref.get("generation") or str(ref.get("sha256") or "")[:12])


def chunk_key(prefix: str, reference: dict[str, Any], index: int) -> str:
    generation=generation_id(reference)
    if generation:
        return f"{prefix}{generation}_{max(0,int(index))}"
    return f"{prefix}{max(0,int(index))}"



_REFERENCE_KEYS = (
    "schema_v","store_mode","store","sha256","generation",
    "evidence_count","chunk_count","raw_bytes",
)


def _reference_copy(reference: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(reference,dict):
        return None
    out={
        key:reference.get(key)
        for key in _REFERENCE_KEYS
        if reference.get(key) is not None
    }
    return out or None


def _distinct_previous_generation(
    previous_generation: dict[str, Any] | None,
    current_sha256: str,
) -> dict[str, Any] | None:
    """Return the first older generation with a different hash.

    Historical self-referential chains are skipped so an unchanged checkpoint
    can never nominate its own active generation for later cleanup.
    """
    seen=set()
    current=previous_generation if isinstance(previous_generation,dict) else None
    while isinstance(current,dict) and current:
        sha=str(current.get("sha256") or "")
        generation=generation_id(current)
        marker=(sha,generation)
        if marker in seen:
            return None
        seen.add(marker)
        if sha and sha != current_sha256:
            chosen=_reference_copy(current)
            older=_distinct_previous_generation(
                current.get("previous_generation") if isinstance(current.get("previous_generation"),dict) else None,
                sha,
            )
            if chosen is not None and older is not None:
                chosen["previous_generation"]=older
            return chosen
        current=current.get("previous_generation") if isinstance(current.get("previous_generation"),dict) else None
    return None


def encode_external_store(
    rows: list[dict[str, Any]] | None,
    *,
    chunk_bytes: int = DEFAULT_CHUNK_BYTES,
    store: str = "render_env_chunks_v1",
    previous_generation: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], list[str]]:
    clean = _canonical_rows(rows)
    raw = _raw_bytes(clean)
    sha = hashlib.sha256(raw).hexdigest()
    packed = lzma.compress(raw, preset=3)
    encoded = STORE_PREFIX + base64.b64encode(packed).decode("ascii")
    size = max(1024, int(chunk_bytes))
    chunks = [encoded[i:i + size] for i in range(0, len(encoded), size)] or [STORE_PREFIX]
    ref = {
        "schema_v": STORE_SCHEMA_V,
        "store_mode": "external",
        "store": store,
        "sha256": sha,
        "generation": sha[:12],
        "evidence_count": len(clean),
        "chunk_count": len(chunks),
        "raw_bytes": len(raw),
    }
    previous=_distinct_previous_generation(previous_generation,sha)
    if previous is not None:
        ref["previous_generation"]=previous
    return ref, chunks


def decode_external_store(
    reference: dict[str, Any] | None,
    chunks: list[str] | None,
) -> list[dict[str, Any]] | None:
    ref = reference if isinstance(reference, dict) else {}
    if ref.get("store_mode") != "external" or ref.get("store") not in {"render_env_chunks_v1","render_env_chunks_v2","render_env_archive_v1"}:
        return None
    expected_chunks = max(0, int(ref.get("chunk_count") or 0))
    values = list(chunks or [])
    if expected_chunks < 1 or len(values) != expected_chunks or any(not isinstance(x, str) for x in values):
        return None
    encoded = "".join(values)
    if not encoded.startswith(STORE_PREFIX):
        return None
    try:
        packed = base64.b64decode(encoded[len(STORE_PREFIX):], validate=True)
        raw = lzma.decompress(packed)
        if hashlib.sha256(raw).hexdigest() != str(ref.get("sha256") or ""):
            return None
        decoded = json.loads(raw.decode("utf-8"))
    except (ValueError, TypeError, UnicodeError, lzma.LZMAError, json.JSONDecodeError):
        return None
    rows = _canonical_rows(decoded if isinstance(decoded, list) else None)
    if len(rows) != int(ref.get("evidence_count") or -1):
        return None
    return rows



def recover_external_store_generation(
    chunks: list[str] | None,
    *,
    store: str = "render_env_chunks_v2",
) -> tuple[dict[str, Any], list[dict[str, Any]]] | None:
    """Recover an orphan generation from its chunk values without trusting a stale reference."""
    values=list(chunks or [])
    if not values or any(not isinstance(value,str) for value in values):
        return None
    encoded="".join(values)
    if not encoded.startswith(STORE_PREFIX):
        return None
    try:
        packed=base64.b64decode(encoded[len(STORE_PREFIX):],validate=True)
        raw=lzma.decompress(packed)
        decoded=json.loads(raw.decode("utf-8"))
    except (ValueError,TypeError,UnicodeError,lzma.LZMAError,json.JSONDecodeError):
        return None
    rows=_canonical_rows(decoded if isinstance(decoded,list) else None)
    if not isinstance(decoded,list) or len(rows)!=len(decoded):
        return None
    sha=hashlib.sha256(raw).hexdigest()
    ref={
        "schema_v":STORE_SCHEMA_V,
        "store_mode":"external",
        "store":store,
        "sha256":sha,
        "generation":sha[:12],
        "evidence_count":len(rows),
        "chunk_count":len(values),
        "raw_bytes":len(raw),
    }
    return ref,rows

def is_external_reference(value: Any) -> bool:
    return (
        isinstance(value, dict)
        and value.get("store_mode") == "external"
        and value.get("store") in {"render_env_chunks_v1","render_env_chunks_v2","render_env_archive_v1"}
    )


def split_active_archive(
    rows: list[dict[str, Any]] | None,
    *,
    active_limit: int = DEFAULT_ACTIVE_LIMIT,
) -> tuple[list[dict[str, Any]],list[dict[str, Any]]]:
    clean=_canonical_rows(rows)
    limit=max(1,int(active_limit))
    if len(clean)<=limit:
        return clean,[]
    eligible=[row for row in clean if bool(row.get("gate_eligible"))]
    ineligible=[row for row in clean if not bool(row.get("gate_eligible"))]
    keep_ineligible=max(0,limit-len(eligible))
    # Rows are expected newest-first in runtime memory. Archive only the oldest
    # non-gate-eligible rows and never evict a gate-eligible row.
    active=eligible+ineligible[:keep_ineligible]
    active_ids={id(row) for row in active}
    archive=[row for row in clean if id(row) not in active_ids]
    return active,archive
