# SPDX-License-Identifier: BUSL-1.1
"""mcp-ledger: a dated, anchored ledger of the public tool contracts of MCP servers (29/10/2026, Andrea's ok).

Once a day neo reads the public handshake (initialize + tools/list, cursors followed, never a tool call, no
credentials) of every remote server in the official MCP registry that has not opted out, and records:

  * in this public repository, per server and day, only a digest of its tool contract and an outcome:
        data/mcp-ledger/days/<date>.json.gz   rows [server_key, contract_digest|"", outcome, tool_count]
        data/mcp-ledger/days/<date>.root.json  the day's Merkle root over those rows, counts, timing
        data/mcp-ledger/state.json.gz          per server: last digest, first_seen, change dates (30 days), gaps
    server_key = sha256("neo-mcp-ledger-v1" + "\\0" + canonical_url)[:32]: anyone who knows the URL recomputes it;
    nobody learns a URL from the ledger. No server name is ever printed or committed here.
  * in the private archive only, the full contract text, content-addressed by its digest, written once per
    distinct contract. It is returned only to a paying caller, for the URL that caller asks about (phase 2).

The daily root is covered by the existing receipt-log anchor (the anchor statement fixes the repository commit
on Bitcoin via OpenTimestamps and in Software Heritage), so "the contract of server S had digest D on day T"
is provable later with the row, its Merkle inclusion path and the anchor. A gap (unreachable, refused, timeout,
cron skipped) is recorded as a gap, never as a change. Granularity is one read per UTC day: the ledger proves
what the server answered at that read, not what it served between two reads.

Usage:
  python tools/mcp_ledger.py read  [--max N] [--shard i/n] [--state DIR] [--private DIR] [--concurrency 32]
  python tools/mcp_ledger.py prove <date> <server_key>      inclusion path of a row in the day's root
  python tools/mcp_ledger.py key   <url>                     the server_key of a URL
"""
from __future__ import annotations

import argparse
import asyncio
import gzip
import hashlib
import json
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

DOMAIN = b"neo-mcp-ledger-v1"
PUBLIC_DIR = Path("data/mcp-ledger")
PRIVATE_SUBDIR = Path("mcp-ledger/contracts")
USER_AGENT = "neo-mcp-ledger/0.1 (+https://neo-collettive.onrender.com/mcp-ledger; daily public-handshake read; opt-out: see page)"
OPT_OUT_WELL_KNOWN = "/.well-known/mcp-ledger-opt-out"
MAX_TOOL_PAGES = 10
MAX_TOOLS = 500
PER_SERVER_TIMEOUT = 25.0
VOLATILE_CHANGES_7D = 3
CHANGE_DATES_KEPT = 30
OUTCOMES = ("ok", "no_tools", "init_failed", "unreachable", "refused", "timeout", "opted_out", "invalid_url", "error")


# ----------------------------------------------------------------------------- canonical forms and digests

def canonical_url(url: str) -> str:
    """scheme and host lower-case, default port dropped, fragment dropped; path and query kept as given."""
    p = urlsplit(str(url).strip())
    host = (p.hostname or "").lower()
    try:
        port = p.port
    except ValueError:  # registry entries such as "https://host:{HAPI_PORT}/mcp": kept verbatim, read as invalid
        return str(url).strip().split("#", 1)[0]
    scheme = (p.scheme or "https").lower()
    if port and not ((scheme == "https" and port == 443) or (scheme == "http" and port == 80)):
        host = f"{host}:{port}"
    return urlunsplit((scheme, host, p.path or "/", p.query, ""))


def server_key(url: str) -> str:
    return hashlib.sha256(DOMAIN + b"\x00" + canonical_url(url).encode("utf-8")).hexdigest()[:32]


def canonical_json(obj: Any) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def contract_of(tools: list[dict]) -> list[dict]:
    """The contract is the list of tools, each reduced to name, description, inputSchema and annotations, sorted by name."""
    out = []
    for t in tools:
        if not isinstance(t, dict) or not t.get("name"):
            continue
        out.append({
            "name": str(t.get("name")),
            "description": t.get("description") if isinstance(t.get("description"), str) else None,
            "inputSchema": t.get("inputSchema"),
            "annotations": t.get("annotations") if isinstance(t.get("annotations"), dict) else None,
        })
    out.sort(key=lambda x: x["name"])
    return out


