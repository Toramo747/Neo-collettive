"""Verify agent-submitted evidence: does the public link exist and contain the quote?

usage: verify_quotes.py <private_dir>
Reads <private_dir>/common/verify_queue.json  [{"id","url","quote"}]
Writes <private_dir>/common/verify_results.json; the log prints counts only.
"""
from __future__ import annotations

import html
import json
import re
import sys
import urllib.request
from pathlib import Path

UA = {"User-Agent": "NEO-verify/1", "Accept": "application/json"}


def get(url: str):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def norm(text: str) -> str:
    text = html.unescape(re.sub(r"<[^>]+>", " ", text or ""))
    text = text.replace("`", "").replace("’", "'").replace("“", '"').replace("”", '"')
    return " ".join(text.lower().split())


ELLIPSIS_RE = re.compile(r"\s*(?:\.\.\.+|…)\s*")


def quote_segments(quote: str) -> list[str]:
    """Agents often cut quotes with '...' mid-sentence (2026-10-16: a real quote
    was rejected for that). Split on ellipses, drop the partial word next to a
    cut, and require every remaining segment of 3+ words to be on the page."""
    raw = (quote or "").strip().strip('"“”')
    parts = ELLIPSIS_RE.split(raw)
    segs = []
    for i, part in enumerate(parts):
        words = norm(part).split()
        if i > 0 and words:                       # text after a cut may start mid-word
            words = words[1:]
        if i < len(parts) - 1 and words:          # text before a cut may end mid-word
            words = words[:-1]
        if len(words) >= 3:
            segs.append(" ".join(words))
    return segs or ([norm(raw)] if norm(raw) else [])


def quote_in(quote: str, text: str) -> bool:
    segs = quote_segments(quote)
    hay = norm(text)
    return bool(segs) and all(s in hay for s in segs)


def fetch(url: str) -> dict:
    m = re.match(r"https://github\.com/([^/]+)/([^/]+)/issues/(\d+)", url)
    if m:
        base = f"https://api.github.com/repos/{m[1]}/{m[2]}/issues/{m[3]}"
        issue = get(base)
        parts = [{"by_opener": True, "text": (issue.get("title") or "") + " " + (issue.get("body") or "")}]
        opener = (issue.get("user") or {}).get("login")
        for c in get(base + "/comments?per_page=100"):
            parts.append({"by_opener": (c.get("user") or {}).get("login") == opener, "text": c.get("body") or ""})
        return {"kind": "github_issue", "created": issue.get("created_at"), "parts": parts}
    m = re.match(r"https://news\.ycombinator\.com/item\?id=(\d+)", url)
    if m:
        item = get(f"https://hn.algolia.com/api/v1/items/{m[1]}")
        title = item.get("title") or ""
        return {"kind": "hn_" + str(item.get("type")), "created": item.get("created_at"),
                "show_hn": title.lower().startswith(("show hn", "launch hn")),
                "parts": [{"by_opener": True, "text": title + " " + (item.get("text") or "")}]}
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "NEO-verify/1"}), timeout=30) as r:
        return {"kind": "web", "parts": [{"by_opener": None, "text": r.read().decode("utf-8", "replace")}]}


def main() -> int:
    d = Path(sys.argv[1]) / "common"
    queue = json.loads((d / "verify_queue.json").read_text())
    out = []
    for q in queue:
        row = {"id": q["id"], "url": q["url"]}
        try:
            page = fetch(q["url"])
            hit = [p for p in page["parts"] if quote_in(q["quote"], p["text"])]
            row.update({"exists": True, "kind": page["kind"], "created": page.get("created"),
                        "quote_found": bool(hit), "quote_by_opener": bool(hit and hit[0]["by_opener"]),
                        "show_hn": page.get("show_hn")})
        except Exception as exc:
            row.update({"exists": False, "error": type(exc).__name__})
        out.append(row)
    (d / "verify_results.json").write_text(json.dumps(out, indent=1))
    print("::notice title=Quote verification::" + json.dumps({
        "items": len(out), "exist": sum(1 for r in out if r.get("exists")),
        "quote_found": sum(1 for r in out if r.get("quote_found"))}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
