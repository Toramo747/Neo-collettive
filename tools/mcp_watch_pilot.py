# SPDX-License-Identifier: BUSL-1.1
"""MCP watch pilot (26/10, Andrea's ok): for 7 days, read the tool definitions of a fixed sample of public MCP servers
from the official registry once a day (initialize + tools/list only, never a tool call, no credentials) and count how
often they change. Honors data/registry-health/opt-out.txt. Prints aggregates only; per-server state is hashes in a
private Actions cache, never published. Decides whether a paid "watch" (signed alert on change) has a market."""
from __future__ import annotations

import asyncio
import hashlib
import json
import random
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx

import mcp_endpoint_verifier as ev
import registry_health as rh

SAMPLE = 150
SEED = 20261026
STATE = Path(sys.argv[1] if len(sys.argv) > 1 else "mcp-watch-state.json")


def _norm(text: str) -> str:
    """27/10 (skitter's idea): digits to #, whitespace collapsed, so dates, versions and counters do not count as change."""
    return re.sub(r"\s+", " ", re.sub(r"\d+", "#", text)).strip()


def tool_hashes(tools: list[dict]) -> tuple[dict[str, str], dict[str, str]]:
    raw, norm = {}, {}
    for t in tools:
        canon = json.dumps({"d": t.get("description"), "s": t.get("input_schema")}, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        k = hashlib.sha256(str(t.get("name")).encode()).hexdigest()[:16]
        raw[k] = hashlib.sha256(canon.encode()).hexdigest()[:16]
        norm[k] = hashlib.sha256(_norm(canon).encode()).hexdigest()[:16]
    return raw, norm


async def read_one(url: str, sem: asyncio.Semaphore) -> dict | None:
    async with sem:
        try:
            v = await asyncio.wait_for(ev.verify_endpoint(url=url, caller="mcp-watch-pilot", usage_scope="internal_registry_health",
                                                          enforce_rate_limit=False, full_tools=True, client_version="mcp-watch-pilot"), timeout=40)
        except Exception:
            return None
    tools = ((v.get("checks") or {}).get("tools_list") or {}).get("full_tools") or []
    if not tools:
        return {"live": bool(v.get("live")), "tools": None, "tools_n": None}
    raw, norm = tool_hashes(tools)
    return {"live": bool(v.get("live")), "tools": raw, "tools_n": norm}


def already_ran_today(state: dict, now: datetime | None = None) -> bool:
    """True when the last recorded row is from the same UTC date: the pilot counts calendar days, not launches."""
    rows = state.get("days") or []
    if not rows:
        return False
    today = (now or datetime.now(timezone.utc)).isoformat()[:10]
    return str(rows[-1].get("utc") or "")[:10] == today


async def main() -> None:
    async with httpx.AsyncClient(timeout=30, trust_env=False) as c:
        reg = await rh.fetch_complete_registry(c)
    opt = rh.read_opt_out()
    remote = [s for s in reg["servers"] if s["access_class"] == "remote" and not rh.is_opted_out(s, opt)]
    random.Random(SEED).shuffle(remote)
    state = json.loads(STATE.read_text()) if STATE.exists() else {"day": 0, "first": None, "prev": {}, "ever_changed": [], "days": []}
    if already_ran_today(state):
        # 27/10: two manual launches 13 minutes apart consumed "day 2" and "day 3". One row per UTC date from now on.
        print(f"::notice title=mcp watch pilot::already ran today (day {state['day']}), nothing read")
        return
    sample = remote[:SAMPLE] if not state["prev"] else [s for s in remote if hashlib.sha256(s["name"].encode()).hexdigest()[:16] in state["prev"]] or remote[:SAMPLE]
    sem = asyncio.Semaphore(8)
    reads = await asyncio.gather(*[read_one(s["remotes"][0]["url"], sem) for s in sample])
    today = {}
    for s, r in zip(sample, reads):
        today[hashlib.sha256(s["name"].encode()).hexdigest()[:16]] = r
    prev = state["prev"]
    with_tools = [k for k, r in today.items() if r and r["tools"]]
    changed = added = removed = edited = 0
    content_changed = numbers_only = norm_compared = 0
    for k in with_tools:
        p = (prev.get(k) or {}).get("tools")
        if not p:
            continue
        t = today[k]["tools"]
        if t != p:
            changed += 1
            if k not in state["ever_changed"]:
                state["ever_changed"].append(k)
            added += len(set(t) - set(p))
            removed += len(set(p) - set(t))
            edited += sum(1 for n in set(t) & set(p) if t[n] != p[n])
            pn, tn = (prev.get(k) or {}).get("tools_n"), today[k].get("tools_n")
            if pn and tn:
                norm_compared += 1
                if tn != pn:
                    content_changed += 1
                else:
                    numbers_only += 1
    went_dark = sum(1 for k, r in today.items() if (prev.get(k) or {}).get("tools") and not (r and r["tools"]))
    state["day"] += 1
    state["first"] = state["first"] or datetime.now(timezone.utc).isoformat()[:16]
    row = {"day": state["day"], "utc": datetime.now(timezone.utc).isoformat()[:16], "sampled": len(sample), "answered_with_tools": len(with_tools),
           "compared": sum(1 for k in with_tools if (prev.get(k) or {}).get("tools")), "changed": changed, "tools_added": added,
           "tools_removed": removed, "tools_edited": edited,
           "changed_content": content_changed, "changed_numbers_only": numbers_only, "norm_compared_changes": norm_compared, "went_dark": went_dark, "ever_changed": len(state["ever_changed"])}
    state["days"].append(row)
    state["prev"] = {k: r for k, r in today.items() if r}
    STATE.write_text(json.dumps(state))
    print(f"::notice title=mcp watch pilot day {row['day']}::{json.dumps(row)} (registry remote servers after opt-out: {len(remote)})")


if __name__ == "__main__":
    asyncio.run(main())
