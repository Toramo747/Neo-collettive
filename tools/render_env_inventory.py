# SPDX-License-Identifier: BUSL-1.1
"""Read-only inventory of the env vars saved on the Render service.

Answers two questions without exposing any value, URL, record or identifier:

1. Issue #244: how many env vars / bytes the service carries, by family
   (state, evidence generations, archive, challenge track, BACKUP_* sets,
   other).  Render rejects deploys whose env config is too large.
2. Memory recovery: which evidence generations are still saved, whether each
   is intact (sha256 of the decoded payload matches its generation id), how
   many rows it holds and how many of its identities are missing from the
   generation currently referenced by NEO_STATE_JSON.

The script only issues GET requests.  It never writes, deletes or prints a
value.  Output: one JSON line plus GitHub ``::notice`` annotations (counts).
"""
from __future__ import annotations

import base64
import hashlib
import json
import lzma
import os
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from state_codec import decode_checkpoint  # noqa: E402

API = "https://api.render.com/v1"
SERVICE = os.getenv("RENDER_SERVICE_ID", "").strip()
TOKEN = os.getenv("RENDER_API_KEY", "").strip()

GEN_RE = re.compile(r"^(NEO_EVIDENCE_ARCHIVE_|NEO_EVIDENCE_|NEO_CHALLENGE_TRACK_)([0-9a-f]{12})_(\d+)$")
FAMILIES = (
    ("state", lambda k: k == "NEO_STATE_JSON"),
    ("seti_private", lambda k: k == "NEO_SETI_PRIVATE_JSON"),
    ("evidence_archive", lambda k: k.startswith("NEO_EVIDENCE_ARCHIVE_")),
    ("evidence_active", lambda k: k.startswith("NEO_EVIDENCE_")),
    ("evidence_legacy_v1", lambda k: k.startswith("NEO_COMMERCIAL_EVIDENCE_")),
    ("challenge_track", lambda k: k.startswith("NEO_CHALLENGE_TRACK_")),
    ("backup_sets", lambda k: k.startswith("BACKUP_")),
    ("other", lambda k: True),
)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def _get(url: str):
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {TOKEN}", "Accept": "application/json"})
    with urllib.request.build_opener(_NoRedirect).open(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def list_env() -> dict[str, str]:
    out: dict[str, str] = {}
    cursor = None
    for _ in range(50):
        params = {"limit": "100"}
        if cursor:
            params["cursor"] = cursor
        page = _get(f"{API}/services/{SERVICE}/env-vars?" + urllib.parse.urlencode(params))
        if not isinstance(page, list) or not page:
            break
        for wrapper in page:
            env = wrapper.get("envVar") if isinstance(wrapper.get("envVar"), dict) else wrapper
            if isinstance(env.get("key"), str) and isinstance(env.get("value"), str):
                out[env["key"]] = env["value"]
        if len(page) < 100:
            break
        cursor = str(page[-1].get("cursor") or "")
        if not cursor:
            break
    return out


def family_of(key: str) -> str:
    for name, match in FAMILIES:
        if match(key):
            return name
    return "other"


def identity(row: dict) -> str:
    url = str(row.get("url") or "").strip().lower().rstrip("/")
    if url:
        return "u:" + url
    return "i:" + str(row.get("evidence_id") or row.get("fingerprint") or "")


def decode_generation(chunks: list[str]) -> tuple[bool, str, list]:
    try:
        encoded = "".join(chunks)
        if not encoded.startswith("xz64:"):
            return False, "", []
        raw = lzma.decompress(base64.b64decode(encoded[5:], validate=True))
        rows = json.loads(raw.decode("utf-8"))
        if not isinstance(rows, list):
            return False, "", []
        return True, hashlib.sha256(raw).hexdigest(), rows
    except Exception:
        return False, "", []


def referenced_generations(ref) -> list[str]:
    out = []
    seen = 0
    while isinstance(ref, dict) and seen < 64:
        gen = str(ref.get("generation") or str(ref.get("sha256") or "")[:12])
        if gen:
            out.append(gen)
        ref = ref.get("previous_generation")
        seen += 1
    return out


def main() -> int:
    if not SERVICE or not TOKEN:
        raise ValueError("credentials_missing")
    env = list_env()

    families: dict[str, dict[str, int]] = {}
    for key, value in env.items():
        fam = family_of(key)
        bucket = families.setdefault(fam, {"keys": 0, "value_bytes": 0})
        bucket["keys"] += 1
        bucket["value_bytes"] += len(value.encode("utf-8"))
    backup_sets = sorted({k.split("_")[1] for k in env if k.startswith("BACKUP_") and "_" in k[7:]})

    state = decode_checkpoint(env.get("NEO_STATE_JSON") or "") if env.get("NEO_STATE_JSON") else None
    state = state if isinstance(state, dict) else {}
    active_ref = state.get("commercial_evidence_store_reference") or state.get("commercial_evidence_memory")
    archive_ref = state.get("commercial_evidence_archive_reference")
    challenge_ref = state.get("challenge_track_store_reference")
    current_head = {
        "evidence_active": (referenced_generations(active_ref) or [None])[0],
        "evidence_archive": (referenced_generations(archive_ref) or [None])[0],
    }
    chain = set(referenced_generations(active_ref) + referenced_generations(archive_ref) + referenced_generations(challenge_ref))

    groups: dict[tuple[str, str], dict[int, str]] = {}
    for key, value in env.items():
        m = GEN_RE.match(key)
        if m:
            groups.setdefault((m.group(1), m.group(2)), {})[int(m.group(3))] = value

    decoded: dict[tuple[str, str], tuple[bool, list]] = {}
    for (prefix, gen), indexed in groups.items():
        idx = sorted(indexed)
        contiguous = idx == list(range(len(idx)))
        ok, sha, rows = decode_generation([indexed[i] for i in idx]) if contiguous else (False, "", [])
        decoded[(prefix, gen)] = (ok and sha[:12] == gen, rows if ok else [])

    current_ids = set()
    for prefix, fam in (("NEO_EVIDENCE_", "evidence_active"), ("NEO_EVIDENCE_ARCHIVE_", "evidence_archive")):
        head = current_head.get(fam)
        if head and (prefix, head) in decoded:
            current_ids |= {identity(r) for r in decoded[(prefix, head)][1] if isinstance(r, dict)}

    generations = []
    recoverable_ids = set()
    for (prefix, gen), (intact, rows) in sorted(decoded.items()):
        ids = {identity(r) for r in rows if isinstance(r, dict)}
        missing = ids - current_ids if prefix != "NEO_CHALLENGE_TRACK_" else set()
        if intact and prefix != "NEO_CHALLENGE_TRACK_":
            recoverable_ids |= missing
        generations.append({
            "family": prefix.rstrip("_").lower(),
            "generation": gen,  # 12-hex content hash, not record data
            "chunks": len(groups[(prefix, gen)]),
            "intact": intact,
            "rows": len(rows),
            "referenced": gen in chain,
            "is_current_head": gen in current_head.values(),
            "identities_missing_from_current": len(missing),
        })

    summary = {
        "inventory_ok": True,
        "total_keys": len(env),
        "total_value_bytes": sum(len(v.encode("utf-8")) for v in env.values()),
        "families": families,
        "backup_set_count": len(backup_sets),
        "state": {
            "cycles_completed": state.get("cycles_completed"),
            "state_generation": state.get("state_generation"),
            "saved_at_utc": state.get("state_saved_at_utc"),
            "current_identities": len(current_ids),
        },
        "generations": generations,
        "recoverable_identities_not_in_current": len(recoverable_ids),
    }
    print(json.dumps(summary, separators=(",", ":"), sort_keys=True))
    # GitHub keeps at most 10 notices per step: keep the output to 6 lines.
    print(f"::notice title=env totals::keys={summary['total_keys']} bytes={summary['total_value_bytes']} backup_sets={len(backup_sets)}")
    print("::notice title=families::" + " ".join(f"{fam}={b['keys']}k/{b['value_bytes']}B" for fam, b in sorted(families.items())))
    st = summary["state"]
    print(f"::notice title=state::cycles={st['cycles_completed']} generation={st['state_generation']} saved_at={st['saved_at_utc']} current_identities={st['current_identities']}")
    def fmt(g):
        return f"{g['generation']}:c{g['chunks']}:{'ok' if g['intact'] else 'BAD'}:r{g['rows']}:{'ref' if g['referenced'] else 'orphan'}{':HEAD' if g['is_current_head'] else ''}:miss{g['identities_missing_from_current']}"
    for fam in ("neo_evidence", "neo_evidence_archive", "neo_challenge_track"):
        items = [fmt(g) for g in generations if g["family"] == fam]
        print(f"::notice title=gens {fam} ({len(items)})::" + (" ".join(items) or "none"))
    print(f"::notice title=recoverable::identities_not_in_current={summary['recoverable_identities_not_in_current']}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(json.dumps({"inventory_ok": False, "reason": type(exc).__name__}, separators=(",", ":")))
        print(f"::error title=inventory failed::{type(exc).__name__}")
        raise SystemExit(1)
