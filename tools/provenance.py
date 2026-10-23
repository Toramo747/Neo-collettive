#!/usr/bin/env python3
"""Provenance receipts for neo's replies (trial, 23/10): where every sentence of a posted reply comes from.

A provenance file, docs/provenance/<post id>.json, holds only public material:
  - the posted text and its sha256;
  - each sentence with the fact cards it cites (or the fixed phrase it is);
  - the cited cards, each with a public source: a bullet of docs/common-voice.md, a sentence of one of
    our own posted replies (docs/common-*.json), or a tool run (tool, inputs, outcome, code version);
  - which checks the draft passed (code check, meaning check).
It is committed to the public repository, so the daily receipt-log anchor (repo commit -> OpenTimestamps,
Software Heritage) fixes it too.

  python tools/provenance.py build <reply.json> <draft.json> <message_id> <board.json> <out.json>
  python tools/provenance.py verify <provenance.json> [--live]     strict check, exit 1 on any failure
  python tools/provenance.py auto <reply.json> <private_dir> <out_dir> after a post: if the reply is a mind draft
                                                                     posted word for word, build + strict check

verify (strict) checks, all of them, and stops at nothing:
  1. sha256 of posted_text is posted_sha256, and the text equals the body in docs/ for that post id;
  2. the sentences, joined, are exactly the posted text after the @name;
  3. every sentence is either one fixed phrase copied exactly, or cites cards that exist;
  4. every cited sentence passes the same deterministic code check as when it was drafted;
  5. every card's source is public and resolves: the voice bullet / posted sentence is found word for word,
     a tool card names the code by its git blob id, and with --live the tool is run again and must give the
     same outcome;
  6. privacy: only whitelisted fields; no private paths or verdicts.
"""
from __future__ import annotations

import asyncio
import glob
import hashlib
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

ALLOWED_TOP = {"v", "post_id", "reply_to", "agent", "posted_text", "posted_sha256", "mind", "sentences", "cards",
               "checks", "built_at_utc", "notes"}
PRIVATE_RX = re.compile(r"private-labels|experience\.jsonl|handled\.json|common/drafts|needs-andrea|MODEL_LABEL", re.I)


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def git(*a: str) -> str:
    return subprocess.run(["git", "-C", str(ROOT), *a], capture_output=True, text=True).stdout.strip()


def posted_reply(post_id: str) -> dict | None:
    for f in glob.glob(str(ROOT / "docs" / "common-*.json")):
        try:
            d = json.loads(Path(f).read_text())
        except Exception:
            continue
        if "post_" + str(d.get("request_id") or "") == post_id:
            return d
    return None


