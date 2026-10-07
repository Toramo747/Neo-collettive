# SPDX-License-Identifier: BUSL-1.1
"""Read first, then create an immutable Render-side backup for memory repair.

The script never mutates NEO_STATE_JSON or any NEO_EVIDENCE_* key. It snapshots
all current evidence generations plus the authenticated runtime state into new
BACKUP_<timestamp>_* variables and prints aggregate hashes/counts only.
"""
from __future__ import annotations

import base64
from datetime import datetime, timezone
import hashlib
import json
import lzma
import os
import re
import sys
import urllib.parse
import urllib.request
import zlib

from state_codec import decode_checkpoint

API = "https://api.render.com/v1"
ORIGIN = "https://neo-collettive.onrender.com"
SERVICE = os.getenv("RENDER_SERVICE_ID", "srv-dampj8bm8hqs73ac0an0").strip()
RENDER_TOKEN = os.environ["RENDER_API_KEY"].strip()
ADMIN_TOKEN = os.environ["NEO_ADMIN_TOKEN"].strip()

ACTIVE_RE = re.compile(r"^NEO_EVIDENCE_([0-9a-f]{12})_(\d+)$")
ARCHIVE_RE = re.compile(r"^NEO_EVIDENCE_ARCHIVE_([0-9a-f]{12})_(\d+)$")
LEGACY_RE = re.compile(r"^NEO_COMMERCIAL_EVIDENCE_(\d+)$")
SOURCE_PREFIXES = (
    "NEO_EVIDENCE_",
    "NEO_EVIDENCE_ARCHIVE_",
    "NEO_COMMERCIAL_EVIDENCE_",
)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise ValueError("redirect_forbidden")


def _request(url: str, *, method: str = "GET", body=None, admin: bool = False):
    headers = {"Accept": "application/json"}
    if admin:
        headers["Authorization"] = "Bearer " + ADMIN_TOKEN
        headers["X-MYCELIX-Self-Traffic"] = "github-actions-memory-repair-backup"
    else:
        headers["Authorization"] = "Bearer " + RENDER_TOKEN
    raw_body = None
    if body is not None:
        raw_body = json.dumps(body, separators=(",", ":")).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=raw_body, method=method, headers=headers)
    with urllib.request.build_opener(NoRedirect).open(req, timeout=45) as response:
        raw = response.read(32 * 1024 * 1024 + 1)
    if len(raw) > 32 * 1024 * 1024:
        raise ValueError("response_too_large")
    return json.loads(raw.decode("utf-8")) if raw else None


def _list_env() -> dict[str, str]:
    out: dict[str, str] = {}
    cursor = None
    while True:
        params = {"limit": "100"}
        if cursor:
            params["cursor"] = cursor
        url = f"{API}/services/{SERVICE}/env-vars?" + urllib.parse.urlencode(params)
        page = _request(url)
        if not isinstance(page, list):
            raise ValueError("invalid_env_list")
        if not page:
            break
        for wrapper in page:
            if not isinstance(wrapper, dict):
                raise ValueError("invalid_env_row")
            env = wrapper.get("envVar") if isinstance(wrapper.get("envVar"), dict) else wrapper
            key = env.get("key")
            value = env.get("value")
            if not isinstance(key, str) or not isinstance(value, str):
                raise ValueError("invalid_env_value")
            out[key] = value
        if len(page) < 100:
            break
        cursor = str(page[-1].get("cursor") or "")
        if not cursor:
            raise ValueError("pagination_cursor_missing")
    return out


def _extract_value(payload) -> str | None:
    if isinstance(payload, dict):
        if isinstance(payload.get("value"), str):
            return payload["value"]
        for key in ("envVar", "env_var"):
            item = payload.get(key)
            if isinstance(item, dict) and isinstance(item.get("value"), str):
                return item["value"]
    return None


def _put_backup(key: str, value: str, existing_keys: set[str]) -> None:
    if key in existing_keys:
        raise ValueError("backup_key_collision")
    encoded = urllib.parse.quote(key, safe="")
    url = f"{API}/services/{SERVICE}/env-vars/{encoded}"
    _request(url, method="PUT", body={"value": value})
    readback = _request(url)
    if _extract_value(readback) != value:
        raise ValueError("backup_readback_mismatch")
    existing_keys.add(key)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical_json_bytes(value) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")


def _decode_generation(chunks: list[str]) -> tuple[str, int, int]:
    encoded = "".join(chunks)
    if not encoded.startswith("xz64:"):
        raise ValueError("generation_encoding_invalid")
    packed = base64.b64decode(encoded[5:], validate=True)
    raw = lzma.decompress(packed)
    decoded = json.loads(raw.decode("utf-8"))
    if not isinstance(decoded, list) or any(not isinstance(row, dict) for row in decoded):
        raise ValueError("generation_payload_invalid")
    return _sha(raw), len(decoded), len(raw)


def _generation_inventory(env: dict[str, str]) -> list[dict]:
    groups: dict[tuple[str, str], dict[int, str]] = {}
    for key, value in env.items():
        match = ARCHIVE_RE.match(key)
        if match:
            group = ("archive", match.group(1))
            groups.setdefault(group, {})[int(match.group(2))] = value
            continue
        match = ACTIVE_RE.match(key)
        if match:
            group = ("active", match.group(1))
            groups.setdefault(group, {})[int(match.group(2))] = value
            continue
        match = LEGACY_RE.match(key)
        if match:
            groups.setdefault(("active_legacy", "legacy"), {})[int(match.group(1))] = value

    inventory = []
    for (kind, generation), indexed in sorted(groups.items()):
        indexes = sorted(indexed)
        if indexes != list(range(len(indexes))):
            raise ValueError("generation_chunks_noncontiguous")
        chunks = [indexed[index] for index in indexes]
        sha256, rows, raw_bytes = _decode_generation(chunks)
        if generation != "legacy" and sha256[:12] != generation:
            raise ValueError("generation_name_hash_mismatch")
        inventory.append({
            "kind": kind,
            "generation": generation,
            "chunks": len(chunks),
            "sha256": sha256,
            "rows": rows,
            "raw_bytes": raw_bytes,
        })
    return inventory


