# SPDX-License-Identifier: BUSL-1.1
"""Maestro phase 2b: strict natural labels, sampled for precision.

Changes after phase 2a (5/100 real):
- HN: only first-person willingness to pay ("I'd pay for", "I would pay for",
  "shut up and take my money", ...) or explicit tool seeking ("is there a
  tool", "looking for a tool/app", "I wish there was a tool"), confirmed by a
  regex on the text, not just by the search engine.  Product context flagged
  (reply under a "Show HN").
- GitHub: feature requests (label:enhancement) with >= 20 reactions whose
  TITLE contains a family term as a whole word.
- Dropped: GitHub bounties (farms), RemoteOK (role ads), softwarerecs (empty).
Texts + links go only to the private archive; logs show counts.
"""
from __future__ import annotations

import json
import os
import random
import re
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import maestro_label_census as census  # noqa: E402
from maestro_label_sample import strip_html  # noqa: E402

PER_TYPE = 20
SEED = 20261012
PAY_QUERIES = ('"I would pay for"', '"I\'d pay for"', '"I would happily pay"', '"take my money"', '"I\'d gladly pay"')
SEEK_QUERIES = ('"is there a tool"', '"looking for a tool"', '"wish there was a tool"', '"is there an app"', '"looking for an app"')
PAY_RE = re.compile(r"\b(i|we)\s*(would|'d|will|'ll)\s+(happily\s+|gladly\s+|definitely\s+)?pay\b|\btake my money\b", re.I)
SEEK_RE = re.compile(r"\b(is there|looking for|i wish there (was|were)|anyone know of|recommend)\s+(a|an|any)\s+(good\s+)?(tool|app|service|software|extension|library|saas|plugin)\b", re.I)
TYPES = ("hn_pay_first_person", "hn_tool_seeking", "gh_feature_title")


def family_of(text: str) -> str | None:
    low = text.lower()
    for family, terms in census.family_terms().items():
        if any(re.search(r"\b" + re.escape(t) + r"\b", low) for t in terms):
            return family
    return None


def hn_pool(client: httpx.Client, queries, regex, since: int, tags: str) -> list[dict]:
    out = []
    for q in queries:
        for page in range(3):
            try:
                r = client.get("https://hn.algolia.com/api/v1/search", headers=census.UA, params={
                    "query": q, "tags": tags, "hitsPerPage": 50, "page": page,
                    "numericFilters": f"created_at_i>{since}"})
                hits = r.json().get("hits") or []
            except Exception:
                break
            for h in hits:
                text = strip_html(h.get("comment_text") or h.get("story_text") or "")
                title = h.get("title") or h.get("story_title") or ""
                if not regex.search(title + " " + text):
                    continue
                out.append({"url": "https://news.ycombinator.com/item?id=" + str(h.get("objectID")),
                            "title": title, "text": text[:1500], "created": h.get("created_at"),
                            "show_hn_context": str(h.get("story_title") or title).lower().startswith("show hn"),
                            "family": family_of(title + " " + text)})
            if len(hits) < 50:
                break
    return out


def gh_pool(client: httpx.Client, headers: dict, since: int) -> list[dict]:
    date = time.strftime("%Y-%m-%d", time.gmtime(since))
    out = []
    for family, terms in census.family_terms().items():
        for term in terms:
            try:
                r = client.get("https://api.github.com/search/issues", headers=headers, params={
                    "q": f'"{term}" in:title is:issue label:enhancement reactions:>=20 created:>={date}', "per_page": 10})
                time.sleep(2.2)
                for it in r.json().get("items") or []:
                    title = it.get("title") or ""
                    if not re.search(r"\b" + re.escape(term) + r"\b", title.lower()):
                        continue
                    out.append({"url": it.get("html_url"), "title": title, "text": strip_html(it.get("body") or "")[:1500],
                                "created": it.get("created_at"), "reactions": (it.get("reactions") or {}).get("total_count"),
                                "family": family})
            except Exception:
                pass
    return out


def main(argv: list[str]) -> int:
    out_dir = Path(argv[1])
    since = int(time.time()) - census.DAYS * 86400
    gh = {"Accept": "application/vnd.github+json", **census.UA}
    if os.getenv("GITHUB_TOKEN"):
        gh["Authorization"] = "Bearer " + os.environ["GITHUB_TOKEN"]
    with httpx.Client(timeout=30) as client:
        pools = {
            "hn_pay_first_person": hn_pool(client, PAY_QUERIES, PAY_RE, since, "comment"),
            "hn_tool_seeking": hn_pool(client, SEEK_QUERIES, SEEK_RE, since, "(comment,ask_hn)"),
            "gh_feature_title": gh_pool(client, gh, since),
        }
    rng = random.Random(SEED)
    rows = []
    for typ in TYPES:
        seen, uniq = set(), []
        for r in pools[typ]:
            if r["url"] not in seen:
                seen.add(r["url"])
                uniq.append(r)
        pools[typ] = uniq
        pick = list(uniq)
        rng.shuffle(pick)
        rows += [dict(r, type=typ) for r in pick[:PER_TYPE]]
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"maestro-sample-v2-{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}.jsonl"
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    parts = []
    for typ in TYPES:
        pool = pools[typ]
        fam = sum(1 for r in pool if r.get("family"))
        show = sum(1 for r in pool if r.get("show_hn_context"))
        parts.append(f"{typ}: pool={len(pool)} with_family={fam} show_hn={show}")
    print("::notice title=maestro sample v2::" + " | ".join(parts) + f" | file={path.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