def build(reply_json: str, draft_json: str, message_id: str, board_json: str, out_json: str) -> int:
    import fact_actions as fa
    from fact_mind import PHRASES
    reply = json.loads(Path(reply_json).read_text())
    draft_file = json.loads(Path(draft_json).read_text())
    draft = next(x for x in draft_file["drafts"] if x["id"] == message_id)
    post_id = "post_" + reply["request_id"]
    cards: dict[str, dict] = {}
    notes = []
    for s in draft.get("sentences") or []:
        for c in s.get("cites") or []:
            c = str(c).strip("[] ")
            if c in PHRASES or c in cards:
                continue
            saved = (draft.get("cards") or {}).get(c)
            if saved:
                cards[c] = saved
                continue
            # older drafts kept no cards: rebuild a tool card by running the same tool on the same input
            from fact_actions import submission
            board = json.loads(Path(board_json).read_text())
            msg = next((str(e.get("body") or "") for k, v in board.items() if isinstance(v, list)
                        for e in v if isinstance(e, dict) and e.get("id") == message_id), "")
            sub = submission(msg or "")
            if sub:
                r = fa.run_verify(*sub)
                cards[c] = {"text": fa.card_text(sub[0], r), "source": "tool:verify_quote",
                            "tool": {"name": "verify_quote", "url": sub[0], "quote": sub[1], "outcome": r.get("outcome"),
                                     "code": {"quote_verifier.py": git("rev-parse", "HEAD:quote_verifier.py")}}}
                notes.append(f"{c} was rebuilt on {datetime.now(timezone.utc):%Y-%m-%d} by running the same tool on the same input; "
                             "the draft of that run did not store its cards.")
    prov = {"v": 1, "post_id": post_id, "reply_to": reply.get("reply_to"), "agent": draft.get("agent"),
            "posted_text": reply["body"], "posted_sha256": sha(reply["body"]),
            "mind": {"name": "neo fact-card mind", "model": draft_file.get("model"), "run": draft_file.get("run_id")},
            "sentences": [{"text": s.get("text"), "cites": [str(c).strip("[] ") for c in s.get("cites") or []]}
                          for s in draft.get("sentences") or []],
            "cards": cards,
            "checks": {"code_check": "pass" if all(not s.get("issues") for s in draft.get("sentences") or []) else "fail",
                       "meaning_check": [s.get("meaning") for s in draft.get("sentences") or [] if s.get("meaning")]},
            "built_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "notes": notes}
    Path(out_json).parent.mkdir(parents=True, exist_ok=True)
    Path(out_json).write_text(json.dumps(prov, ensure_ascii=False, indent=1) + "\n")
    print(f"::notice title=provenance::built {Path(out_json).name} sentences={len(prov['sentences'])} cards={len(cards)}")
    return 0


def verify(prov_json: str, live: bool = False) -> int:
    from fact_mind import PHRASES, check_sentence
    import claim_evidence as ce
    import fact_actions as fa
    p = json.loads(Path(prov_json).read_text())
    fails, oks = [], []
    def ok(cond: bool, what: str):
        (oks if cond else fails).append(what)
    # 6. privacy first
    ok(set(p) <= ALLOWED_TOP, "only whitelisted fields")
    ok(not PRIVATE_RX.search(json.dumps(p)), "no private paths or verdicts")
    # 1. text and hash
    ok(sha(p["posted_text"]) == p["posted_sha256"], "posted_sha256 matches posted_text")
    rep = posted_reply(p["post_id"])
    ok(bool(rep) and rep.get("body") == p["posted_text"], "posted_text equals the reply in docs/")
    # 2. sentences rebuild the text
    head = f"@{p['agent']} "
    joined = head + " ".join(str(s["text"]).strip() for s in p["sentences"])
    ok(joined == p["posted_text"], "sentences joined are exactly the posted text")
    # 3 + 4. each sentence
    cards = {k: v["text"] for k, v in p["cards"].items()}
    for i, s in enumerate(p["sentences"], 1):
        cites = s["cites"]
        if cites and all(c in PHRASES for c in cites):
            ok(any(ce.norm(s["text"]) == ce.norm(PHRASES[c]) for c in cites), f"sentence {i}: fixed phrase copied exactly")
            continue
        ok(all(c in cards for c in cites) and bool(cites), f"sentence {i}: every cited card exists")
        issues = check_sentence({"text": s["text"], "cites": cites}, cards, "")
        ok(not issues, f"sentence {i}: code check passes ({','.join(issues) or 'ok'})")
    # 5. sources
    voice = (ROOT / "docs" / "common-voice.md").read_text()
    for cid, c in p["cards"].items():
        src = c.get("source") or ""
        if src == "common-voice.md":
            ok(ce.norm(c["text"]) in ce.norm(voice), f"{cid}: found word for word in common-voice.md")
        elif src.startswith("post_"):
            r = posted_reply(src)
            ok(bool(r) and ce.norm(c["text"]) in ce.norm(r.get("body") or ""), f"{cid}: found word for word in {src}")
        elif src == "tool:verify_quote":
            t = c.get("tool") or {}
            blob = (t.get("code") or {}).get("quote_verifier.py")
            ok(bool(blob) and bool(git("cat-file", "-t", blob)), f"{cid}: names the tool's code by git blob id")
            ok(c["text"] == fa.card_text(t.get("url"), {"outcome": t.get("outcome")}), f"{cid}: card text follows from the tool outcome")
            if live:
                r = fa.run_verify(t["url"], t["quote"])
                ok(r.get("outcome") == t.get("outcome"), f"{cid}: re-run gives the same outcome ({r.get('outcome')})")
        else:
            ok(False, f"{cid}: source {src!r} is not a public source we can check")
    for w in oks:
        print(f"OK   {w}")
    for w in fails:
        print(f"FAIL {w}")
    print(f"::notice title=provenance verify::{Path(prov_json).name} ok={len(oks)} fail={len(fails)} live={live}")
    return 1 if fails else 0


def auto(reply_json: str, private_dir: str, out_dir: str) -> int:
    reply = json.loads(Path(reply_json).read_text())
    rid, body = reply.get("reply_to"), reply.get("body")
    hit = None
    for f in sorted(glob.glob(str(Path(private_dir) / "common" / "drafts" / "*factmind*.json"))):
        for x in json.loads(Path(f).read_text()).get("drafts") or []:
            if x.get("id") == rid and x.get("body") == body:
                hit = f
    if not hit:
        print("::notice title=provenance::no receipt: this reply is not a mind draft posted word for word")
        return 0
    boards = sorted(glob.glob(str(Path(private_dir) / "common" / "board-*.json")))
    out = Path(out_dir) / f"post_{reply['request_id']}.json"
    build(reply_json, hit, rid, boards[-1], str(out))
    return verify(str(out), live=True)


if __name__ == "__main__":
    if len(sys.argv) == 5 and sys.argv[1] == "auto":
        sys.exit(auto(sys.argv[2], sys.argv[3], sys.argv[4]))
    a = sys.argv
    if len(a) == 7 and a[1] == "build":
        sys.exit(build(a[2], a[3], a[4], a[5], a[6]))
    if len(a) >= 3 and a[1] == "verify":
        sys.exit(verify(a[2], "--live" in a))
    print(__doc__)
    sys.exit(2)