def contract_digest(contract: list[dict]) -> str:
    return hashlib.sha256(DOMAIN + b"\x01" + canonical_json(contract)).hexdigest()


# ----------------------------------------------------------------------------- Merkle tree (RFC 6962 style)

def leaf_bytes(row: list) -> bytes:
    """row = [server_key, contract_digest or "", outcome, tool_count]"""
    return canonical_json(row)


def _leaf_hash(data: bytes) -> str:
    return hashlib.sha256(b"\x00" + data).hexdigest()


def _node_hash(left: str, right: str) -> str:
    return hashlib.sha256(b"\x01" + bytes.fromhex(left) + bytes.fromhex(right)).hexdigest()


def merkle_root(rows: list[list]) -> str:
    """Rows must already be sorted by server_key. Empty set has root sha256("")."""
    if not rows:
        return hashlib.sha256(b"").hexdigest()
    level = [_leaf_hash(leaf_bytes(r)) for r in rows]
    while len(level) > 1:
        if len(level) % 2 == 1:
            level.append(level[-1])
        level = [_node_hash(level[i], level[i + 1]) for i in range(0, len(level), 2)]
    return level[0]


def merkle_path(rows: list[list], index: int) -> list[dict]:
    """Siblings from the leaf up: [{"side": "L"|"R", "hash": ...}]. Verify with verify_path()."""
    level = [_leaf_hash(leaf_bytes(r)) for r in rows]
    path = []
    i = index
    while len(level) > 1:
        if len(level) % 2 == 1:
            level.append(level[-1])
        sib = i ^ 1
        path.append({"side": "L" if sib < i else "R", "hash": level[sib]})
        level = [_node_hash(level[j], level[j + 1]) for j in range(0, len(level), 2)]
        i //= 2
    return path


def verify_path(row: list, path: list[dict], root: str) -> bool:
    h = _leaf_hash(leaf_bytes(row))
    for step in path:
        h = _node_hash(step["hash"], h) if step["side"] == "L" else _node_hash(h, step["hash"])
    return h == root


# ----------------------------------------------------------------------------- reading one server

