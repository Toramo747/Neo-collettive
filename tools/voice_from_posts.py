#!/usr/bin/env python3
"""Memory that grows from approved replies (trial, 22/10).

Every reply neo posted on Agent Commons went out with Andrea's OK on the exact text
(docs/common-reply-*.json, common-kb-*, common-post-*). Their sentences are public,
approved statements, so they can serve as facts for the drafting mind and the
sentence checkers, each with its source post id and date.

  python tools/voice_from_posts.py <cutoff YYYYMMDD> <out.md>

writes docs/common-voice.md followed by one line per sentence (>= 6 words) of every
post dated <= cutoff: "- [<post id>, <date>] <sentence>". Not used in production.
"""
from __future__ import annotations

import glob
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import claim_evidence as ce  # noqa: E402


def posts(cutoff: str) -> list[tuple[str, str, list[str]]]:
    out = []
    for f in sorted(glob.glob(str(ROOT / "docs" / "common-*.json"))):
        name = Path(f).name
        m = re.search(r"(20261\d{3})", name)
        if not m or not re.match(r"common-(reply|kb|post)-", name) or m.group(1) > cutoff:
            continue
        try:
            d = json.loads(Path(f).read_text())
        except Exception:
            continue
        body = d.get("body") or d.get("result") or ""
        if not body:
            continue
        pid = "post_" + d["request_id"] if d.get("request_id") else name
        out.append((m.group(1), pid, [s for s in ce.split_sentences(body) if len(s.split()) >= 6]))
    return out


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(__doc__)
        return 2
    lines = [(ROOT / "docs" / "common-voice.md").read_text().rstrip(), "",
             "## From our own public posts (approved by Andrea, verbatim, with source)"]
    n = 0
    for date, pid, sents in posts(argv[1]):
        for s in sents:
            lines.append(f"- [{pid}, {date[:4]}-{date[4:6]}-{date[6:]}] {s}")
            n += 1
    Path(argv[2]).write_text("\n".join(lines) + "\n")
    print(f"::notice title=voice from posts::sentences={n} cutoff={argv[1]}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
