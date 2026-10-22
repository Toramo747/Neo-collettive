#!/usr/bin/env python3
"""Actions for the fact-card mind (trial, 22/10): the code acts, the model reports.

When a message brings a checkable claim (a public link + an exact sentence), the code runs
verify_quote itself (same code as production, run locally: no receipt, no effect on the
production counters) and adds the outcome as a fact card the mind can say to the sender.

  python tools/fact_actions.py enrich <replay.json> <out.json>
  python tools/fact_actions.py verification-set <private_dir> <out.json>   messages to neo that bring a link + sentence
"""
from __future__ import annotations

import asyncio
import glob
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

URL_RE = re.compile(r"https?://[^\s<>\"'\)\]]+")
QUOTE_RE = re.compile(r"[\"“]([^\"”]{25,600})[\"”]")


def submission(body: str) -> tuple[str, str] | None:
    """A link and an exact sentence, as our checkable-claim rule asks. Deterministic, no model."""
    urls = [u.rstrip(".,;:") for u in URL_RE.findall(body or "")]
    urls = [u for u in urls if "neo-collettive.onrender.com" not in u and "commons.dooza.ai" not in u]
    m = re.search(r"exact (?:sentence|quote)[^:\n]*:\s*[\"“]([^\"”]{10,600})[\"”]", body or "", re.I)
    quote = m.group(1) if m else None
    if not quote:
        qs = [q for q in QUOTE_RE.findall(body or "") if len(q.split()) >= 6 and "\n" not in q]
        quote = max(qs, key=len) if qs else None
    if not urls or not quote:
        return None
    lm = re.search(r"link:\s*(https?://\S+)", body or "", re.I)
    return ((lm.group(1).rstrip(".,;:") if lm else urls[0]), quote.strip())


def card_text(url: str, r: dict) -> str:
    o = r.get("outcome")
    if not r.get("ok", True) and r.get("error"):
        return f"We could not check that sentence: verify_quote refused it ({r.get('error')}), before fetching {url}."
    if o == "verbatim":
        return f"We checked your sentence with verify_quote: it is verbatim on the page at {url}."
    if o == "paraphrase":
        return (f"We checked your sentence with verify_quote: it is not verbatim on the page at {url}; "
                f"{round(100 * float(r.get('four_word_overlap') or 0))}% of its four-word runs are there, so the outcome is paraphrase.")
    if o == "stitched":
        return (f"We checked your sentence with verify_quote: every piece is on the page at {url}, but not in this order or "
                "not close together, so the outcome is stitched: the joined quote may say something the page does not.")
    if o == "not_found":
        return (f"We checked your sentence with verify_quote: the words are not on the page at {url} (not_found). "
                "That means the words are not there, not that the claim is false.")
    if o == "unreachable":
        why = r.get("reason") or r.get("error") or "no reason given"
        return f"We could not check your sentence: verify_quote could not fetch {url} ({why}). That is not a verdict on the sentence."
    return f"verify_quote returned {o} for {url}."


# --- routing (22/10): decisions go to Andrea, actions to tools, the rest to fact cards ---
DECISION_RE = re.compile(r"\b(register\w*|registration|join\w*|partner\w*|commission\w*|budget|price|pay (you|neo)|payment|paid (task|work|job)|"
                         r"wallet|invoice|bounty|sign\w* up|accept\w*|contribute|collaborat\w*|publish\w* (it|later|when))\b", re.I)
ASKS_RE = re.compile(r"\b(you|your|neo)\b", re.I)  # the commitment is asked of neo, not of a tool ("does it accept")
ANCHOR_RE = re.compile(r"\b(anchor\w*|ots|opentimestamps|timestamp(ed)?|receipt log|receipts?/log|log head|head hash|"
                       r"software heritage|swh:|hash chain|bitcoin block)\b", re.I)


def route(body: str) -> str:
    if submission(body):
        return "verify"
    if ANCHOR_RE.search(body or "") and "?" in (body or ""):  # 22/10: only when the message asks something
        return "anchor"
    # a decision is asked when a sentence both asks neo something and names a commitment (22/10)
    for sent in re.split(r"(?<=[.!?])\s+|\n+", body or ""):
        if DECISION_RE.search(sent) and ASKS_RE.search(sent):
            return "andrea"
    return "facts"


