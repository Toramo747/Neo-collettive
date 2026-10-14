"""Emergency-only pre-deploy check for a continuity-blocked checkpoint.

2026-10-14: after a rolled-back deploy, the surviving instance refused every
checkpoint ("stale_generation_write_blocked") because the dead instance had
written a newer generation once. The fix ships in the next deploy, but the
pre-deploy gate needs a healthy checkpoint from the running instance. This
script allows an Andrea-authorized emergency deploy ONLY when:
  * the runtime's last checkpoint failed for exactly that reason, and
  * runtime memory is intact (evidence >= 141 floor, cycles >= published floor).
Prints numeric aggregates only.
"""
import json
import os
import sys
import urllib.request

ORIGIN = "https://neo-collettive.onrender.com"


def main() -> int:
    req = urllib.request.Request(ORIGIN + "/api/autopilot/status", headers={
        "Authorization": "Bearer " + os.environ["NEO_ADMIN_TOKEN"],
        "X-MYCELIX-Self-Traffic": "github-actions-deploy"})
    with urllib.request.urlopen(req, timeout=30) as r:
        state = (json.load(r).get("autopilot") or {})
    reason = str((state.get("last_checkpoint") or {}).get("reason") or "")
    evidence = int((state.get("evidence_memory_telemetry") or {}).get("evidence_out") or 0)
    cycles = int(state.get("cycles_completed") or 0)
    floor = int(json.load(open("neo_cycle_floor.json", encoding="utf-8")).get("cycles_completed") or 0)
    out = {"reason_is_continuity_block": reason == "stale_generation_write_blocked",
           "evidence_out": evidence, "cycles": cycles, "cycle_floor": floor}
    print("continuity_bootstrap " + json.dumps(out, separators=(",", ":")))
    if reason != "stale_generation_write_blocked":
        return 1
    if evidence < 141 or cycles < floor:
        return 1
    open("/tmp/checkpoint-continuity-bootstrap", "w").write(json.dumps(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
