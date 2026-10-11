# SPDX-License-Identifier: BUSL-1.1
"""Who is talking to MYCELIX? Aggregate-only view of the live inbound summary.

Prints counts only. Origins (IPs, raw user agents) are never printed: real
contacts are reduced to a number of distinct callers and a coarse client
family; crawlers are named only when they match a public bot allowlist.
"""
from __future__ import annotations

import json
import re
import sys

BOTS = ("GPTBot", "ChatGPT-User", "OAI-SearchBot", "ClaudeBot", "Claude-User", "Claude-SearchBot", "anthropic-ai",
        "PerplexityBot", "Perplexity-User", "Google-Extended", "Googlebot", "bingbot", "Applebot", "Bytespider",
        "CCBot", "Amazonbot", "meta-externalagent", "DuckDuckBot", "YandexBot", "Baiduspider", "SemrushBot",
        "AhrefsBot", "MJ12bot", "DotBot", "PetalBot", "Censys", "Shodan", "zgrab", "masscan", "Expanse",
        "Palo Alto", "InternetMeasurement", "ModatScanner", "Smithery", "glama", "mcp-registry", "a2a")
FAMILIES = (("python", r"python|httpx|aiohttp|requests"), ("node", r"node|axios|undici|got\b"),
            ("curl", r"curl|wget"), ("go", r"go-http|golang"), ("browser", r"mozilla|chrome|safari"),
            ("mcp_client", r"mcp|claude|cursor|smithery|glama|openai|anthropic|langchain|agent"))


def family(name: str) -> str:
    s = name.lower()
    for fam, rx in FAMILIES:
        if re.search(rx, s):
            return fam
    if re.fullmatch(r"[0-9a-f:.]+", s):
        return "ip_only"
    return "other"


def find_summary(o):
    if isinstance(o, dict):
        if "real_contact_origins" in o or ("counts" in o and "events_total" in o):
            return o
        for v in o.values():
            r = find_summary(v)
            if r:
                return r
    elif isinstance(o, list):
        for v in o:
            r = find_summary(v)
            if r:
                return r
    return None


def main(path: str) -> int:
    d = json.load(open(path, encoding="utf-8"))
    s = find_summary(d) or {}
    c = s.get("counts") or {}
    print("::notice title=inbound counts::" + json.dumps({"events_in_buffer": s.get("events_total"),
          "total": c.get("total"), "last_24h": c.get("last_24h")}, separators=(",", ":")))
    real = s.get("real_contact_origins")
    if real is None:
        print("::notice title=inbound real contacts::origins not exposed by the live status (only counts)")
    else:
        fams = {}
        for r in real:
            f = family(str(r.get("name") or ""))
            fams[f] = fams.get(f, 0) + int(r.get("requests") or 0)
        print("::notice title=inbound real contacts::" + json.dumps({"distinct_callers": len(real),
              "requests_by_client_family": fams,
              "top_caller_share": round(max((int(r.get("requests") or 0) for r in real), default=0)
                                        / max(1, sum(int(r.get("requests") or 0) for r in real)), 3)},
              separators=(",", ":")))
    crawl = s.get("crawler_origins")
    if crawl is not None:
        named, other = {}, 0
        for r in crawl:
            n, k = str(r.get("name") or ""), int(r.get("requests") or 0)
            hit = next((b for b in BOTS if b.lower() in n.lower()), None)
            if hit:
                named[hit] = named.get(hit, 0) + k
            else:
                other += k
        top = dict(sorted(named.items(), key=lambda kv: -kv[1])[:15])
        print("::notice title=inbound crawlers::" + json.dumps({"distinct": len(crawl), "named": top,
              "unnamed_requests": other}, separators=(",", ":")))
    ap = d.get("autopilot") if isinstance(d.get("autopilot"), dict) else d
    ev = [e for e in (ap.get("inbound_traffic_events") or []) if isinstance(e, dict)]
    real_ev = [e for e in ev if e.get("category") == "real_contact"]
    def tally(rows, key):
        out = {}
        for e in rows:
            k = str(e.get(key) or "-")[:60]
            out[k] = out.get(k, 0) + 1
        return dict(sorted(out.items(), key=lambda kv: -kv[1])[:8])
    if real_ev:
        tools = {}
        for e in real_ev:
            t = e.get("tool_name") or e.get("mcp_tool") or (e.get("rpc_params") or {}).get("name") if isinstance(e.get("rpc_params"), dict) else e.get("tool_name") or e.get("mcp_tool")
            if t:
                tools[str(t)[:60]] = tools.get(str(t)[:60], 0) + 1
        days = {}
        for e in real_ev:
            dday = str(e.get("timestamp_utc") or "")[:10]
            days[dday] = days.get(dday, 0) + 1
        print("::notice title=real contact events::" + json.dumps({
            "events": len(real_ev), "by_reason": tally(real_ev, "reason"), "by_endpoint": tally(real_ev, "endpoint"),
            "by_rpc_method": tally(real_ev, "rpc_method"), "tools_called": tools, "by_day": days,
            "distinct_callers": len({str(e.get("ip_or_origin") or e.get("user_agent") or "") for e in real_ev}),
            "client_family": {f: sum(1 for e in real_ev if family(str(e.get("user_agent") or "")) == f) for f in
                              ("python", "node", "curl", "go", "browser", "mcp_client", "ip_only", "other")}},
            separators=(",", ":"))[:3900])
    if ev:
        print("::notice title=event keys::" + ",".join(sorted({k for e in ev[:200] for k in e})))
    msgs = ap.get("inbound_messages") or []
    stats = ap.get("inbound_agent_stats") or {}
    print("::notice title=inbound messages::" + json.dumps({"messages": len(msgs) if isinstance(msgs, list) else None,
          "agent_stats_keys": sorted(stats)[:20] if isinstance(stats, dict) else None}, separators=(",", ":")))
    keys = sorted(k for k in (d.get("autopilot") or {}) if "chat" in k or "a2a" in k)
    mon = (d.get("autopilot") or {}).get("agent_chat_monitor") or (d.get("latest_result") or {}).get("agent_chat_monitor")
    print("::notice title=agent chats::" + json.dumps({"thread_count": (mon or {}).get("thread_count") if isinstance(mon, dict) else None,
          "autopilot_chat_keys": keys}, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1]))