def _git(*a: str) -> str:
    return subprocess.run(["git", "-C", str(ROOT), *a], capture_output=True, text=True).stdout.strip()


def _swh_has(blob: str) -> bool:
    import urllib.request
    try:
        r = urllib.request.urlopen(urllib.request.Request(
            f"https://archive.softwareheritage.org/api/1/content/sha1_git:{blob}/", headers={"User-Agent": "neo"}), timeout=30)
        return r.status == 200
    except Exception:
        return False


def anchor_cards() -> list[dict]:
    """Where the latest anchor's files are, in an archive we do not control, and whether the proof is on Bitcoin."""
    d = ROOT / "docs" / "receipts-log" / "anchors"
    stmts = sorted(d.glob("20*.json"))
    if not stmts:
        return []
    st = stmts[-1]
    rel = lambda p: str(p.relative_to(ROOT))
    cards = []
    stmt = json.loads(st.read_text())
    cards.append(f"The latest anchor, {st.name}, fixes {stmt.get('log_count')} receipts with log head {stmt.get('log_head')} "
                 f"and repository commit {stmt.get('repo_commit')}.")
    main = _git("rev-parse", "HEAD")
    if stmt.get("repo_commit") and not _git("merge-base", "--is-ancestor", stmt["repo_commit"], main) and \
            subprocess.run(["git", "-C", str(ROOT), "merge-base", "--is-ancestor", stmt["repo_commit"], main]).returncode != 0:
        cards.append(f"The anchored commit {stmt['repo_commit'][:8]} is not on main.")
    def swh_link(path: str, label: str):
        blob = _git("rev-parse", f"HEAD:{path}")
        if blob and _swh_has(blob):
            return f"{label} in Software Heritage, an independent archive: https://archive.softwareheritage.org/swh:1:cnt:{blob}"
        for c in _git("log", "--format=%H", "-n", "20", "--", path).split():
            b = _git("rev-parse", f"{c}:{path}")
            if b and b != blob and _swh_has(b):
                return (f"{label} in Software Heritage, as archived in an earlier version: "
                        f"https://archive.softwareheritage.org/swh:1:cnt:{b}")
        return None
    for path, label in ((rel(st), "The anchor statement is"), (rel(st) + ".ots", "Its OpenTimestamps proof is"),
                        ("docs/receipts-log/log.jsonl", "The receipt log is"), ("tools/receipt_log_anchor.py", "The checking tool is")):
        t = swh_link(path, label)
        if t:
            cards.append(t)
    cards.append("The live receipt log is at https://neo-collettive.onrender.com/receipts/log.")
    try:
        info = subprocess.run(["ots", "info", str(st) + ".ots"], capture_output=True, text=True, timeout=60).stdout
        m = re.search(r"BitcoinBlockHeaderAttestation\((\d+)\)", info)
        cards.append(f"The OpenTimestamps proof is attested in Bitcoin block {m.group(1)}." if m else
                     "The OpenTimestamps proof is still pending: the Bitcoin attestation is not in it yet.")
    except Exception:
        pass
    return [{"text": t, "source": "tool:anchors(live)"} for t in cards]


def run_verify(url: str, quote: str) -> dict:
    import quote_verifier as qv  # same code as production
    try:
        return asyncio.run(qv.verify_quote(url, quote, caller="neo-fact-mind-replay"))
    except Exception as e:
        return {"ok": False, "error": type(e).__name__}


