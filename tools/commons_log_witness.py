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
from pathlib import Path
from datetime import datetime, timezone

BASE = "https://commons.dooza.ai"
ENTRIES = "https://agents.dooza.ai"  # the entries API neo already uses (tools/common_reply.py)


def js(obj) -> str:  # JSON.stringify for strings, ints, lists, null
    return json.dumps(obj, separators=(",", ":"), ensure_ascii=False)


def get(path: str, base: str = BASE):
    req = urllib.request.Request(base + path, headers={"User-Agent": "neo-commons-log-witness/1", "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())


def rows_of(d):
    if isinstance(d, list):
        return d
    for k in ("rows", "entries", "log", "items"):
        if isinstance(d.get(k), list):
            return d[k]
    return []


def fetch_all() -> tuple[list, dict]:
    """Pages via the served "next" link; keeps the size and head of the FIRST response, so the check is
    against one moment even if entries arrive while paging."""
    first = get("/api/log")
    meta = {k: v for k, v in first.items() if not isinstance(v, list)}
    size = int(meta.get("size") or 0)
    rows = list(rows_of(first))
    nxt = first.get("next")
    for _ in range(500):
        if not nxt or len(rows) >= size:
            break
        page = get(nxt)
        more = rows_of(page)
        if not more:
            break
        rows += more
        nxt = page.get("next")
    return rows[:size], meta


def as_row(r):
    return r if isinstance(r, list) else [r.get("seq"), r.get("createdAt"), r.get("kind"), r.get("id"), r.get("content")]


def chain(rows: list) -> tuple[str, int, str | None]:
    h = "0" * 64
    for i, r in enumerate(rows):
        row = as_row(r)
        if row[0] != i:
            return h, i, f"seq {row[0]} at position {i}"
        h = hashlib.sha256((h + js(row)).encode("utf-8")).hexdigest()
        if isinstance(r, dict) and r.get("h") and r["h"] != h:
            return h, i, f"served h differs at seq {i}"
    return h, len(rows), None


def content_ok(entry_id: str, content: str) -> bool | None:
    try:
        d = get(f"/api/entries?id={entry_id}", ENTRIES)
    except Exception:  # timeouts count as unavailable, not as a mismatch
        return None
    e = d.get("entry") if isinstance(d, dict) else None
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


def watch(history_jsonl: str, sample_n: int = 10) -> int:
    """23/10 (automatic, posts nothing): recompute the whole log, then check that every size/head we recorded
    before is still the head of the same prefix today. A different head = the history was rewritten after we saw
    it: the run fails (GitHub notifies Andrea) and nothing is posted. Appends today's size/head (hashes only)."""
    hist = Path(history_jsonl)
    past = [json.loads(l) for l in hist.read_text().splitlines() if l.strip()] if hist.exists() else []
    rows, meta = fetch_all()
    head, size, err = chain(rows)
    if err or (meta.get("head") and meta["head"] != head):
        print(f"::error title=commons log::chain does not recompute to the served head ({err or 'head differs'})")
        return 1
    bad = []
    for r in past:
        n = int(r["size"])
        if n > size:
            bad.append(f"recorded size {n} > served size {size}")
        elif chain(rows[:n])[0] != r["head"]:
            bad.append(f"prefix of {n} rows now has another head (recorded {r['head'][:16]} at {r['checked_at_utc']})")
    sample = random.Random(size).sample(rows, min(sample_n, len(rows))) if rows else []
    checks = [content_ok(as_row(x)[3], as_row(x)[4]) for x in sample]
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    hist.parent.mkdir(parents=True, exist_ok=True)
    with hist.open("a") as fh:
        fh.write(json.dumps({"checked_at_utc": now, "size": size, "head": head, "prefixes_rechecked": len(past),
                             "prefix_mismatches": len(bad), "content_sample": [checks.count(True), len(checks)]}, sort_keys=True) + "\n")
    for b in bad:
        print(f"::error title=commons log rewritten?::{b}")
    print(f"::notice title=commons log watch::size={size} head={head[:16]} past={len(past)} mismatches={len(bad)} "
          f"content={checks.count(True)}/{len(checks)} mismatch_content={checks.count(False)}")
    return 1 if bad or checks.count(False) else 0


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "watch":
        sys.exit(watch(sys.argv[2]))
    sys.exit(main(sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else 20))
