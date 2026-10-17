"""Experience log for the Common drafting mind: every draft with Andrea's verdict.

The local model (tools/common_deep.py) drafts replies; Andrea approves, rewrites
or rejects them. Each judgement becomes one row in the PRIVATE archive,
``common/experience.jsonl``, so the model can later be trained on it (LoRA on
Kaggle) and measured against the current one before any adoption.

  posted <private_dir> <reply_json> [note]  -> a reply neo actually posted (Andrea-approved):
        rows for every draft written for that message ("approved" if the text
        is essentially the posted one, else "rewritten" with the posted text as
        the target), or one "gold_only" row when no draft existed.
  sweep  <private_dir> [hours]              -> drafts older than <hours> (default 48)
        with no posted reply become "not_used" (weak negative).
  reject <private_dir> <draft_file> <reason> -> every draft in that file becomes
        "rejected" with the reason (when Andrea or Claude discards a whole run).
  stats  <private_dir>                      -> counts per verdict (no text printed)

Rows never leave the private archive; logs print counts only.
"""
from __future__ import annotations

import difflib
import glob
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

LOG = "common/experience.jsonl"
APPROVED_SIMILARITY = 0.9


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _rows(private_dir: str) -> list[dict]:
    p = Path(private_dir) / LOG
    return [json.loads(l) for l in p.read_text().splitlines() if l.strip()] if p.exists() else []


def _append(private_dir: str, rows: list[dict]) -> None:
    p = Path(private_dir) / LOG
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def _key(r: dict) -> tuple:
    return (r.get("draft_file"), r.get("message_id"), r.get("draft_body"), r.get("verdict"))


def _drafts_for(private_dir: str, message_id: str) -> list[tuple[str, dict]]:
    out = []
    for f in sorted(glob.glob(str(Path(private_dir) / "common" / "drafts" / "2*.json"))):
        data = json.loads(Path(f).read_text())
        for d in data.get("drafts") or []:
            if message_id == d.get("id") or message_id in (d.get("covers") or []):
                out.append((Path(f).name, d))
    return out


def _source(private_dir: str, message_id: str) -> dict:
    for f in sorted(glob.glob(str(Path(private_dir) / "common" / "board-*.json")), reverse=True)[:40]:
        for r in json.loads(Path(f).read_text()).get("replies_for_neo") or []:
            if isinstance(r, dict) and r.get("id") == message_id:
                return {"agent": r.get("agent"), "body": r.get("body")}
    return {}


def _row(verdict, *, message_id, source, draft=None, draft_file=None, target=None, note=""):
    return {"at": _now(), "verdict": verdict, "message_id": message_id,
            "agent": source.get("agent") or (draft or {}).get("agent"),
            "source_body": source.get("body") or (draft or {}).get("source_body") or "",
            "draft_file": draft_file, "draft_body": (draft or {}).get("body"),
            "draft_issues": (draft or {}).get("issues") or [], "draft_should_reply": (draft or {}).get("should_reply"),
            "target_body": target, "note": note}


def posted(private_dir: str, reply_json: str, note: str = "") -> int:
    reply = json.loads(Path(reply_json).read_text())
    mid = str(reply.get("reply_to") or "")
    if not mid:
        print("::notice title=experience::not a reply; nothing to learn")
        return 0
    target = str(reply.get("body") or "")
    source = _source(private_dir, mid)
    existing = {_key(r) for r in _rows(private_dir)}
    rows = []
    for fname, d in _drafts_for(private_dir, mid):
        body = str(d.get("body") or "")
        sim = difflib.SequenceMatcher(None, body, target).ratio() if body else 0.0
        verdict = "approved" if sim >= APPROVED_SIMILARITY else "rewritten"
        rows.append(_row(verdict, message_id=mid, source=source, draft=d, draft_file=fname, target=target,
                         note=note or f"similarity {sim:.2f}"))
    if not rows:
        rows.append(_row("gold_only", message_id=mid, source=source, target=target, note=note))
    rows = [r for r in rows if _key(r) not in existing]
    _append(private_dir, rows)
    print(f"::notice title=experience::posted reply recorded rows={len(rows)}")
    return 0


def reject(private_dir: str, draft_file: str, reason: str) -> int:
    data = json.loads((Path(private_dir) / "common" / "drafts" / draft_file).read_text())
    existing = {_key(r) for r in _rows(private_dir)}
    done = {(r.get("draft_file"), r.get("message_id"), r.get("draft_body")) for r in _rows(private_dir)}
    rows = []
    for d in data.get("drafts") or []:
        if (draft_file, d.get("id"), d.get("body")) in done:
            continue  # already judged (e.g. rewritten into a posted reply)
        rows.append(_row("rejected", message_id=d.get("id"), source=_source(private_dir, d.get("id")),
                         draft=d, draft_file=draft_file, note=reason))
    rows = [r for r in rows if _key(r) not in existing]
    _append(private_dir, rows)
    print(f"::notice title=experience::rejected rows={len(rows)}")
    return 0


def sweep(private_dir: str, hours: str = "48") -> int:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=float(hours))
    judged = {(r.get("draft_file"), r.get("message_id"), r.get("draft_body")) for r in _rows(private_dir)}
    rows = []
    for f in sorted(glob.glob(str(Path(private_dir) / "common" / "drafts" / "2*.json"))):
        name = Path(f).name
        try:
            stamp = datetime.strptime(name[:16], "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        data = json.loads(Path(f).read_text())
        if stamp > cutoff or data.get("replay"):
            continue
        for d in data.get("drafts") or []:
            if (name, d.get("id"), d.get("body")) in judged:
                continue
            verdict = "skip_kept" if not d.get("should_reply") else "not_used"
            rows.append(_row(verdict, message_id=d.get("id"), source={}, draft=d, draft_file=name,
                             note=f"no posted reply within {hours}h"))
    _append(private_dir, rows)
    print(f"::notice title=experience::swept rows={len(rows)}")
    return 0


def stats(private_dir: str) -> int:
    counts: dict[str, int] = {}
    for r in _rows(private_dir):
        counts[r["verdict"]] = counts.get(r["verdict"], 0) + 1
    print("::notice title=experience stats::" + json.dumps(counts, sort_keys=True))
    return 0


if __name__ == "__main__":
    cmd, *args = sys.argv[1:]
    raise SystemExit({"posted": posted, "reject": reject, "sweep": sweep, "stats": stats}[cmd](*args))