def enrich(in_json: str, out_json: str) -> int:
    items = json.loads(Path(in_json).read_text())
    n = 0
    anchors = None
    for it in items:
        it["route"] = route(it.get("body") or "")
        nxt = max([int(c["id"][1:]) for c in it["cards"]] + [0]) + 1
        if it["route"] == "verify":
            sub = submission(it.get("body") or "")
            r = run_verify(*sub)
            it["cards"] = [{"id": f"F{nxt}", "text": card_text(sub[0], r), "source": "tool:verify_quote(live)"}] + it["cards"]
            it["action"] = {"tool": "verify_quote", "url": sub[0], "outcome": r.get("outcome") or r.get("error")}
            n += 1
        elif it["route"] == "anchor":
            anchors = anchors if anchors is not None else anchor_cards()
            it["cards"] = [{"id": f"F{nxt + i}", **c} for i, c in enumerate(anchors)] + it["cards"]
            it["action"] = {"tool": "anchors", "cards": len(anchors)}
    Path(out_json).write_text(json.dumps(items, ensure_ascii=False, indent=1))
    routes: dict[str, int] = {}
    for it in items:
        routes[it["route"]] = routes.get(it["route"], 0) + 1
    print(f"::notice title=fact actions::routes={json.dumps(routes, sort_keys=True)}")
    outs: dict[str, int] = {}
    for it in items:
        if it.get("action"):
            outs[str(it["action"]["outcome"])] = outs.get(str(it["action"]["outcome"]), 0) + 1
    print(f"::notice title=fact actions::messages={len(items)} with_submission={n} outcomes={json.dumps(outs, sort_keys=True)}")
    return 0


def verification_set(private_dir: str, out_json: str) -> int:
    from fact_cards import all_cards, select
    msgs = {}
    for f in sorted(glob.glob(str(Path(private_dir) / "common" / "board-*.json"))):
        d = json.loads(Path(f).read_text())
        for r in d.get("replies_for_neo") or []:
            if isinstance(r, dict) and r.get("id") and r.get("agent") not in ("neo", "anonymous"):
                msgs[r["id"]] = r
    head = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    cards = all_cards(head)
    items = []
    for r in sorted(msgs.values(), key=lambda x: x.get("createdAt") or 0):
        body = str(r.get("body") or "")[:1500]
        if submission(body):
            items.append({"message_id": r["id"], "agent": r.get("agent"), "body": body, "target": None,
                          "reply_file": f"verification-{r['id']}", "known_at": head, "cards": select(cards, body)})
    Path(out_json).write_text(json.dumps(items, ensure_ascii=False, indent=1))
    print(f"::notice title=fact actions::verification messages={len(items)}")
    return 0


def recent_set(private_dir: str, out_json: str, hours: str = "72") -> int:
    """Every message addressed to neo in the last hours (all routes), for a replay of the router."""
    from fact_cards import all_cards, select
    import time
    boards = sorted(glob.glob(str(Path(private_dir) / "common" / "board-*.json")))
    rows = [r for r in json.loads(Path(boards[-1]).read_text()).get("replies_for_neo") or []
            if isinstance(r, dict) and r.get("agent") not in ("neo", "anonymous")
            and time.time() * 1000 - float(r.get("createdAt") or 0) < float(hours) * 3600 * 1000]
    cards = all_cards(_git("rev-parse", "HEAD"))
    items = [{"message_id": r["id"], "agent": r.get("agent"), "body": str(r.get("body") or "")[:1500], "target": None,
              "reply_file": f"recent-{r['id']}", "known_at": "HEAD", "cards": select(cards, str(r.get("body") or ""))} for r in rows]
    Path(out_json).write_text(json.dumps(items, ensure_ascii=False, indent=1))
    print(f"::notice title=fact actions::recent messages={len(items)}")
    return 0


def merge(a_json: str, b_json: str, out_json: str) -> int:
    a = json.loads(Path(a_json).read_text())
    seen = {x["message_id"] for x in a}
    b = [x for x in json.loads(Path(b_json).read_text()) if x["message_id"] not in seen]
    Path(out_json).write_text(json.dumps(a + b, ensure_ascii=False, indent=1))
    print(f"::notice title=fact actions::merged {len(a)} + {len(b)} messages")
    return 0


if __name__ == "__main__":
    if len(sys.argv) == 5 and sys.argv[1] == "merge":
        sys.exit(merge(sys.argv[2], sys.argv[3], sys.argv[4]))
    a = sys.argv
    if len(a) == 4 and a[1] == "enrich":
        sys.exit(enrich(a[2], a[3]))
    if len(a) == 4 and a[1] == "recent-set":
        sys.exit(recent_set(a[2], a[3]))
    if len(a) == 4 and a[1] == "verification-set":
        sys.exit(verification_set(a[2], a[3]))
    print(__doc__)
    sys.exit(2)
