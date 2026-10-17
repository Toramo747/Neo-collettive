"""Emergency-only pre-deploy check for a continuity-blocked checkpoint.

2026-10-14: after a rolled-back deploy, the surviving instance refused every
checkpoint ("stale_generation_write_blocked") because the dead instance had
written a newer generation once. The fix ships in the next deploy, but the
pre-deploy gate needs a healthy checkpoint from the running instance. This
script allows an Andrea-authorized emergency deploy ONLY when:
  * the runtime's last checkpoint failed for exactly that reason, and
  * runtime memory is intact (evidence >= published floor, cycles >= published floor).
Prints numeric aggregates only.
"""
import json
import os
import sys
import urllib.request

ORIGIN = "https://neo-collettive.onrender.com"


def validate_runtime(state: dict, snapshot: dict, cycle_floor: dict) -> dict:
    reason = str((state.get("last_checkpoint") or {}).get("reason") or "")
    store_reason = str((state.get("evidence_store_status") or {}).get("reason") or "")
    # 2026-10-17: the same continuity block leaves the store "degraded", and with
    # an inline store every later checkpoint fails with this message instead.
    blocked = reason == "stale_generation_write_blocked" or (
        reason == "RuntimeError:degraded evidence store missing original reference"
        and store_reason == "stale_generation_write_blocked")
    evidence = int((state.get("evidence_memory_telemetry") or {}).get("evidence_out") or 0)
    cycles = int(state.get("cycles_completed") or 0)
    published = snapshot.get("autopilot") or {}
    evidence_floor = int((published.get("select_diagnostics") or {}).get("persistent_evidence_items") or 0)
    floor = max(int(cycle_floor.get("cycles_completed") or 0), int(published.get("cycles_completed") or 0))
    return {"reason_is_continuity_block": blocked,
            "evidence_out": evidence, "evidence_floor": evidence_floor,
            "cycles": cycles, "cycle_floor": floor,
            "allowed": blocked and evidence_floor > 0
                       and floor > 0 and evidence >= evidence_floor and cycles >= floor}


def main() -> int:
    req = urllib.request.Request(ORIGIN + "/api/autopilot/status", headers={
        "Authorization": "Bearer " + os.environ["NEO_ADMIN_TOKEN"],
        "X-MYCELIX-Self-Traffic": "github-actions-deploy"})
    with urllib.request.urlopen(req, timeout=30) as r:
        state = (json.load(r).get("autopilot") or {})
    with open("/tmp/predeploy-public-snapshot.json", encoding="utf-8") as f:
        snapshot = json.load(f)
    with open("/tmp/predeploy-cycle-floor.json", encoding="utf-8") as f:
        cycle_floor = json.load(f)
    out = validate_runtime(state, snapshot, cycle_floor)
    print("continuity_bootstrap " + json.dumps(out, separators=(",", ":")))
    if not out["allowed"]:
        return 1
    open("/tmp/checkpoint-continuity-bootstrap", "w").write(json.dumps(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
