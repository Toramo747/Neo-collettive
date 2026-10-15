"""Monitor NEO's jobs on Common's public job board (agents.dooza.ai).

Usage: python tools/common_jobs_monitor.py <private_dir> [status_json]
Raw board data goes ONLY to <private_dir>/common/. The log prints aggregate
counts, never job text, URLs or agent identifiers.
"""
from __future__ import annotations

import json
import re
import sys
import urllib.request
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

BASE = "https://agents.dooza.ai"
ME = "neo"
POSTER_KEYS = ("agent", "postedBy", "posted_by", "poster", "author", "by", "from")


def fetch(path: str):
    req = urllib.request.Request(BASE + path, headers={"Accept": "application/json", "User-Agent": "NEO-monitor/1"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def rows(payload, key):
    if isinstance(payload, dict):
        val = payload.get(key)
        if isinstance(val, list):
            return [x for x in val if isinstance(x, dict)]
    return [x for x in payload if isinstance(x, dict)] if isinstance(payload, list) else []


def poster(job: dict) -> str:
    for k in POSTER_KEYS:
        v = job.get(k)
        if isinstance(v, dict):
            v = v.get("name") or v.get("slug") or v.get("id")
        if isinstance(v, str) and v:
            return v.lower()
    return ""


MENTION_RE = re.compile(r"(?<![\w-])@?neo(?![\w-])", re.I)


def addressed_to_me(entry: dict) -> bool:
    """Entries for neo that Common's ?for= filter misses (2026-10-15: a reply that
    named neo in the text and collective-mind submissions on the jobs channel)."""
    if not isinstance(entry, dict) or str(entry.get("agent") or "") == ME:
        return False
    tags = [str(t).lower() for t in (entry.get("tags") or [])]
    text = " ".join(str(entry.get(k) or "") for k in ("title", "body"))
    return "collective-mind" in tags or bool(MENTION_RE.search(text))


def merge_replies(direct: list[dict], recent: list[dict]) -> list[dict]:
    out, seen = [], set()
    for e in list(direct or []) + [x for x in recent or [] if addressed_to_me(x)]:
        key = e.get("id") if isinstance(e, dict) else None
        if key and key in seen:
            continue
        if key:
            seen.add(key)
        out.append(e)
    return out


def summarize(jobs: list[dict], replies: list[dict], prod: dict) -> dict:
    mine = [j for j in jobs if poster(j) == ME]
    status = Counter(str(j.get("status") or "unknown") for j in mine)
    with_result = sum(1 for j in mine if j.get("result") or j.get("resultId") or j.get("result_ids") or j.get("results"))
    return {
        "board_jobs_seen": len(jobs),
        "neo_jobs": len(mine),
        "neo_jobs_by_status": dict(status),
        "neo_jobs_with_result": with_result,
        "replies_for_neo": len(replies),
        "prod_posted_total": int(prod.get("posted_total") or 0),
        "prod_ok_total": int(prod.get("ok_total") or 0),
        "prod_error_total": int(prod.get("error_total") or 0),
        "prod_skipped_cap_total": int(prod.get("skipped_total") or 0),
    }


def main() -> int:
    out_dir = Path(sys.argv[1]) / "common"
    prod, tools = {}, {}
    if len(sys.argv) > 2 and Path(sys.argv[2]).exists():
        try:
            data = json.loads(Path(sys.argv[2]).read_text())
            ap = data.get("autopilot") or data
            prod = dict(ap.get("common_jobs") or {})
            tools = dict(ap.get("public_tool_usage") or {})
        except Exception:
            prod, tools = {}, {}
    errors = []
    try:
        jobs = rows(fetch("/api/jobs?status=all&limit=100"), "jobs")
    except Exception as exc:
        jobs, errors = [], errors + ["jobs:" + type(exc).__name__]
    try:
        replies = rows(fetch("/api/entries?for=" + ME + "&limit=100"), "entries")
    except Exception as exc:
        replies, errors = [], errors + ["entries:" + type(exc).__name__]
    try:
        replies = merge_replies(replies, rows(fetch("/api/entries?limit=100"), "entries"))
    except Exception as exc:
        errors.append("recent_entries:" + type(exc).__name__)
    summary = summarize(jobs, replies, prod)
    summary["errors"] = errors
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"board-{stamp}.json").write_text(json.dumps(
        {"captured_at_utc": stamp, "summary": summary, "neo_jobs": [j for j in jobs if poster(j) == ME],
         "replies_for_neo": replies, "prod_common_jobs": prod}, ensure_ascii=False, indent=1))
    hist = out_dir / "history.jsonl"
    with hist.open("a") as fh:
        fh.write(json.dumps({"captured_at_utc": stamp, **summary}) + "\n")
    print("::notice title=Common job board::" + json.dumps(summary, separators=(",", ":")))
    # Free public MCP verifier test: aggregate demand only (hashed origins are never printed).
    free = {name: {"calls": int(r.get("calls") or 0), "distinct_origins": int(r.get("distinct_origins") or 0),
                   "returning_origins": int(r.get("returning_origins") or 0), "by_category": r.get("by_category") or {}} for name, r in tools.items()}
    with (out_dir / "free_tools_history.jsonl").open("a") as fh:
        fh.write(json.dumps({"captured_at_utc": stamp, **free}) + "\n")
    print("::notice title=Free MCP verifier usage::" + json.dumps(free, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
