# SPDX-License-Identifier: BUSL-1.1
"""Call the admin reintegration endpoint and print counts only (GitHub notices).

Usage: evidence_reintegration_call.py status | plan | apply <plan_id> | revert <batch>
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

ORIGIN = "https://neo-collettive.onrender.com"
TOKEN = os.environ["NEO_ADMIN_TOKEN"].strip()
KEEP = ("ok", "mode", "plan_id", "candidates", "gate_eligible", "intact_generations", "skipped_expired_rows",
        "rows", "batch", "active_count", "reason", "action")


def call(path: str, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(ORIGIN + path, data=data, method="POST" if body is not None else "GET", headers={
        "Authorization": "Bearer " + TOKEN, "Accept": "application/json", "Content-Type": "application/json",
        "X-MYCELIX-Self-Traffic": "github-actions-evidence-reintegration"})
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as exc:
        try:
            return exc.code, json.loads(exc.read() or b"{}")
        except Exception:
            return exc.code, {}


def main(argv):
    mode = argv[1] if len(argv) > 1 else "status"
    if mode == "status":
        code, out = call("/api/memory/status")
        guard = out.get("state_generation_guard") or {}
        boot = out.get("boot_env") or {}
        print(f"::notice title=memory status::http={code} boot_env_source={boot.get('boot_env_source')} reason={boot.get('reason')} "
              f"saved_keys={boot.get('saved_persisted_keys')} stale_detected={boot.get('stale_process_values_detected')} "
              f"state_generation={out.get('state_generation')} guard={guard.get('status')} loaded={guard.get('loaded_generation')} saved={guard.get('saved_generation')}")
        return 0 if code == 200 else 1
    body = {"mode": mode}
    if mode == "apply":
        body["confirm"] = argv[2]
    if mode == "revert":
        body["batch"] = argv[2]
    code, out = call("/api/admin/evidence-reintegration", body)
    print(f"::notice title=reintegration {mode}::http={code} " + " ".join(f"{k}={out[k]}" for k in KEEP if k in out))
    return 0 if code == 200 else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
