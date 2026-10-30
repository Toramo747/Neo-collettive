#!/usr/bin/env python3
"""Export the env vars of a Render service into two files for the VPS migration.

    RENDER_API_KEY=rnd_... python3 export_render_env.py srv-dampj8bm8hqs73ac0an0 ./out

writes, with mode 600:
    out/render.env         config + secrets  -> append to /srv/neo/.env
    out/render-state.env   persisted state   -> ops/hetzner/import_state.sh
and prints only key names and sizes (never values). Works on a suspended
service too: the API keeps serving env vars. For jarvis run it again with its
service id and a different output dir, then copy render.env to /srv/neo/jarvis.env.

Stdlib only, so it runs on any machine with python3.
"""
from __future__ import annotations

import json
import os
import pathlib
import sys
import urllib.parse
import urllib.request

API = "https://api.render.com/v1"
STATE_PREFIXES = ("NEO_STATE_JSON", "NEO_SETI_PRIVATE_JSON", "NEO_EVIDENCE_", "NEO_COMMERCIAL_EVIDENCE_", "NEO_CHALLENGE_TRACK_", "BACKUP_")
SKIP = {"RENDER_API_KEY", "RENDER_SERVICE_ID", "JARVIS_RENDER_SERVICE_ID", "JARVIS_URL", "PORT", "RENDER_GIT_COMMIT", "NEO_STATE_SNAPSHOT_PATH"}


def fetch_all(service_id: str, key: str) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    cursor = None
    for _ in range(50):
        params = {"limit": 100}
        if cursor:
            params["cursor"] = cursor
        req = urllib.request.Request(f"{API}/services/{service_id}/env-vars?" + urllib.parse.urlencode(params),
                                     headers={"Authorization": f"Bearer {key}", "Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=60) as r:
            body = json.load(r)
        if not isinstance(body, list) or not body:
            break
        for item in body:
            env = item.get("envVar") if isinstance(item, dict) else None
            if isinstance(env, dict) and isinstance(env.get("key"), str) and isinstance(env.get("value"), str):
                out.append((env["key"], env["value"]))
        next_cursor = body[-1].get("cursor") if isinstance(body[-1], dict) else None
        if len(body) < 100 or not next_cursor or next_cursor == cursor:
            break
        cursor = next_cursor
    return out


def quote(value: str) -> str:
    # docker compose env_file: double quotes, escape backslash/quote/newline
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n") + '"'


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    key = (os.getenv("RENDER_API_KEY") or "").strip()
    if not key:
        print("set RENDER_API_KEY (Render dashboard -> Account settings -> API keys)")
        return 2
    service_id = sys.argv[1]
    out_dir = pathlib.Path(sys.argv[2] if len(sys.argv) > 2 else "./render-export")
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = fetch_all(service_id, key)
    config, state, skipped = [], [], []
    for k, v in sorted(rows):
        if k in SKIP:
            skipped.append(k)
        elif k.startswith(STATE_PREFIXES):
            state.append((k, v))
        else:
            config.append((k, v))
    for name, items in (("render.env", config), ("render-state.env", state)):
        path = out_dir / name
        path.write_text("".join(f"{k}={quote(v)}\n" for k, v in items), encoding="utf-8")
        os.chmod(path, 0o600)
        print(f"{path}: {len(items)} keys")
        for k, v in items:
            print(f"  {k} ({len(v)} chars)")
    if skipped:
        print("skipped (set by docker-compose): " + ", ".join(skipped))
    return 0


if __name__ == "__main__":
    sys.exit(main())
