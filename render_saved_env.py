"""Boot-time view of the env vars *saved* in Render, not the process env.

Why this exists
---------------
Render applies env var updates made through the API only on the next deploy.
A plain restart (crash, OOM, platform maintenance, free-plan spin down) starts
the process with the env captured at the last deploy. NEO persists its state
and evidence generations as env vars written through the API, so after such
a restart ``os.environ`` holds a *stale* checkpoint: the 10 October restart
reloaded a deploy-time state with ~145 evidences instead of the 200 saved
minutes before, and the next checkpoint overwrote the newer generation's
reference.

This module reads the saved values from the Render API at boot (read-only,
same credentials the checkpoint already uses) and exposes a getter that
prefers them, falling back to ``os.environ`` when the API is not configured or
unreachable.  No value is ever logged or returned in diagnostics: only counts,
key prefixes and generation ids.
"""
from __future__ import annotations

import os
import re
from typing import Any, Callable, Iterable

import httpx

# Keys whose saved value must win over a stale process env.
PERSISTED_PREFIXES = (
    "NEO_STATE_JSON",
    "NEO_SETI_PRIVATE_JSON",
    "NEO_EVIDENCE_",
    "NEO_COMMERCIAL_EVIDENCE_",
    "NEO_CHALLENGE_TRACK_",
)
DEFAULT_TIMEOUT_SECONDS = 8.0
MAX_PAGES = 20
PAGE_LIMIT = 100


def is_persisted_key(key: str) -> bool:
    return any(str(key or "").startswith(p) for p in PERSISTED_PREFIXES)


def _items(body: Any) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    if not isinstance(body, list):
        return out
    for item in body:
        if not isinstance(item, dict):
            continue
        env = item.get("envVar") if isinstance(item.get("envVar"), dict) else item
        key = env.get("key")
        value = env.get("value")
        if isinstance(key, str) and isinstance(value, str):
            out.append((key, value))
    return out


def _cursor(body: Any) -> str | None:
    if isinstance(body, list) and body and isinstance(body[-1], dict):
        cursor = body[-1].get("cursor")
        if isinstance(cursor, str) and cursor:
            return cursor
    return None


def fetch_saved_env(
    api_base: str,
    service_id: str,
    api_key: str,
    *,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    transport: httpx.BaseTransport | None = None,
) -> dict[str, Any]:
    """Return ``{"ok": bool, "values": {key: value}, "reason": str, "pages": n}``.

    Only persisted NEO keys are retained in memory; other env vars (secrets,
    tokens) are dropped immediately and never stored.
    """
    if not api_base or not service_id or not api_key:
        return {"ok": False, "values": {}, "reason": "render_api_not_configured", "pages": 0}
    headers = {"Authorization": f"Bearer {api_key}", "Accept": "application/json"}
    values: dict[str, str] = {}
    names: list[str] = []
    pages = 0
    cursor: str | None = None
    try:
        with httpx.Client(timeout=timeout, follow_redirects=False, transport=transport) as client:
            while pages < MAX_PAGES:
                params: dict[str, Any] = {"limit": PAGE_LIMIT}
                if cursor:
                    params["cursor"] = cursor
                r = client.get(f"{api_base}/services/{service_id}/env-vars", headers=headers, params=params)
                pages += 1
                if not r.is_success:
                    return {"ok": False, "values": {}, "reason": f"http_{r.status_code}", "pages": pages}
                body = r.json()
                batch = _items(body)
                for key, value in batch:
                    names.append(key)
                    if is_persisted_key(key):
                        values[key] = value
                next_cursor = _cursor(body)
                if len(batch) < PAGE_LIMIT or not next_cursor or next_cursor == cursor:
                    return {"ok": True, "values": values, "key_names": names, "reason": "ok", "pages": pages}
                cursor = next_cursor
    except Exception as exc:  # network, JSON, timeout
        return {"ok": False, "values": {}, "reason": type(exc).__name__, "pages": pages}
    return {"ok": False, "values": {}, "reason": "too_many_pages", "pages": pages}


