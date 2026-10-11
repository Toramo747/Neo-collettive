# SPDX-License-Identifier: BUSL-1.1
"""Independent backup and orphan cleanup for NEO's persisted Render env vars.

Modes
-----
backup <dir>
    GET-only on Render.  Writes every persisted NEO_* value byte-for-byte to
    ``<dir>/env-backup-<stamp>/values/<KEY>`` plus ``manifest.json`` (key,
    sha256, bytes) and re-reads each file to verify.  Meant to run into the
    private archive repo, never into the public repo.

plan
    GET-only.  Lists orphan generations (chunked keys whose generation is not
    referenced by the saved NEO_STATE_JSON chain), keeps every generation still
    needed to cover evidence identities missing from the current memory
    (greedy cover, so reintegration stays possible), and prints the deletion
    plan as counts + a ``plan_id``.  Prints no values.

apply <manifest.json> <plan_id>
    DESTRUCTIVE.  Recomputes the plan and refuses if ``plan_id`` differs, or if
    the backup manifest does not hold the exact sha256 of every key to delete.
    Deletes the keys one by one and verifies each is gone.  Requires explicit
    human authorization; never run automatically.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from render_saved_env import is_persisted_key  # noqa: E402
import render_env_inventory as inv  # noqa: E402

API = inv.API
SERVICE = os.getenv("RENDER_SERVICE_ID", "").strip()
TOKEN = os.getenv("RENDER_API_KEY", "").strip()


def sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def compute_plan(env: dict[str, str]) -> dict:
    from state_codec import decode_checkpoint

    state = decode_checkpoint(env.get("NEO_STATE_JSON") or "") if env.get("NEO_STATE_JSON") else None
    state = state if isinstance(state, dict) else {}
    if not state:
        raise ValueError("saved_state_unreadable")  # never clean without a readable state
    active_ref = state.get("commercial_evidence_store_reference") or state.get("commercial_evidence_memory")
    refs = (inv.referenced_generations(active_ref)
            + inv.referenced_generations(state.get("commercial_evidence_archive_reference"))
            + inv.referenced_generations(state.get("challenge_track_store_reference")))
    referenced = set(refs)
    if not referenced:
        raise ValueError("no_referenced_generation")

    groups: dict[tuple[str, str], dict[int, str]] = {}
    for key, value in env.items():
        m = inv.GEN_RE.match(key)
        if m:
            groups.setdefault((m.group(1), m.group(2)), {})[int(m.group(3))] = key
    head = (inv.referenced_generations(active_ref) or [None])[0]
    head_keys = groups.get(("NEO_EVIDENCE_", head), {}) if head else {}
    ok, digest, head_rows = inv.decode_generation([env[head_keys[i]] for i in sorted(head_keys)]) if head_keys else (False, "", [])
    if not ok or digest[:12] != head:
        raise ValueError("current_head_unverifiable")
    current_ids = {inv.identity(r) for r in head_rows if isinstance(r, dict)}

    # Missing identities per orphan evidence generation (intact only).
    missing_by_gen: dict[str, set[str]] = {}
    freshness: dict[str, float] = {}
    for (prefix, gen), indexed in groups.items():
        if prefix != "NEO_EVIDENCE_" or gen in referenced:
            continue
        ok, digest, rows = inv.decode_generation([env[indexed[i]] for i in sorted(indexed)])
        if ok and digest[:12] == gen:
            missing = {inv.identity(r) for r in rows if isinstance(r, dict)} - current_ids
            if missing:
                missing_by_gen[gen] = missing
                freshness[gen] = inv.newest_seen(rows)
    keep: list[str] = []
    uncovered = set().union(*missing_by_gen.values()) if missing_by_gen else set()
    while uncovered:
        # Most coverage first; on ties the freshest generation (newest last_seen).
        gen = max(sorted(missing_by_gen), key=lambda g: (len(missing_by_gen[g] & uncovered), freshness.get(g, 0.0)))
        if not missing_by_gen[gen] & uncovered:
            break
        keep.append(gen)
        uncovered -= missing_by_gen[gen]

    delete_keys = []
    for (prefix, gen), indexed in sorted(groups.items()):
        if gen in referenced or gen in keep:
            continue
        delete_keys.extend(indexed[i] for i in sorted(indexed))
    freed = sum(len(env[k].encode("utf-8")) for k in delete_keys)
    total = sum(len(v.encode("utf-8")) for v in env.values())
    plan_id = hashlib.sha256("\n".join(f"{k}:{sha(env[k])}" for k in sorted(delete_keys)).encode()).hexdigest()[:16]
    return {
        "plan_id": plan_id if delete_keys else None,
        "delete_keys": sorted(delete_keys),
        "delete_key_count": len(delete_keys),
        "delete_generations": len({inv.GEN_RE.match(k).group(2) for k in delete_keys}),
        "kept_for_reintegration": keep,
        "referenced_generations": len(referenced),
        "bytes_total_before": total,
        "bytes_freed": freed,
        "bytes_total_after": total - freed,
    }


def backup(out_dir: str, env: dict[str, str]) -> dict:
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    root = Path(out_dir) / f"env-backup-{stamp}"
    values = root / "values"
    values.mkdir(parents=True, exist_ok=False)
    manifest = {"schema_v": 1, "created_at_utc": stamp, "service": "neo-collettive", "keys": {}}
    for key in sorted(k for k in env if is_persisted_key(k)):
        path = values / key
        path.write_text(env[key], encoding="utf-8")
        if sha(path.read_text(encoding="utf-8")) != sha(env[key]):
            raise ValueError("backup_readback_mismatch")
        manifest["keys"][key] = {"sha256": sha(env[key]), "bytes": len(env[key].encode("utf-8"))}
    (root / "manifest.json").write_text(json.dumps(manifest, indent=1, sort_keys=True), encoding="utf-8")
    return {"backup_ok": True, "dir": root.name, "keys": len(manifest["keys"]),
            "bytes": sum(v["bytes"] for v in manifest["keys"].values()),
            "manifest_sha256": sha((root / "manifest.json").read_text(encoding="utf-8"))}


def _delete(key: str) -> None:
    url = f"{API}/services/{SERVICE}/env-vars/{urllib.parse.quote(key, safe='')}"
    req = urllib.request.Request(url, method="DELETE", headers={"Authorization": f"Bearer {TOKEN}"})
    urllib.request.build_opener(inv._NoRedirect).open(req, timeout=30).close()
    try:
        inv._get(url)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return
        raise
    raise ValueError("delete_not_effective")


def apply(manifest_path: str, plan_id: str, env: dict[str, str]) -> dict:
    plan = compute_plan(env)
    if not plan["plan_id"] or plan["plan_id"] != plan_id:
        raise ValueError("plan_changed")
    manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    for key in plan["delete_keys"]:
        if (manifest.get("keys") or {}).get(key, {}).get("sha256") != sha(env[key]):
            raise ValueError("backup_missing_or_stale_for_key")
    for key in plan["delete_keys"]:
        _delete(key)
    return {"apply_ok": True, "deleted_keys": len(plan["delete_keys"]), "bytes_freed": plan["bytes_freed"]}


def main(argv: list[str]) -> int:
    global SERVICE, TOKEN
    inv.SERVICE, inv.TOKEN = SERVICE, TOKEN
    if not SERVICE or not TOKEN:
        raise ValueError("credentials_missing")
    mode = argv[1] if len(argv) > 1 else "plan"
    env = inv.list_env()
    if mode == "backup":
        out = backup(argv[2], env)
    elif mode == "plan":
        plan = compute_plan(env)
        out = {k: v for k, v in plan.items() if k != "delete_keys"}
    elif mode == "apply":
        out = apply(argv[2], argv[3], env)
    else:
        raise ValueError("unknown_mode")
    print(json.dumps(out, separators=(",", ":"), sort_keys=True))
    print("::notice title=orphans " + mode + "::" + " ".join(f"{k}={v}" for k, v in sorted(out.items())))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv))
    except Exception as exc:
        print(f"::error title=orphans failed::{type(exc).__name__}:{str(exc)[:80]}")
        raise SystemExit(1)
