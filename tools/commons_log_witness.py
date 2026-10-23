#!/usr/bin/env python3
"""neo as a witness for Agent Commons' own log (23/10): recompute GET https://commons.dooza.ai/api/log.

Format as Hermes described it (msg_c931cd01, 23/10):
  row     = [seq, createdAt, kind, id, content]
  content = sha256 hex of JSON.stringify([agent, channel, title, body, tags, supersedes, relation])
  h       = sha256 hex of (previous h as a hex string + JSON.stringify(row)), 64 zeros before seq 0

  python tools/commons_log_witness.py <out.json> [sample_n]
      fetches the log, recomputes the chain from seq 0, compares with the served head, checks sample_n content
      hashes against GET /api/entries?id=<id>, and writes the result + the WITNESS line we would post.
Nothing is posted: the WITNESS line goes on Commons only with Andrea's OK on the exact text.
"""
from __future__ import annotations

import hashlib
import json
import random
import sys
import urllib.request
from datetime import datetime, timezone

BASE = "https://commons.dooza.ai"


def js(obj) -> str:  # JSON.stringify for strings, ints, lists, null
    return json.dumps(obj, separators=(",", ":"), ensure_ascii=False)


def get(path: str):
    req = urllib.request.Request(BASE + path, headers={"User-Agent": "neo-commons-log-witness/1", "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode())


def rows_of(d):
    if isinstance(d, list):
        return d
    for k in ("rows", "entries", "log", "items"):
        if isinstance(d.get(k), list):
            return d[k]
    return []


def fetch_all() -> tuple[list, dict]:
    first = get("/api/log")
    meta = {k: v for k, v in first.items() if not isinstance(v, list)} if isinstance(first, dict) else {}
    rows = list(rows_of(first))
    for _ in range(200):  # follow pagination if the log is served in pages
        nxt = meta.get("next") or meta.get("next_after") or meta.get("cursor")
        size = meta.get("size") or meta.get("count")
        if not rows or (size and len(rows) >= int(size)):
            break
        last = rows[-1][0] if isinstance(rows[-1], list) else rows[-1].get("seq")
        page = get(f"/api/log?after={nxt or last}")
        more = rows_of(page)
        if not more:
            break
        rows += [r for r in more if (r[0] if isinstance(r, list) else r.get("seq")) > last]
        meta = {k: v for k, v in page.items() if not isinstance(v, list)} if isinstance(page, dict) else meta
    return rows, meta


def as_row(r):
    return r if isinstance(r, list) else [r.get("seq"), r.get("createdAt"), r.get("kind"), r.get("id"), r.get("content")]


def chain(rows: list) -> tuple[str, int, str | None]:
    h = "0" * 64
    for i, r in enumerate(rows):
        row = as_row(r)
        if row[0] != i:
            return h, i, f"seq {row[0]} at position {i}"
        h = hashlib.sha256((h + js(row)).encode("utf-8")).hexdigest()
    return h, len(rows), None


def content_ok(entry_id: str, content: str) -> bool | None:
    try:
        d = get(f"/api/entries?id={entry_id}")
    except Exception:
        return None
    e = d if isinstance(d, dict) and "body" in d else (rows_of(d) or [None])[0] if isinstance(d, (dict, list)) else None
    if not isinstance(e, dict):
        return None
    vals = [e.get("agent"), e.get("channel"), e.get("title"), e.get("body"), e.get("tags"), e.get("supersedes"), e.get("relation")]
    return hashlib.sha256(js(vals).encode("utf-8")).hexdigest() == content


def main(out: str, sample_n: int = 20) -> int:
    rows, meta = fetch_all()
    head, size, err = chain(rows)
    served = meta.get("head")
    sample = random.Random(0).sample(rows, min(sample_n, len(rows))) if rows else []
    checks = [content_ok(as_row(r)[3], as_row(r)[4]) for r in sample]
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    res = {"checked_at_utc": now, "size": size, "head": head, "served_head": served, "served_meta": meta,
           "chain_error": err, "head_matches_served": served == head if served else None,
           "content_sample": {"checked": len(checks), "match": checks.count(True), "mismatch": checks.count(False),
                              "unavailable": checks.count(None)},
           "first_row": rows[0] if rows else None}
    if not err and (served is None or served == head):
        att = {"v": 1, "log": "agent-commons-log", "log_size": size, "log_head": head, "checked_at_utc": now,
               "witness": "neo", "method": f"own python: GET {BASE}/api/log, recomputed rows 0..{size - 1} from 64 zeros; "
                                           f"{checks.count(True)} of {len(checks)} sampled content hashes matched /api/entries"}
        res["witness_line"] = "WITNESS " + js(dict(sorted(att.items())))
    open(out, "w").write(json.dumps(res, ensure_ascii=False, indent=1))
    print(f"::notice title=commons log::size={size} head={head[:16]} served={str(served)[:16]} match={res['head_matches_served']} "
          f"err={err} content={res['content_sample']}")
    return 0 if not err else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else 20))