async def read_contract(url: str, client, pacer) -> dict:
    """Public handshake only. Returns {"outcome", "tools", "latency_ms", "pages"}; tools is the raw list or None."""
    import mcp_endpoint_verifier as ev  # SSRF guard, IP pinning, SSE parsing, pacing: reused as-is

    started = time.perf_counter()
    init = {"jsonrpc": "2.0", "id": "ledger-init", "method": "initialize",
            "params": {"protocolVersion": "2025-11-25", "capabilities": {},
                       "clientInfo": {"name": "neo-mcp-ledger", "version": "0.1"}}}
    try:
        r = await ev._bounded_request(client, "POST", url, json_body=init, user_agent=USER_AGENT, request_pacer=pacer)
    except ev.VerificationError as exc:
        code = str(exc.code or "")
        detail = str(exc.detail or "")
        if "Timeout" in detail or "timeout" in code:
            return {"outcome": "timeout", "tools": None, "error": f"{code}:{detail}"}
        return {"outcome": "unreachable", "tools": None, "error": f"{code}:{detail}"}
    except Exception as exc:  # noqa: BLE001
        return {"outcome": "unreachable", "tools": None, "error": type(exc).__name__}
    status = int(r.get("status") or 0)
    if status in (401, 403, 429):
        return {"outcome": "refused", "tools": None, "error": f"http_{status}"}
    payload = ev._json_payload(r)
    result = payload.get("result") if isinstance(payload.get("result"), dict) else {}
    if not (200 <= status < 300 and result):
        return {"outcome": "init_failed", "tools": None, "error": f"http_{status}"}
    headers = {}
    if (r.get("headers") or {}).get("mcp-session-id"):
        headers["Mcp-Session-Id"] = str(r["headers"]["mcp-session-id"])
    if result.get("protocolVersion"):
        headers["MCP-Protocol-Version"] = str(result["protocolVersion"])
    try:
        await ev._bounded_request(client, "POST", url, json_body={"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}},
                                  headers=headers, user_agent=USER_AGENT, request_pacer=pacer)
    except Exception:  # noqa: BLE001
        pass  # stateless servers may ignore the notification
    tools: list[dict] = []
    cursor = None
    pages = 0
    seen_cursors: set[str] = set()
    while pages < MAX_TOOL_PAGES:
        params = {"cursor": cursor} if cursor else {}
        body = {"jsonrpc": "2.0", "id": f"ledger-tools-{pages}", "method": "tools/list", "params": params}
        try:
            lr = await ev._bounded_request(client, "POST", url, json_body=body, headers=headers, user_agent=USER_AGENT, request_pacer=pacer)
        except Exception as exc:  # noqa: BLE001
            return {"outcome": "error", "tools": None, "error": f"tools_list:{getattr(exc, 'code', type(exc).__name__)}"}
        pages += 1
        lp = ev._json_payload(lr)
        res = lp.get("result") if isinstance(lp.get("result"), dict) else {}
        if not (200 <= int(lr.get("status") or 0) < 300 and isinstance(res.get("tools"), list)):
            return {"outcome": "error", "tools": None, "error": f"tools_list_http_{lr.get('status')}"}
        tools.extend(t for t in res["tools"] if isinstance(t, dict))
        if len(tools) > MAX_TOOLS:
            tools = tools[:MAX_TOOLS]
            break
        nxt = res.get("nextCursor")
        if not nxt or not isinstance(nxt, str) or nxt in seen_cursors:
            break
        seen_cursors.add(nxt)
        cursor = nxt
    latency = round((time.perf_counter() - started) * 1000)
    if not tools:
        return {"outcome": "no_tools", "tools": [], "latency_ms": latency, "pages": pages}
    return {"outcome": "ok", "tools": tools, "latency_ms": latency, "pages": pages}


async def well_known_opt_out(host: str, client) -> bool:
    """A server operator refuses the daily read by serving a 2xx at /.well-known/mcp-ledger-opt-out whose body
    contains the words "mcp-ledger-opt-out" (a bare 2xx is not enough: many hosts answer 200 to any path)."""
    try:
        r = await client.get(f"https://{host}{OPT_OUT_WELL_KNOWN}", timeout=6, headers={"User-Agent": USER_AGENT}, follow_redirects=False)
        return 200 <= r.status_code < 300 and "mcp-ledger-opt-out" in r.text[:4096].lower()
    except Exception:  # noqa: BLE001
        return False


# ----------------------------------------------------------------------------- state and day files

def _load_gz_json(path: Path, default):
    if not path.exists():
        return default
    with gzip.open(path, "rt", encoding="utf-8") as f:
        return json.load(f)


def _save_gz_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with gzip.open(tmp, "wt", encoding="utf-8", compresslevel=9) as f:
        json.dump(obj, f, separators=(",", ":"), ensure_ascii=False)
    tmp.replace(path)


def update_state(state: dict, key: str, day: str, outcome: str, digest: str | None) -> dict:
    """Per-server record; keeps only what the paid queries need: digests over time, never names."""
    rec = state.get(key) or {"first_seen": None, "last": None, "last_seen": None, "changes": [], "observed": 0, "gaps": 0, "history": []}
    rec["observed"] += 1
    if outcome == "ok" and digest:
        if rec["last"] is None:
            rec["first_seen"] = day
        elif rec["last"] != digest:
            rec["changes"] = (rec["changes"] + [day])[-CHANGE_DATES_KEPT:]
        if not rec["history"] or rec["history"][-1][1] != digest:
            rec["history"] = (rec["history"] + [[day, digest]])[-CHANGE_DATES_KEPT:]
        rec["last"] = digest
        rec["last_seen"] = day
    else:
        rec["gaps"] += 1
    rec["last_outcome"] = outcome
    state[key] = rec
    return rec


def is_volatile(rec: dict, day: str) -> bool:
    cutoff = (datetime.fromisoformat(day) - timedelta(days=7)).strftime("%Y-%m-%d")
    return sum(1 for d in rec.get("changes", []) if d >= cutoff) >= VOLATILE_CHANGES_7D


def purge_opted_out(state: dict, keys: list[str], private_dir: Path | None) -> int:
    """An operator who opted out gets the archived texts of its contracts deleted (digests already anchored stay).
    A text is kept when another, still-read server has the same contract digest (content-addressed archive)."""
    if not private_dir or not keys:
        return 0
    keys_set = set(keys)
    in_use: set[str] = set()
    for k, rec in state.items():
        if k.startswith("_") or k in keys_set:
            continue
        in_use.update(h[1] for h in rec.get("history") or [])
        if rec.get("last"):
            in_use.add(rec["last"])
    removed = 0
    for k in keys:
        rec = state.get(k) or {}
        digests = {h[1] for h in rec.get("history") or []} | ({rec["last"]} if rec.get("last") else set())
        for d in digests - in_use:
            f = private_dir / PRIVATE_SUBDIR / d[:2] / f"{d}.json.gz"
            if f.exists():
                f.unlink()
                removed += 1
        rec["history"], rec["last"] = [], None
        rec["opted_out"] = True
        state[k] = rec
    return removed


# ----------------------------------------------------------------------------- the daily read

async def run_read(args) -> int:
    import httpx

    import mcp_endpoint_verifier as ev
    import registry_health as rh

    public = Path(args.state)
    days_dir = public / "days"
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if (days_dir / f"{day}.root.json").exists() and not args.force:
        print(f"::notice title=mcp-ledger::{day} already read, nothing done")
        return 0
    t0 = time.perf_counter()
    async with httpx.AsyncClient(timeout=30, trust_env=False) as c:
        reg = await rh.fetch_complete_registry(c)
    opt = rh.read_opt_out()
    remote = [s for s in reg["servers"] if s["access_class"] == "remote"]
    opted = [s for s in remote if rh.is_opted_out(s, opt)]
    remote = [s for s in remote if not rh.is_opted_out(s, opt)]
    remote.sort(key=lambda s: server_key(s["remotes"][0]["url"]))
    if args.shard:
        i, n = (int(x) for x in args.shard.split("/"))
        remote = [s for j, s in enumerate(remote) if j % n == i]
    if args.max:
        remote = remote[: int(args.max)]
    state = _load_gz_json(public / "state.json.gz", {})
    wk_cache = state.get("_well_known", {})  # host -> [date_checked, opted_out]
    pacer = ev.RequestPacer(max_concurrency=int(args.concurrency), per_host=2, min_host_interval=0.5)
    rows: list[list] = []
    new_contracts: dict[str, list] = {}
    outcomes = {o: 0 for o in OUTCOMES}
    latencies: list[int] = []
    changed = volatile = 0
    wk_checked = 0
    wk_sem = asyncio.Semaphore(int(args.concurrency))
    wk_locks: dict[str, asyncio.Lock] = {}

    async with httpx.AsyncClient(timeout=httpx.Timeout(12.0, connect=6.0), trust_env=False, follow_redirects=False) as client:
        async def one(s: dict) -> tuple[str, dict]:
            url = canonical_url(s["remotes"][0]["url"])
            key = server_key(url)
            host = (urlsplit(url).hostname or "").lower()
            if not host or not url.startswith("https://") or any(ch in url for ch in "{}<> "):
                return key, {"outcome": "invalid_url", "tools": None}
            lock = wk_locks.setdefault(host, asyncio.Lock())
            async with lock:  # one well-known check per host per day, however many servers share the host
                cached = wk_cache.get(host)
                if not cached or (datetime.fromisoformat(day) - datetime.fromisoformat(cached[0])).days >= 7:
                    async with wk_sem:
                        oo = await well_known_opt_out(host, client)
                    wk_cache[host] = [day, oo]
            if wk_cache[host][1]:
                return key, {"outcome": "opted_out", "tools": None}
            try:
                return key, await asyncio.wait_for(read_contract(url, client, pacer), timeout=PER_SERVER_TIMEOUT)
            except asyncio.TimeoutError:
                return key, {"outcome": "timeout", "tools": None}
            except Exception as exc:  # noqa: BLE001
                return key, {"outcome": "error", "tools": None, "error": type(exc).__name__}

        results = await asyncio.gather(*[one(s) for s in remote])

    for key, r in results:
        outcome = r["outcome"]
        outcomes[outcome] = outcomes.get(outcome, 0) + 1
        digest = None
        n_tools = 0
        if outcome == "ok":
            contract = contract_of(r["tools"])
            digest = contract_digest(contract)
            n_tools = len(contract)
            new_contracts[digest] = contract
            latencies.append(int(r.get("latency_ms") or 0))
        before = (state.get(key) or {}).get("last")
        rec = update_state(state, key, day, outcome, digest)
        if digest and before and before != digest:
            changed += 1
        if is_volatile(rec, day):
            volatile += 1
        rows.append([key, digest or "", outcome, n_tools])
    rows.sort(key=lambda x: x[0])
    root = merkle_root(rows)
    state["_well_known"] = wk_cache
    wk_checked = sum(1 for v in wk_cache.values() if v[0] == day)

    # private archive: the full contract text, once per distinct digest, never in the public repo
    archived = 0
    if args.private:
        priv = Path(args.private) / PRIVATE_SUBDIR
        for d, contract in new_contracts.items():
            p = priv / d[:2] / f"{d}.json.gz"
            if not p.exists():
                _save_gz_json(p, {"v": 1, "digest": d, "first_archived": day, "contract": contract})
                archived += 1
    opted_keys = [server_key(s["remotes"][0]["url"]) for s in opted] + [k for k, r in results if r["outcome"] == "opted_out"]
    purged = purge_opted_out(state, [k for k in opted_keys if k in state], Path(args.private) if args.private else None)

    _save_gz_json(days_dir / f"{day}.json.gz", {"v": 1, "date": day, "rows": rows,
                                                 "row_format": "[server_key, contract_digest|'', outcome, tool_count]",
                                                 "leaf": "sha256(0x00 || canonical_json(row))", "node": "sha256(0x01 || left || right)",
                                                 "odd": "last node duplicated", "root": root})
    lat = sorted(latencies)
    summary = {
        "v": 1, "date": day, "root": root, "rows": len(rows), "registry_remote": len(remote) + len(opted),
        "opted_out_list": len(opted), "read_attempted": len(remote), "shard": args.shard or None, "max": int(args.max or 0) or None,
        "outcomes": {k: v for k, v in outcomes.items() if v}, "changed_vs_last_digest": changed, "volatile_servers": volatile,
        "distinct_contracts_new_in_archive": archived if args.private else None, "opt_out_texts_purged": purged,
        "latency_ms": {"p50": lat[len(lat) // 2] if lat else None, "p90": lat[int(len(lat) * 0.9)] if lat else None, "max": lat[-1] if lat else None},
        "well_known_checked_today": wk_checked, "duration_s": round(time.perf_counter() - t0, 1),
        "granularity": "one public-handshake read per UTC day", "names_published": False,
    }
    (days_dir / f"{day}.root.json").write_text(json.dumps(summary, indent=1) + "\n")
    _save_gz_json(public / "state.json.gz", state)
    print(f"::notice title=mcp-ledger {day}::{json.dumps(summary, separators=(',', ':'))}")
    return 0


# ----------------------------------------------------------------------------- proofs

def prove(date: str, key: str, state_dir: str) -> int:
    day_file = Path(state_dir) / "days" / f"{date}.json.gz"
    if not day_file.exists():
        print(json.dumps({"ok": False, "error": "no_such_day"}))
        return 1
    d = _load_gz_json(day_file, {})
    rows = d.get("rows") or []
    idx = next((i for i, r in enumerate(rows) if r[0] == key), None)
    if idx is None:
        print(json.dumps({"ok": False, "error": "server_not_in_day", "date": date}))
        return 1
    path = merkle_path(rows, idx)
    out = {"ok": True, "date": date, "row": rows[idx], "index": idx, "path": path, "root": d["root"],
           "verified": verify_path(rows[idx], path, d["root"]),
           "anchor": f"docs/receipts-log/anchors/{date}.json (+.ots): statement fixing the repository commit that holds this day file"}
    print(json.dumps(out, indent=1))
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="mcp-ledger")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("read")
    r.add_argument("--max", type=int, default=0, help="read at most N servers (measurement week)")
    r.add_argument("--shard", default="", help="i/n: read only servers with position % n == i")
    r.add_argument("--state", default=str(PUBLIC_DIR), help="public data directory")
    r.add_argument("--private", default="", help="private archive checkout (contract texts); omit to keep digests only")
    r.add_argument("--concurrency", type=int, default=32)
    r.add_argument("--force", action="store_true")
    p = sub.add_parser("prove")
    p.add_argument("date")
    p.add_argument("server_key")
    p.add_argument("--state", default=str(PUBLIC_DIR))
    k = sub.add_parser("key")
    k.add_argument("url")
    args = ap.parse_args(argv)
    if args.cmd == "read":
        return asyncio.run(run_read(args))
    if args.cmd == "prove":
        return prove(args.date, args.server_key, args.state)
    if args.cmd == "key":
        print(server_key(args.url))
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
