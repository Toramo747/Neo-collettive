#!/usr/bin/env python3
"""Compound-key memory for the Common mind (trial, 20/10).

docs/common-memory.json holds docs/common-voice.md rewritten as memories with
compound keys: detail pieces from left to right, last piece = category from a
controlled vocabulary. Rules / limits / voice are always retrieved, so a safety
rule can never be dropped by a bad match.

  python tools/memory_keys.py check            every excerpt is word for word in
                                               common-voice.md, every fact there is
                                               covered, every category is allowed
  python tools/memory_keys.py pick FILE|-      which memories a message pulls in
  python tools/memory_keys.py voice FILE|-     the reduced facts sheet for that message
  python tools/memory_keys.py compare FULL.json KEYED.json
                                               counts only (safe for public logs):
                                               drafts, unsupported sentences, guard issues

Not wired into production: common_deep.py still sends the whole sheet.
Nothing is adopted without a measurement and Andrea's ok.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MEMORY = ROOT / "docs" / "common-memory.json"
VOICE = ROOT / "docs" / "common-voice.md"
TOP = 6          # at most this many matched memories, besides the always-on ones
SEP = " · "
STOP = {"the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "is", "are", "it", "we", "you",
        "our", "your", "with", "that", "this", "be", "do", "does", "what", "not"}


def ws(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def load() -> dict:
    return json.loads(MEMORY.read_text())


def pieces(key: str) -> list[str]:
    return [p.strip() for p in key.split(SEP.strip()) if p.strip()]


def category(m: dict) -> str:
    return pieces(m["key"])[-1]


def words(text: str) -> set[str]:
    out = set()
    for w in re.findall(r"[\w.…\-]+", text.lower()):
        w2 = re.sub(r"[^0-9a-z…]", "", w)       # verify_quote -> verifyquote
        if w2 and w2 not in STOP:
            out.add(w2)
        out.update(x for x in re.split(r"[_\-.]", w) if x and x not in STOP)
    if "…" in text or "..." in text:
        out.add("…")
    return out


def pick(message: str, data: dict | None = None) -> list[dict]:
    data = data or load()
    always = set(data["always"])
    msg = words(message)
    scored = []
    for i, m in enumerate(data["memories"]):
        if category(m) in always:
            continue
        terms = set(pieces(m["key"])[:-1]) | {a.lower() for a in m.get("aliases", [])}
        hit = len(terms & msg)
        if hit:
            scored.append((-hit, i, m))
    scored.sort(key=lambda t: (t[0], t[1]))
    chosen = [m for _, _, m in scored[:TOP]]
    return chosen + [m for m in data["memories"] if category(m) in always]


def render(mems: list[dict]) -> str:
    lines = ["# neo on Agent Commons — facts that match this message (keyed memory trial)", ""]
    for m in mems:
        lines.append(f"## {m['key']}")
        lines += [f"- {t}" for t in m["text"]]
        lines.append("")
    return "\n".join(lines)


def check() -> int:
    data = load()
    voice = ws(VOICE.read_text())
    allowed = set(data["categories"])
    bad = 0
    covered = [False] * len(voice)
    for m in data["memories"]:
        if category(m) not in allowed:
            print(f"::error title=memory keys::category not allowed: {m['key']}")
            bad += 1
        for t in m["text"]:
            i = voice.find(ws(t))
            if i < 0:
                print(f"::error title=memory keys::not word for word in common-voice.md: {m['key']}")
                bad += 1
            else:
                covered[i:i + len(ws(t))] = [True] * len(ws(t))
    # every bullet after the intro must be covered
    body = VOICE.read_text().split("## Who we are", 1)[1]
    bullets = [ws(b) for b in re.split(r"\n\s*-\s", "\n" + body) if ws(b)]
    missing = 0
    for b in bullets:
        b = re.sub(r"\s*## .*$", "", b)  # drop a heading glued to the last bullet of a section
        i = voice.find(b)
        if i >= 0 and any(not c and voice[i + k] != " " for k, c in enumerate(covered[i:i + len(b)])):
            missing += 1
            print(f"::warning title=memory keys::fact not covered: {b[:70]}")
    print(f"::notice title=memory keys::memories={len(data['memories'])} errors={bad} uncovered={missing}")
    return 1 if bad or missing else 0


def compare(full_path: str, keyed_path: str) -> int:
    """Same messages, two arms. Prints aggregate counts only."""
    sys.path.insert(0, str(ROOT / "tools"))
    import common_deep
    arms = {}
    for name, path in (("full", full_path), ("keyed", keyed_path)):
        d = json.loads(Path(path).read_text())
        drafts = d.get("drafts") or []
        replied = [r for r in drafts if r.get("should_reply") and str(r.get("body") or "").strip()]
        issues: dict[str, int] = {}
        for r in replied:
            for x in common_deep.guard(r, r.get("source_body") or ""):
                issues[x] = issues.get(x, 0) + 1
        arms[name] = {"messages": len(drafts), "replies": len(replied),
                      "sentences": sum(r.get("checked_sentences") or 0 for r in replied),
                      "unsupported": sum(len(r.get("unsupported") or []) for r in replied),
                      "commits_neo": sum(1 for r in replied if r.get("commits_neo")),
                      "issues": issues}
        a = arms[name]
        print(f"::notice title=keyed memory {name}::messages={a['messages']} replies={a['replies']} "
              f"sentences={a['sentences']} unsupported={a['unsupported']} commits_neo={a['commits_neo']} "
              f"issues={json.dumps(issues, sort_keys=True)}")
    return 0


def main(argv: list[str]) -> int:
    if len(argv) >= 4 and argv[1] == "compare":
        return compare(argv[2], argv[3])
    if len(argv) < 2 or argv[1] not in ("check", "pick", "voice"):
        print(__doc__)
        return 2
    if argv[1] == "check":
        return check()
    msg = sys.stdin.read() if len(argv) < 3 or argv[2] == "-" else Path(argv[2]).read_text()
    mems = pick(msg)
    if argv[1] == "pick":
        for m in mems:
            print(m["key"])
    else:
        print(render(mems))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
