#!/usr/bin/env python3
"""Fact-card mind in shadow mode for every message to neo (22/10, Andrea's OK). Drafts only; never posts.

Each message is routed by code: verify (link + exact sentence: verify_quote runs), anchor (questions about the
receipt log and its anchors: archive links, Bitcoin attestation), andrea (a commitment is asked of neo: no draft,
it goes to Andrea, listed in common/factmind/needs-andrea.jsonl) or facts (fact cards and citations).

  python tools/fact_shadow.py pending <private_dir> <out_set.json>   messages to neo with a link + exact sentence,
                                                                      not yet drafted, last 72 h (exit 3 if none)
  python tools/fact_shadow.py collect <kernel_out.json> <private_dir> store drafts where the experience log
                                                                      matches them to the posted reply

Each draft is shown to Andrea as the mind's own, before any other version (his rule of 19/10). The drafts go to
common/drafts/<tag>-factmind.json, so tools/common_experience.py grades them like the other mind's drafts.
"""
from __future__ import annotations

import glob
import json
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
HANDLED = "common/factmind/shadow-handled.json"
NO_REPLY_RE = re.compile(r"no further (action|reply|response)[\w ,]{0,40}? (is|are) (needed|requested|required|expected)|"
                         r"no (reply|response) (is )?(needed|expected|owed)|nothing (more|else) is (needed|requested)|"
                         r"no need to (reply|respond)", re.I)  # not "silence is fine": invitations say that too
WINDOW_MS = 36 * 3600 * 1000  # 22/10: 72 h brought back messages already settled in their thread


def pending(private_dir: str, out_json: str) -> int:
    from fact_actions import submission
    from fact_cards import all_cards, select
    p = Path(private_dir)
    done = set(json.loads((p / HANDLED).read_text())) if (p / HANDLED).exists() else set()
    for f in glob.glob(str(ROOT / "docs" / "common-reply-*.json")):  # already answered by us
        try:
            done.add(json.loads(Path(f).read_text()).get("reply_to"))
        except Exception:
            pass
    boards = sorted(glob.glob(str(p / "common" / "board-*.json")))
    if not boards:
        return 3
    latest = json.loads(Path(boards[-1]).read_text())
    now = time.time() * 1000
    from common_deep import addressed_to_neo  # same filter as the other mind
    from fact_actions import route
    job_results = {x for j in latest.get("neo_jobs") or [] for x in (j.get("results") or [])}
    def for_neo(r: dict) -> bool:  # addressed to neo, a reply to one of our posts, or a result on one of our jobs
        return (addressed_to_neo(str(r.get("body") or "")) or str(r.get("supersedes") or "").startswith("post_neo")
                or r.get("id") in job_results)
    rows = [r for r in latest.get("replies_for_neo") or [] if isinstance(r, dict) and r.get("id")
            and r.get("agent") not in ("neo", "anonymous") and r["id"] not in done
            and now - float(r.get("createdAt") or 0) < WINDOW_MS and for_neo(r)]
    # 22/10: a message that says no reply is needed gets none (Codex: "No further action ... requested")
    quiet = [r for r in rows if NO_REPLY_RE.search(str(r.get("body") or ""))]
    if quiet:
        hp = p / HANDLED
        hp.parent.mkdir(parents=True, exist_ok=True)
        done = done | {r["id"] for r in quiet}
        hp.write_text(json.dumps(sorted(done)))
        print(f"::notice title=fact shadow::no reply needed={len(quiet)}")
    rows = [r for r in rows if r not in quiet]
    if not rows:
        print("::notice title=fact shadow::no new message to neo")
        return 3
    # decisions: no draft; listed for Andrea, marked handled
    asks = [r for r in rows if route(str(r.get("body") or "")) == "andrea"]
    if asks:
        log = p / "common" / "factmind" / "needs-andrea.jsonl"
        log.parent.mkdir(parents=True, exist_ok=True)
        with log.open("a") as fh:
            for r in asks:
                fh.write(json.dumps({"at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "message_id": r["id"],
                                     "agent": r.get("agent")}) + "\n")
        hp = p / HANDLED
        hp.parent.mkdir(parents=True, exist_ok=True)
        hp.write_text(json.dumps(sorted(done | {r["id"] for r in asks})))
        print(f"::notice title=fact shadow::needs Andrea={len(asks)} (no draft)")
    rows = [r for r in rows if r not in asks]
    if not rows:
        return 3
    head = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    cards = all_cards(head)
    items = [{"message_id": r["id"], "agent": r.get("agent"), "body": str(r.get("body") or "")[:1500], "target": None,
              "reply_file": "shadow", "known_at": head, "cards": select(cards, str(r.get("body") or ""))} for r in rows[-6:]]
    Path(out_json).write_text(json.dumps(items, ensure_ascii=False))
    print(f"::notice title=fact shadow::drafting for {len(items)} messages")
    return 0


def collect(out_json: str, private_dir: str) -> int:
    d = json.loads(Path(out_json).read_text())
    run = (d.get("runs") or [{}])[0]
    res = run.get("compose") or []
    p = Path(private_dir)
    tag = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    drafts = [{"id": x["message_id"], "agent": x["agent"], "covers": [x["message_id"]], "source_body": "",
               "should_reply": x.get("should_reply", True), "category": x.get("route") or "facts", "body": x.get("body"),
               "ready": bool(x.get("ready")), "issues": sorted({i for s in x.get("sentences") or [] for i in s.get("issues") or []}),
               "sentences": x.get("sentences"), "mind": f"fact-mind {run.get('model')}"} for x in res if not x.get("error")]
    out = p / "common" / "drafts" / f"{tag}-factmind.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"run_id": tag, "model": run.get("model"), "replay": False, "mind": "fact-mind",
                               "presented": False, "drafts": drafts}, ensure_ascii=False, indent=1))
    hp = p / HANDLED
    done = set(json.loads(hp.read_text())) if hp.exists() else set()
    hp.parent.mkdir(parents=True, exist_ok=True)
    hp.write_text(json.dumps(sorted(done | {x["id"] for x in drafts})))
    print(f"::notice title=fact shadow::drafts={len(drafts)} ready={sum(x['ready'] for x in drafts)} errors={len(res) - len(drafts)}")
    return 0


if __name__ == "__main__":
    a = sys.argv
    if len(a) == 4 and a[1] == "pending":
        sys.exit(pending(a[2], a[3]))
    if len(a) == 4 and a[1] == "collect":
        sys.exit(collect(a[2], a[3]))
    print(__doc__)
    sys.exit(2)
