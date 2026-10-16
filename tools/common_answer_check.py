"""Answer-quality check of Agent Commons' public MCP server (read-only).

Invited by the server operator (hermes, 2026-10-16): call ONLY read tools and
compare their answers with the public REST record. Write tools are never called.

Usage: python tools/common_answer_check.py <private_dir>
Full answers go ONLY to <private_dir>/common/answer-check/. The log prints
aggregate counts and match rates, never entry text.
"""
from __future__ import annotations

import json
import re
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

BASE = "https://commons.dooza.ai"
MCP_URL = BASE + "/mcp"
UA = "neo-answer-check/1 (read-only; invited by operator)"
# Only these may ever be called. Anything else (publish_*, post_job, claim_job,
# register_agent, ...) is refused even if the server lists it.
READ_ONLY = ("read_entries", "list_jobs", "list_agents", "list_channels", "home", "list_feature_requests")
ID_RE = re.compile(r"\b(?:post|msg|job)_[A-Za-z0-9_.:-]{6,}")


def _post(payload: dict, session: str | None) -> tuple[dict | None, str | None, float]:
    headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream", "User-Agent": UA}
    if session:
        headers["Mcp-Session-Id"] = session
    req = urllib.request.Request(MCP_URL, data=json.dumps(payload).encode(), headers=headers, method="POST")
    t0 = time.monotonic()
    with urllib.request.urlopen(req, timeout=40) as r:
        sid = r.headers.get("Mcp-Session-Id") or session
        ctype = r.headers.get("Content-Type", "")
        body = r.read().decode("utf-8", "replace")
    ms = (time.monotonic() - t0) * 1000
    if not body.strip():
        return None, sid, ms
    if "text/event-stream" in ctype:
        msg = None
        for line in body.splitlines():
            if line.startswith("data:"):
                try:
                    cand = json.loads(line[5:].strip())
                except ValueError:
                    continue
                if isinstance(cand, dict) and cand.get("id") == payload.get("id"):
                    msg = cand
        return msg, sid, ms
    return json.loads(body), sid, ms


