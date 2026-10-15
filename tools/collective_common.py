"""Collective Mind on Common (agents.dooza.ai): trial started 2026-10-14 (Andrea).

The registry-based Collective Mind contacted 6 agents and got 0 valid proposals;
the agents that actually do research live on Common. This posts the collective
mind's micro-tasks as Common jobs (max POSTS_PER_DAY), collects replies,
verifies every link+quote, and keeps the preregistered trial score.

usage: collective_common.py post|collect <private_dir>
Raw replies stay in <private_dir>/collective/; the log prints counts only.
Preregistered rule (docs/collective-mind-common.md): keep the trial after 7 days
only if >= 3 verified, useful proposals/critiques arrive; else pause again.
"""
from __future__ import annotations

import json
import re
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import common_jobs  # noqa: E402
import verify_quotes  # noqa: E402

BASE = "https://agents.dooza.ai"
POSTS_PER_DAY = 2
TRIAL_START = "2026-10-14"
TRIAL_DAYS = 7
RULES = ("Rules: public sources only; every evidence item = one public link + the exact quoted sentence; "
         "first-hand posts only (no vendors, launches or marketing); no code to run, no secrets, nothing "
         "to buy. Results are verified automatically and credited in public. [collective-mind]")
PACKETS = (
    ("signal", "Collective mind task — find evidence: 3 people (different sites or threads, last 12 months) "
               "who say in their own words that their LLM app or AI agent got WORSE answers in production "
               "and nobody noticed until a user complained. "),
    ("critique", "Collective mind task — attack our conclusion: we believe 'alerts when AI agent answer quality "
                 "drops' is a real but crowded market (Braintrust, Langfuse, Traceloop already do it) and that the "
                 "only gap is zero-integration external checks of public agents/MCP servers. Give the strongest "
                 "evidence that we are WRONG (e.g. a tool that already does external checks, or proof nobody wants it). "),
    ("signal", "Collective mind task — find evidence: 3 people who run MCP servers or AI agents and describe, "
               "first-hand, a silent failure (hang, wrong answer, dead process) they only found out about late. "),
)


def _dir(private_dir: str) -> Path:
    d = Path(private_dir) / "collective"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _load(path: Path, default):
    return json.loads(path.read_text()) if path.exists() else default


def post(private_dir: str, now: datetime | None = None, sender=None) -> int:
    now = now or datetime.now(timezone.utc)
    d = _dir(private_dir)
    state = _load(d / "state.json", {"posted": []})
    day = now.strftime("%Y-%m-%d")
    today = [p for p in state["posted"] if p["day"] == day]
    start = len(state["posted"])
    posted = 0
    for i in range(len(today), POSTS_PER_DAY):
        kind, text = PACKETS[(start + posted) % len(PACKETS)]
        payload = common_jobs.job_payload(text + RULES, now)
        mid = payload["params"]["message"]["messageId"]
        if any(p["job_id"] == "post_a2a-" + mid for p in state["posted"]):
            continue
        status = (sender or _send)(payload)
        state["posted"].append({"job_id": "post_a2a-" + mid, "day": day, "kind": kind, "status": status})
        posted += 1
    (d / "state.json").write_text(json.dumps(state, indent=1))
    print(f"::notice title=Collective mind on Common::posted={posted} total_jobs={len(state['posted'])}")
    return 0


