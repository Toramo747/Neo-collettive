#!/usr/bin/env python3
"""Alarm for the paid x402 routes (24/10): read the public counters, compare with the last check, fail on trouble.

  python tools/x402_health.py <private_dir>
Fails (exit 1, so GitHub notifies Andrea) when, since the last check, any of these grew:
  facilitator_http_error, settle_failed, or our_failure_not_charged by 3+.
Nothing is posted anywhere. 404 (not deployed yet) or enabled=false is a notice, not a failure.
"""
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

URL = "https://neo-collettive.onrender.com/x402"
ALARM = {"facilitator_http_error": 1, "settle_failed": 1, "our_failure_not_charged": 3, "settle_uncertain_delivered": 1,
         "client_gone_not_charged": 2}


def check(now: dict, before: dict) -> list[str]:
    c, p = now.get("counters_since_start") or {}, before.get("counters_since_start") or {}
    restarted = any(c.get(k, 0) < p.get(k, 0) for k in c)  # counters reset on deploy
    base = {} if restarted else p
    return [f"{k} +{c.get(k, 0) - base.get(k, 0)}" for k, lim in ALARM.items() if c.get(k, 0) - base.get(k, 0) >= lim]


def main(private_dir: str, fetch=None) -> int:
    state = Path(private_dir) / "common" / "x402" / "health.json"
    try:
        now = fetch() if fetch else json.loads(urllib.request.urlopen(urllib.request.Request(URL, headers={"User-Agent": "neo-x402-health"}), timeout=60).read())
    except urllib.error.HTTPError as e:
        print(f"::notice title=x402 health::HTTP {e.code} (not deployed yet?)")
        return 0
    before = json.loads(state.read_text()) if state.exists() else {}
    state.parent.mkdir(parents=True, exist_ok=True)
    state.write_text(json.dumps(now))
    c = now.get("counters_since_start") or {}
    paid = now.get("paid_since_launch") or {}
    total = sum(int(v.get("calls", 0)) for v in paid.values())
    usd = round(sum(float(v.get("usd", 0)) for v in paid.values()), 2)
    by = ",".join(f"{k}={v.get('calls', 0)}" for k, v in sorted(paid.items())) or "-"
    print(f"::notice title=x402 health::enabled={now.get('enabled')} paid_and_served={c.get('paid_and_served', 0)} asked_to_pay={c.get('asked_to_pay', 0)} "
          f"paid_since_launch={total} usd={usd} by_service={by}")
    bad = check(now, before)
    if bad:
        print("::error title=x402 paid routes need Andrea::" + ", ".join(bad))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]) if len(sys.argv) == 2 else 2)
