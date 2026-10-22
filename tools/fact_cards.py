#!/usr/bin/env python3
"""Fact cards for the Common mind (trial, 22/10): the code finds the facts, the model only words them.

A card is {"id", "text", "source"}. Sources, all deterministic:
  voice   - each bullet of docs/common-voice.md
  post    - each sentence (>= 6 words) of a reply/knowledge entry neo already posted with Andrea's OK
  tool    - behaviour of verify_quote, computed by running quote_verifier.judge on the pinned test page
  state   - receipt-log count/head, production version (from the runtime snapshot)

Cards are built from the repository *as it was at a given git commit*, so a replay of an old
message only sees what was known when we answered it.

  python tools/fact_cards.py replay-set <out.json> <private_dir>   build the replay set (needs full git history)
"""
from __future__ import annotations

import glob
import importlib.util
import json
import math
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import claim_evidence as ce  # noqa: E402

STOP = set("""the a an and or of to in on for is are was were it its we you our your with that this be do does what not as at by
from has have had their they i me my so but if then than can will would just also only one any all there here which who whom
how when where why been being into about over more most such no yes per via each other same these those them his her he she""".split())
ALWAYS = ("never", "decisions about", "no logs or reputation")  # rule bullets always shown
QUOTE_TOPIC = re.compile(r"verify_quote|verbatim|paraphrase|stitched|not_found|ellipsis|…|\.\.\.|teaser|\bquot", re.I)


def git(*args: str) -> str:
    return subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, text=True).stdout


def show(commit: str, path: str) -> str:
    return git("show", f"{commit}:{path}")


def words(text: str) -> list[str]:
    return [w for w in re.findall(r"[a-z0-9_.]+|[一-鿿]", ce.norm(text)) if w not in STOP and len(w) > 1]


def voice_cards(commit: str) -> list[dict]:
    text = show(commit, "docs/common-voice.md")
    cards, cur = [], ""
    for line in text.splitlines():
        if line.startswith("- "):
            if cur:
                cards.append(cur)
            cur = line[2:].strip()
        elif line.startswith("  ") and cur:
            cur += " " + line.strip()
        else:
            if cur:
                cards.append(cur)
            cur = ""
    if cur:
        cards.append(cur)
    return [{"text": c, "source": "common-voice.md"} for c in cards]


def post_cards(commit: str) -> list[dict]:
    out = []
    for name in git("ls-tree", "--name-only", commit, "docs/").split():
        base = name.split("/")[-1]
        if not re.match(r"common-(reply|kb|post)-.*\.json$", base):
            continue
        try:
            d = json.loads(show(commit, name))
        except Exception:
            continue
        body = d.get("body") or ""
        pid = "post_" + d["request_id"] if d.get("request_id") else base
        for s in ce.split_sentences(body):
            if len(s.split()) >= 6:
                out.append({"text": s, "source": pid})
    return out


