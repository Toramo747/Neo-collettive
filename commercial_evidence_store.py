from __future__ import annotations

import base64
import hashlib
import json
import lzma
from typing import Any

STORE_SCHEMA_V = 1
STORE_PREFIX = "xz64:"
DEFAULT_CHUNK_BYTES = 60_000


def _canonical_rows(rows: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    return [row for row in (rows or []) if isinstance(row, dict)]


def _raw_bytes(rows: list[dict[str, Any]] | None) -> bytes:
    return json.dumps(
        _canonical_rows(rows),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def evidence_hash(rows: list[dict[str, Any]] | None) -> str:
    return hashlib.sha256(_raw_bytes(rows)).hexdigest()


def encode_external_store(
    rows: list[dict[str, Any]] | None,
    *,
    chunk_bytes: int = DEFAULT_CHUNK_BYTES,
) -> tuple[dict[str, Any], list[str]]:
    clean = _canonical_rows(rows)
    raw = _raw_bytes(clean)
    packed = lzma.compress(raw, preset=3)
    encoded = STORE_PREFIX + base64.b64encode(packed).decode("ascii")
    size = max(1024, int(chunk_bytes))
    chunks = [encoded[i:i + size] for i in range(0, len(encoded), size)] or [STORE_PREFIX]
    ref = {
        "schema_v": STORE_SCHEMA_V,
        "store_mode": "external",
        "store": "render_env_chunks_v1",
        "sha256": hashlib.sha256(raw).hexdigest(),
        "evidence_count": len(clean),
        "chunk_count": len(chunks),
        "raw_bytes": len(raw),
    }
    return ref, chunks


def decode_external_store(
    reference: dict[str, Any] | None,
    chunks: list[str] | None,
) -> list[dict[str, Any]] | None:
    ref = reference if isinstance(reference, dict) else {}
    if ref.get("store_mode") != "external" or ref.get("store") != "render_env_chunks_v1":
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


def is_external_reference(value: Any) -> bool:
    return (
        isinstance(value, dict)
        and value.get("store_mode") == "external"
        and value.get("store") == "render_env_chunks_v1"
    )