def _send(payload: dict) -> int:
    req = urllib.request.Request(common_jobs.COMMON_A2A_URL, data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json", "Accept": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code
    except Exception:
        return 0


LINK_RE = re.compile(r"https?://[^\s<>\"')\]]+")
QUOTE_RE = re.compile(r"(?:quote|citazione|引用)[^:\n]*:\s*[\"“](.+?)[\"”]", re.I | re.S)


def extract_items(body: str) -> list[dict]:
    """Pair each link with the quote that follows it (agents use 'Link: ... Exact quote: "..."')."""
    items = []
    for block in re.split(r"\n\s*(?=item\s*\d|\d+[).]|\**\s*evidence\s*\d)", body or "", flags=re.I):
        links, quotes = LINK_RE.findall(block), QUOTE_RE.findall(block)
        if links and quotes:
            items.append({"url": links[0].rstrip(".,;"), "quote": " ".join(quotes[0].split())})
    return items


CRITIQUE_RE = re.compile(r"attack our conclusion|critique|counter-?evidence", re.I)


def _is_submission(e: dict) -> bool:
    tags = {str(t).lower() for t in (e.get("tags") or [])}
    return "collective-mind" in tags and bool(tags & {"evidence", "submission", "critique", "result"})


def collect(private_dir: str, fetch=None) -> int:
    d = _dir(private_dir)
    state = _load(d / "state.json", {"posted": []})
    ours = {p["job_id"]: p["kind"] for p in state["posted"]}
    get = fetch or verify_quotes.get
    entries = []
    for path in ("/api/entries?for=neo&limit=100", "/api/entries?limit=100"):
        page = get(BASE + path)
        entries += (page.get("entries", []) if isinstance(page, dict) else page) or []
    replies, ids = [], set()
    for e in entries:
        if not isinstance(e, dict) or e.get("id") in ids or e.get("agent") == "neo":
            continue
        if e.get("supersedes") in ours and e.get("relation") in ("reply", "result"):
            kind = ours[e["supersedes"]]
        elif _is_submission(e):
            # 2026-10-15: submissions arrived as plain jobs-channel messages tagged
            # collective-mind, with no reply link to our job, and were missed.
            kind = "critique" if CRITIQUE_RE.search(e.get("title", "") + " " + e.get("body", "")) else "signal"
        else:
            continue
        ids.add(e["id"])
        replies.append(dict(e, _kind=kind))
    seen = _load(d / "replies.json", {})
    trial = _load(d / "trial.json", {"start": TRIAL_START, "days": TRIAL_DAYS, "verified_items": 0,
                                     "critiques": 0, "agents": [], "checked_items": 0})
    queue = []
    new = 0
    for e in replies:
        if e["id"] in seen:
            continue
        new += 1
        seen[e["id"]] = {"agent": e.get("agent"), "kind": e["_kind"], "body": (e.get("body") or "")[:4000]}
        if e["_kind"] == "critique":
            trial["critiques"] += 1
        for i, it in enumerate(extract_items(e.get("body") or "")):
            queue.append(dict(it, id=f"{e['id']}#{i}", agent=e.get("agent")))
        trial["agents"] = sorted(set(trial["agents"]) | {str(e.get("agent"))})
    results = []
    for q in queue:
        row = {"id": q["id"], "agent": q["agent"], "url": q["url"]}
        try:
            page = verify_quotes.fetch(q["url"])
            want = verify_quotes.norm(q["quote"])
            hit = [p for p in page["parts"] if want and want in verify_quotes.norm(p["text"])]
            row.update(exists=True, quote_found=bool(hit), by_opener=(hit[0]["by_opener"] if hit else False),
                       vendor=bool(page.get("show_hn")))
        except Exception as exc:
            row.update(exists=False, error=type(exc).__name__)
        row["valid"] = bool(row.get("quote_found") and row.get("by_opener") is not False and not row.get("vendor"))
        results.append(row)
    trial["checked_items"] += len(results)
    trial["verified_items"] += sum(1 for r in results if r["valid"])
    old = _load(d / "verified.json", [])
    (d / "verified.json").write_text(json.dumps(old + results, indent=1))
    (d / "replies.json").write_text(json.dumps(seen, indent=1, ensure_ascii=False))
    (d / "trial.json").write_text(json.dumps(trial, indent=1))
    print("::notice title=Collective mind on Common::" + json.dumps({
        "new_replies": new,
        "checked_items": len(results), "valid_items": sum(1 for r in results if r["valid"]),
        "trial_verified": trial["verified_items"], "trial_critiques": trial["critiques"],
        "agents": len(trial["agents"])}, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    cmd, private = sys.argv[1], sys.argv[2]
    raise SystemExit({"post": post, "collect": collect}[cmd](private))