def tool_cards(commit: str) -> list[dict]:
    src = show(commit, "quote_verifier.py")
    page = show(commit, "docs/conformance/verify_quote_page_v1.txt")
    if not src or not page:
        return []
    cards = []
    for name, what in (("MIN_QUOTE_WORDS", "minimum words in a quote"), ("MAX_QUOTE_CHARS", "maximum quote length in characters"),
                       ("PARAPHRASE_SHARE", "share of matching four-word runs needed for paraphrase"),
                       ("MAX_CUT_GAP_CHARS", "maximum characters between pieces of a quote cut with an ellipsis")):
        m = re.search(rf"^{name}\s*=\s*([0-9.]+)", src, re.M)
        if m:
            cards.append({"text": f"verify_quote: {what} is {m.group(1)}.", "source": "tool:quote_verifier.py"})
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "qv_at_commit.py"
        p.write_text(src)
        spec = importlib.util.spec_from_file_location("qv_at_commit", p)
        qv = importlib.util.module_from_spec(spec)
        try:
            sys.path.insert(0, str(ROOT))
            spec.loader.exec_module(qv)
        except Exception:
            return cards
    sents = [s for s in re.split(r"(?<=[.!?])\s+", " ".join(page.split())) if len(s.split()) >= 8]
    if len(sents) < 4:
        return cards
    a, b, z = sents[1], sents[2], sents[-1]
    aw, zw = a.split(), z.split()
    cases = [
        ("an exact sentence from the page", a),
        ("the same sentence with one word changed", " ".join(aw[:-2] + ["purple"] + aw[-1:])),
        ("only the first part of the sentence, as a cut-off teaser shows it", " ".join(aw[: max(4, len(aw) // 2)])),
        ("the first part and the end of one sentence joined with …", " ".join(aw[:4]) + "…" + " ".join(aw[-4:])),
        ("pieces from far-apart parts of the page joined with …", " ".join(aw[:5]) + "…" + " ".join(zw[-5:])),
        ("a sentence that is not on the page", "The orange submarine counts every quiet harbour light at noon."),
    ]
    for label, q in cases:
        try:
            r = qv.judge(q, page)
        except Exception:
            continue
        fields = ", ".join(k for k in r if k != "context")
        extra = f"; four_word_overlap {r['four_word_overlap']}" if "four_word_overlap" in r else ""
        cards.append({"text": f"verify_quote on {label}: outcome {r['outcome']}{extra}; the result carries these fields: {fields}.",
                      "source": "tool:quote_verifier.judge"})
    return cards


def state_cards(commit: str) -> list[dict]:
    out = []
    try:
        h = json.loads(show(commit, "docs/receipts-log/head.json"))
        out.append({"text": f"The public receipt log holds {h['count']} entries; its head is {h['head']}.",
                    "source": "docs/receipts-log/head.json"})
    except Exception:
        pass
    try:
        v = json.loads(show(commit, "neo_latest_result.json")).get("neo_version")
        snap = git("log", "-1", "--format=%h %cI", commit, "--", "neo_latest_result.json").split()
        if v and snap:
            out.append({"text": f"The service in production reported version {v} in runtime snapshot {snap[0]} ({snap[1]}).",
                        "source": f"snapshot:{snap[0]}"})
    except Exception:
        pass
    return out


def all_cards(commit: str) -> list[dict]:
    cards = voice_cards(commit) + state_cards(commit) + tool_cards(commit) + post_cards(commit)
    seen, out = set(), []
    for c in cards:
        k = ce.norm(c["text"])
        if k not in seen:
            seen.add(k)
            out.append(c)
    return out


def select(cards: list[dict], message: str, k: int = 14) -> list[dict]:
    """Deterministic retrieval: idf-weighted word overlap with the message, plus the rule cards."""
    docs = [set(words(c["text"])) for c in cards]
    n = len(docs)
    df: dict[str, int] = {}
    for d in docs:
        for w in d:
            df[w] = df.get(w, 0) + 1
    q = set(words(message))
    scored = []
    for i, d in enumerate(docs):
        s = sum(math.log(1 + n / df[w]) for w in d & q)
        if cards[i]["source"].startswith("tool:"):
            s *= 1.3
        scored.append((s, i))
    rules = [i for i, c in enumerate(cards) if c["source"] == "common-voice.md" and c["text"].lower().startswith(ALWAYS)]
    tools = []
    if QUOTE_TOPIC.search(message):  # questions about verify_quote get the computed behaviour, always
        tools = [i for i, c in enumerate(cards) if c["source"].startswith("tool:")]
    top = [i for s, i in sorted(scored, reverse=True) if s > 0 and i not in rules and i not in tools][:k]
    pick = tools + top + rules
    return [{"id": f"F{j + 1}", **cards[i]} for j, i in enumerate(pick)]


def replay_set(out_path: str, private_dir: str) -> int:
    msgs = {}
    for f in sorted(glob.glob(str(Path(private_dir) / "common" / "board-*.json"))):
        d = json.loads(Path(f).read_text())
        for k, v in d.items():
            if isinstance(v, list):
                for r in v:
                    if isinstance(r, dict) and r.get("id"):
                        msgs[r["id"]] = r
    items = []
    for f in sorted(glob.glob(str(ROOT / "docs" / "common-reply-*.json"))):
        d = json.loads(Path(f).read_text())
        rid = d.get("reply_to")
        m = re.search(r"(20261\d{3})", f)
        if not rid or not m or m.group(1) < "20261019" or rid not in msgs:
            continue
        c = git("log", "--diff-filter=A", "--format=%H", "-1", "--", str(Path(f).relative_to(ROOT))).strip()
        if not c:
            continue
        before = c + "^"
        src = msgs[rid]
        body = str(src.get("body") or "")[:1500]
        cards = select(all_cards(before), body)
        items.append({"message_id": rid, "agent": src.get("agent"), "body": body, "target": d.get("body"),
                      "reply_file": Path(f).name, "known_at": before, "cards": cards})
    Path(out_path).write_text(json.dumps(items, ensure_ascii=False, indent=1))
    print(f"::notice title=fact cards::replay items={len(items)} cards_per_item={sum(len(i['cards']) for i in items) // max(1, len(items))}")
    return 0


if __name__ == "__main__":
    if len(sys.argv) == 4 and sys.argv[1] == "replay-set":
        sys.exit(replay_set(sys.argv[2], sys.argv[3]))
    print(__doc__)
    sys.exit(2)
