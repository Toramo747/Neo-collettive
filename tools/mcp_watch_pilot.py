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
import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx

import mcp_endpoint_verifier as ev
import registry_health as rh

SAMPLE = 150
SEED = 20261026
STATE = Path(sys.argv[1] if len(sys.argv) > 1 else "mcp-watch-state.json")


def tool_hashes(tools: list[dict]) -> dict[str, str]:
    out = {}
    for t in tools:
        canon = json.dumps({"d": t.get("description"), "s": t.get("input_schema")}, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        out[hashlib.sha256(str(t.get("name")).encode()).hexdigest()[:16]] = hashlib.sha256(canon.encode()).hexdigest()[:16]
    return out


async def read_one(url: str, sem: asyncio.Semaphore) -> dict | None:
    async with sem:
        try:
            v = await asyncio.wait_for(ev.verify_endpoint(url=url, caller="mcp-watch-pilot", usage_scope="internal_registry_health",
                                                          enforce_rate_limit=False, full_tools=True, client_version="mcp-watch-pilot"), timeout=40)
        except Exception:
            return None
    tools = ((v.get("checks") or {}).get("tools_list") or {}).get("full_tools") or []
    return {"live": bool(v.get("live")), "tools": tool_hashes(tools)} if tools else {"live": bool(v.get("live")), "tools": None}


async def main() -> None:
    async with httpx.AsyncClient(timeout=30, trust_env=False) as c:
        reg = await rh.fetch_complete_registry(c)
    opt = rh.read_opt_out()
    remote = [s for s in reg["servers"] if s["access_class"] == "remote" and not rh.is_opted_out(s, opt)]
    random.Random(SEED).shuffle(remote)
    state = json.loads(STATE.read_text()) if STATE.exists() else {"day": 0, "first": None, "prev": {}, "ever_changed": [], "days": []}
    sample = remote[:SAMPLE] if not state["prev"] else [s for s in remote if hashlib.sha256(s["name"].encode()).hexdigest()[:16] in state["prev"]] or remote[:SAMPLE]
    sem = asyncio.Semaphore(8)
    reads = await asyncio.gather(*[read_one(s["remotes"][0]["url"], sem) for s in sample])
    today = {}
    for s, r in zip(sample, reads):
        today[hashlib.sha256(s["name"].encode()).hexdigest()[:16]] = r
    prev = state["prev"]
    with_tools = [k for k, r in today.items() if r and r["tools"]]
    changed = added = removed = edited = 0
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
    went_dark = sum(1 for k, r in today.items() if (prev.get(k) or {}).get("tools") and not (r and r["tools"]))
    state["day"] += 1
    state["first"] = state["first"] or datetime.now(timezone.utc).isoformat()[:16]
    row = {"day": state["day"], "utc": datetime.now(timezone.utc).isoformat()[:16], "sampled": len(sample), "answered_with_tools": len(with_tools),
           "compared": sum(1 for k in with_tools if (prev.get(k) or {}).get("tools")), "changed": changed, "tools_added": added,
           "tools_removed": removed, "tools_edited": edited, "went_dark": went_dark, "ever_changed": len(state["ever_changed"])}
    state["days"].append(row)
    state["prev"] = {k: r for k, r in today.items() if r}
    STATE.write_text(json.dumps(state))
    print(f"::notice title=mcp watch pilot day {row['day']}::{json.dumps(row)} (registry remote servers after opt-out: {len(remote)})")


if __name__ == "__main__":
    asyncio.run(main())