def _checkpoint_summary(value: str) -> dict:
    payload = decode_checkpoint(value)
    if not isinstance(payload, dict):
        raise ValueError("checkpoint_decode_failed")
    memory = payload.get("commercial_evidence_memory")
    if isinstance(memory, list):
        rows = len([row for row in memory if isinstance(row, dict)])
    elif isinstance(memory, dict):
        rows = max(0, int(memory.get("evidence_count") or 0))
    else:
        rows = 0
    return {
        "value_sha256": _sha(value.encode("utf-8")),
        "rows": rows,
        "cycles_completed": max(0, int(payload.get("cycles_completed") or 0)),
        "state_saved_at_utc": payload.get("state_saved_at_utc"),
    }


def _runtime_snapshot() -> tuple[bytes, dict]:
    payload = _request(ORIGIN + "/api/autopilot/status", admin=True)
    if not isinstance(payload, dict) or payload.get("ok") is not True:
        raise ValueError("runtime_export_failed")
    state = payload.get("autopilot")
    if not isinstance(state, dict):
        raise ValueError("runtime_state_missing")
    raw = _canonical_json_bytes(state)
    memory = state.get("commercial_evidence_memory")
    rows = len([row for row in memory if isinstance(row, dict)]) if isinstance(memory, list) else 0
    return raw, {
        "sha256": _sha(raw),
        "rows": rows,
        "cycles_completed": max(0, int(state.get("cycles_completed") or 0)),
    }


def _runtime_chunks(raw: bytes, size: int = 50000) -> list[str]:
    encoded = "zlib64:" + base64.b64encode(zlib.compress(raw, 9)).decode("ascii")
    return [encoded[i:i + size] for i in range(0, len(encoded), size)] or ["zlib64:"]


def main() -> int:
    if not SERVICE or not RENDER_TOKEN or not ADMIN_TOKEN:
        raise ValueError("backup_credentials_missing")

    # PASSO 0 invariant: complete every read and verification before first write.
    env = _list_env()
    checkpoint = env.get("NEO_STATE_JSON")
    if not isinstance(checkpoint, str) or not checkpoint:
        raise ValueError("checkpoint_missing")
    source_keys = sorted(
        key for key in env
        if key == "NEO_STATE_JSON" or key.startswith(SOURCE_PREFIXES)
    )
    if not source_keys:
        raise ValueError("backup_sources_missing")

    checkpoint_summary = _checkpoint_summary(checkpoint)
    generations = _generation_inventory(env)
    runtime_raw, runtime_summary = _runtime_snapshot()
    runtime_chunks = _runtime_chunks(runtime_raw)

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    prefix = f"BACKUP_{stamp}"
    if any(key.startswith(prefix + "_") for key in env):
        raise ValueError("backup_prefix_collision")

    manifest = {
        "schema_v": 1,
        "backup_prefix": prefix,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_env_count": len(source_keys),
        "checkpoint": checkpoint_summary,
        "generations": generations,
        "runtime": {**runtime_summary, "chunks": len(runtime_chunks)},
        "sources": [
            {
                "source_key": key,
                "backup_key": f"{prefix}_ENV_{key}",
                "value_sha256": _sha(env[key].encode("utf-8")),
                "value_bytes": len(env[key].encode("utf-8")),
            }
            for key in source_keys
        ],
    }

    existing = set(env)
    # Backup original Render values byte-for-byte.
    for row in manifest["sources"]:
        _put_backup(row["backup_key"], env[row["source_key"]], existing)

    # Backup the live runtime independently from the durable checkpoint.
    for index, chunk in enumerate(runtime_chunks):
        _put_backup(f"{prefix}_RUNTIME_{index}", chunk, existing)

    manifest_bytes = _canonical_json_bytes(manifest)
    manifest_key = f"{prefix}_MANIFEST"
    _put_backup(manifest_key, manifest_bytes.decode("utf-8"), existing)

    summary = {
        "backup_ok": True,
        "backup_prefix": prefix,
        "manifest_sha256": _sha(manifest_bytes),
        "source_env_count": len(source_keys),
        "checkpoint_sha256": checkpoint_summary["value_sha256"],
        "checkpoint_rows": checkpoint_summary["rows"],
        "checkpoint_cycles": checkpoint_summary["cycles_completed"],
        "runtime_sha256": runtime_summary["sha256"],
        "runtime_rows": runtime_summary["rows"],
        "runtime_cycles": runtime_summary["cycles_completed"],
        "generations": [
            {
                "kind": row["kind"],
                "generation": row["generation"],
                "sha256": row["sha256"],
                "rows": row["rows"],
                "chunks": row["chunks"],
            }
            for row in generations
        ],
    }
    print(json.dumps(summary, separators=(",", ":"), sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(json.dumps({
            "backup_ok": False,
            "reason": type(exc).__name__,
        }, separators=(",", ":"), sort_keys=True))
        raise SystemExit(1)