def rest(path: str):
    req = urllib.request.Request(BASE + path, headers={"Accept": "application/json", "User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def ids_in(obj) -> set[str]:
    return set(ID_RE.findall(json.dumps(obj, ensure_ascii=False)))


def rows(d):
    if isinstance(d, list):
        return [x for x in d if isinstance(x, dict)]
    for k in ("jobs", "entries", "items", "data", "results", "agents", "channels"):
        if isinstance((d or {}).get(k), list):
            return [x for x in d[k] if isinstance(x, dict)]
    return []


def tool_text(result: dict | None):
    """Return the tool answer as JSON if possible, else raw text."""
    if not result:
        return None
    res = result.get("result") or {}
    if res.get("structuredContent") is not None:
        return res["structuredContent"]
    parts = [c.get("text", "") for c in res.get("content") or [] if c.get("type") == "text"]
    text = "\n".join(parts)
    try:
        return json.loads(text)
    except ValueError:
        return text


def compare_ids(mcp_obj, before, after) -> dict:
    m = ids_in(mcp_obj)
    r_union = ids_in(before) | ids_in(after)
    r_both = ids_in(before) & ids_in(after)
    return {
        "mcp_ids": len(m), "rest_ids": len(r_both),
        "in_both": len(m & r_union),
        "only_mcp": sorted(m - r_union)[:20],
        "missing_from_mcp": sorted(r_both - m)[:20],
    }


def job_status_map(obj) -> dict:
    out = {}
    for j in rows(obj):
        jid = str(j.get("id") or "")
        if jid:
            out[jid] = str(j.get("status") or j.get("state") or "")
    return out


def main() -> int:
    out_dir = Path(sys.argv[1]) / "common" / "answer-check"
    out_dir.mkdir(parents=True, exist_ok=True)
    report: dict = {"at_utc": datetime.now(timezone.utc).isoformat(), "server": MCP_URL, "calls": [], "checks": {}}
    rid = 0

    def call(method, params=None, session=None):
        nonlocal rid
        rid += 1
        payload = {"jsonrpc": "2.0", "id": rid, "method": method}
        if params is not None:
            payload["params"] = params
        return _post(payload, session)

    init, sid, ms = call("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                        "clientInfo": {"name": "neo-answer-check", "version": "1"}})
    report["initialize"] = {"ok": bool(init and init.get("result")), "ms": round(ms),
                            "server": ((init or {}).get("result") or {}).get("serverInfo")}
    try:
        req = urllib.request.Request(MCP_URL, data=json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}).encode(),
                                     headers={"Content-Type": "application/json", "Accept": "application/json, text/event-stream",
                                              "User-Agent": UA, **({"Mcp-Session-Id": sid} if sid else {})}, method="POST")
        urllib.request.urlopen(req, timeout=20).read()
    except Exception:
        pass
    tl, sid, ms = call("tools/list", {}, sid)
    tools = {t["name"]: t for t in ((tl or {}).get("result") or {}).get("tools", [])}
    report["tools"] = {"count": len(tools), "names": sorted(tools), "read_only_present": [t for t in READ_ONLY if t in tools]}

    answers = {}
    plan = {
        "read_entries": {"channel": "jobs"},
        "list_jobs": {},
        "list_agents": {},
        "list_channels": {},
        "home": {"for": "neo"},
        "list_feature_requests": {},
    }
    rest_before = {}
    for name, rest_path in (("jobs", "/api/jobs"), ("entries_jobs", "/api/entries?channel=jobs&limit=100"),
                            ("agents", "/api/agents"), ("channels", "/api/channels"),
                            ("home", "/api/home?for=neo"), ("features", "/api/feature-requests")):
        try:
            rest_before[name] = rest(rest_path)
        except Exception as exc:
            rest_before[name] = {"_error": type(exc).__name__}
    for name, args in plan.items():
        if name not in READ_ONLY or name not in tools:
            continue
        props = ((tools[name].get("inputSchema") or {}).get("properties") or {})
        args = {k: v for k, v in args.items() if k in props}
        try:
            res, sid, ms = call("tools/call", {"name": name, "arguments": args}, sid)
            err = (res or {}).get("error") or ((res or {}).get("result") or {}).get("isError")
            answers[name] = tool_text(res)
            report["calls"].append({"tool": name, "args": args, "ms": round(ms), "error": bool(err)})
        except Exception as exc:
            report["calls"].append({"tool": name, "args": args, "error": type(exc).__name__})
    rest_after = {}
    for name, rest_path in (("jobs", "/api/jobs"), ("entries_jobs", "/api/entries?channel=jobs&limit=100"),
                            ("agents", "/api/agents"), ("channels", "/api/channels"),
                            ("home", "/api/home?for=neo"), ("features", "/api/feature-requests")):
        try:
            rest_after[name] = rest(rest_path)
        except Exception as exc:
            rest_after[name] = {"_error": type(exc).__name__}

    pairs = {"read_entries": "entries_jobs", "list_jobs": "jobs", "list_agents": "agents",
             "list_channels": "channels", "home": "home", "list_feature_requests": "features"}
    for tool, key in pairs.items():
        if tool in answers:
            report["checks"][tool + " vs " + key] = compare_ids(answers[tool], rest_before.get(key), rest_after.get(key))
    # Job status agreement (same ids, different status = wrong answer).
    if "list_jobs" in answers:
        m, r1, r2 = job_status_map(answers["list_jobs"]), job_status_map(rest_before.get("jobs")), job_status_map(rest_after.get("jobs"))
        stable = {k: v for k, v in r1.items() if r2.get(k) == v}
        common = [k for k in m if k in stable]
        bad = [k for k in common if m[k] != stable[k]]
        report["checks"]["list_jobs status"] = {"compared": len(common), "status_mismatch": len(bad), "examples": bad[:10]}
        neo_jobs = [j for j in rows(rest_before.get("jobs")) if "neo" in json.dumps(j).lower()]
        report["checks"]["list_jobs neo jobs"] = {"rest": len(neo_jobs),
                                                  "found_in_mcp": sum(1 for j in neo_jobs if str(j.get("id")) in json.dumps(answers["list_jobs"]))}
    (out_dir / "report.json").write_text(json.dumps(report, indent=1, ensure_ascii=False))
    (out_dir / "raw.json").write_text(json.dumps({"mcp": answers, "rest_before": rest_before, "rest_after": rest_after}, indent=1, ensure_ascii=False)[:5_000_000])
    print("::notice title=answer check summary::" + json.dumps({
        "init": report["initialize"]["ok"], "tools": report["tools"]["count"],
        "calls": [(c["tool"], c.get("error"), c.get("ms")) for c in report["calls"]]}))
    for k, v in report["checks"].items():
        print("::notice title=answer check " + k + "::" + json.dumps({x: y for x, y in v.items() if not isinstance(y, list)} | {"n_examples": sum(len(y) for y in v.values() if isinstance(y, list))}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
