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


def run_verify(url: str, quote: str) -> dict:
    import quote_verifier as qv  # same code as production
    try:
        return asyncio.run(qv.verify_quote(url, quote, caller="neo-fact-mind-replay"))
    except Exception as e:
        return {"ok": False, "error": type(e).__name__}


def enrich(in_json: str, out_json: str) -> int:
    items = json.loads(Path(in_json).read_text())
    n = 0
    for it in items:
        sub = submission(it.get("body") or "")
        if not sub:
            continue
        r = run_verify(*sub)
        nxt = max([int(c["id"][1:]) for c in it["cards"]] + [0]) + 1
        it["cards"] = [{"id": f"F{nxt}", "text": card_text(sub[0], r), "source": "tool:verify_quote(live)"}] + it["cards"]
        it["action"] = {"tool": "verify_quote", "url": sub[0], "outcome": r.get("outcome") or r.get("error")}
        n += 1
    Path(out_json).write_text(json.dumps(items, ensure_ascii=False, indent=1))
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
    if len(a) == 4 and a[1] == "verification-set":
        sys.exit(verification_set(a[2], a[3]))
    print(__doc__)
    sys.exit(2)