class BootEnv:
    """Getter preferring Render-saved values; ``os.environ`` as fallback."""

    def __init__(self, saved: dict[str, str] | None = None, *, source: str = "process_env_fallback",
                 reason: str = "", environ: Callable[[str], str | None] = os.getenv):
        self.saved = dict(saved or {})
        self.source = source
        self.reason = reason
        self._environ = environ
        self.stale_keys = 0
        self.missing_in_process = 0
        self.saved_only_reads = 0
        self.saved_key_names: list[str] = []

    def get(self, key: str) -> str | None:
        if self.source == "render_api_saved":
            if key in self.saved:
                value = self.saved[key]
                process_value = self._environ(key)
                if process_value is None:
                    self.saved_only_reads += 1
                elif process_value != value:
                    self.stale_keys += 1
                return value
            if is_persisted_key(key):
                # Saved env is authoritative: a key deleted through the API but
                # still present in the stale process env must not resurrect.
                return None
        return self._environ(key)

    def keys(self) -> list[str]:
        if self.source == "render_api_saved":
            return list(self.saved_key_names or self.saved)
        return list(os.environ)

    def items(self) -> list[tuple[str, str]]:
        if self.source == "render_api_saved":
            return list(self.saved.items())
        return [(k, v) for k, v in os.environ.items() if is_persisted_key(k)]

    def status(self) -> dict[str, Any]:
        return {
            "boot_env_source": self.source,
            "reason": self.reason,
            "saved_persisted_keys": len(self.saved),
            "stale_process_values_detected": self.stale_keys,
            "saved_only_reads": self.saved_only_reads,
        }


def load_boot_env(api_base: str | None, service_id: str | None, api_key: str | None, *,
                  enabled: bool = True, timeout: float = DEFAULT_TIMEOUT_SECONDS,
                  transport: httpx.BaseTransport | None = None,
                  environ: Callable[[str], str | None] = os.getenv) -> BootEnv:
    if not enabled:
        return BootEnv(source="process_env_fallback", reason="disabled", environ=environ)
    fetched = fetch_saved_env(api_base or "", service_id or "", api_key or "", timeout=timeout, transport=transport)
    if fetched.get("ok"):
        boot = BootEnv(fetched["values"], source="render_api_saved", reason="ok", environ=environ)
        boot.saved_key_names = list(fetched.get("key_names") or [])
        return boot
    return BootEnv(source="process_env_fallback", reason=str(fetched.get("reason") or "unknown"), environ=environ)


_GEN_RE = re.compile(r"^(NEO_EVIDENCE_ARCHIVE_|NEO_EVIDENCE_|NEO_CHALLENGE_TRACK_)([0-9a-f]{12})_(\d+)$")


def generation_inventory(keys: Iterable[str], referenced_generations: Iterable[str]) -> dict[str, Any]:
    """Count chunked generations and orphans. Keys only, never values."""
    referenced = {str(g) for g in referenced_generations if g}
    families: dict[str, dict[str, int]] = {}
    total = 0
    legacy = 0
    for key in keys:
        total += 1
        if str(key).startswith("NEO_COMMERCIAL_EVIDENCE_"):
            legacy += 1
            continue
        m = _GEN_RE.match(str(key))
        if not m:
            continue
        families.setdefault(m.group(1), {}).setdefault(m.group(2), 0)
        families[m.group(1)][m.group(2)] += 1
    summary: dict[str, Any] = {"persisted_keys": total, "legacy_v1_chunks": legacy, "families": {}}
    orphan_gens: list[str] = []
    for prefix, gens in sorted(families.items()):
        orphans = sorted(g for g in gens if g not in referenced)
        orphan_gens.extend(orphans)
        summary["families"][prefix] = {
            "generations": len(gens),
            "chunks": sum(gens.values()),
            "referenced_generations": len([g for g in gens if g in referenced]),
            "orphan_generations": len(orphans),
            "orphan_chunks": sum(gens[g] for g in orphans),
        }
    summary["orphan_generation_ids"] = orphan_gens  # 12-hex content hashes, not record data
    return summary
