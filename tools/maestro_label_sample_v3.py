# SPDX-License-Identifier: BUSL-1.1
"""Maestro phase 2c: widened strict pools (volume at fixed precision).

Same strict rules as v2, much wider net:
- HN: 12+ phrase variants per label, up to 20 pages per query (Algolia max).
- New label: product validation under Show HN ("looking for something like
  this", "exactly what I needed").
- GitHub: titled issues with >= 5 reactions, kept only if labelled as a
  feature/enhancement request.
- Stack Exchange softwarerecs: every question is an explicit tool request.
Texts + links only in the private archive; logs show pool sizes.
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
from maestro_label_sample_v2 import family_of  # noqa: E402

PER_TYPE = 20
SEED = 20261013
MAX_PAGES = 20
PAY_QUERIES = ('"I would pay for"', '"I\'d pay for"', '"I would happily pay"', '"I\'d happily pay"',
               '"I\'d gladly pay"', '"take my money"', '"pay good money"', '"I would definitely pay"',
               '"willing to pay for"', '"I\'d buy this"', '"I would buy this"', '"I\'d pay money"')
SEEK_QUERIES = ('"is there a tool"', '"is there an app"', '"is there a service"', '"is there any software"',
                '"looking for a tool"', '"looking for an app"', '"looking for software"', '"wish there was a tool"',
                '"wish there was an app"', '"anyone know of a tool"', '"recommend a tool"', '"know a tool"')
VALID_QUERIES = ('"looking for something like this"', '"exactly what I needed"', '"exactly what I was looking for"',
                 '"been looking for this"', '"needed this"', '"I was looking for an app like this"')
PAY_RE = re.compile(r"\b(i|we)\s*(would|'d|will|'ll)\s+(happily\s+|gladly\s+|definitely\s+|totally\s+)?(pay|buy)\b"
                    r"|\btake my money\b|\b(i'm|i am|we're|we are)\s+willing to pay\b|\bpay good money\b", re.I)
SEEK_RE = re.compile(r"\b(is there|looking for|i wish there (was|were)|anyone know of|know of|recommend)\s+"
                     r"(a|an|any)\s+(good\s+|decent\s+)?(tool|app|service|software|extension|library|saas|plugin)\b", re.I)
VALID_RE = re.compile(r"\b(looking for something like this|exactly what i (needed|was looking for)|been looking for (this|something like this)|needed this|looking for an app like this)\b", re.I)
TYPES = ("hn_pay_first_person", "hn_tool_seeking", "hn_product_validation", "gh_feature_request", "se_softwarerecs")


def hn_pool(client, queries, regex, since, tags, require_show=False):
    out, seen = [], set()
    for q in queries:
        for page in range(MAX_PAGES):
            try:
                r = client.get("https://hn.algolia.com/api/v1/search", headers=census.UA, params={
                    "query": q, "tags": tags, "hitsPerPage": 50, "page": page,
                    "numericFilters": f"created_at_i>{since}"})
                data = r.json()
            except Exception:
                break
            hits = data.get("hits") or []
            for h in hits:
                oid = str(h.get("objectID"))
                if oid in seen:
                    continue
                text = strip_html(h.get("comment_text") or h.get("story_text") or "")
                title = h.get("title") or h.get("story_title") or ""
                show = str(h.get("story_title") or title).lower().startswith("show hn")
                if not regex.search(title + " " + text) or (require_show and not show):
                    continue
                seen.add(oid)
                out.append({"url": "https://news.ycombinator.com/item?id=" + oid, "title": title, "text": text[:1500],
                            "created": h.get("created_at"), "show_hn_context": show, "family": family_of(title + " " + text)})
            if page + 1 >= int(data.get("nbPages") or 0):
                break
    return out


def gh_pool(client, headers, since):
    date = time.strftime("%Y-%m-%d", time.gmtime(since))
    out, seen = [], set()
    for family, terms in census.family_terms().items():
        for term in terms:
            try:
                r = client.get("https://api.github.com/search/issues", headers=headers, params={
                    "q": f'"{term}" in:title is:issue reactions:>=5 created:>={date}', "per_page": 50})
                time.sleep(2.2)
                for it in r.json().get("items") or []:
                    labels = " ".join(str(l.get("name") or "") for l in it.get("labels") or []).lower()
                    title = it.get("title") or ""
                    feature = ("feature" in labels or "enhancement" in labels
                               or re.match(r"^\s*\[?(feat|feature|feature request|request)\b", title, re.I))
                    if not feature or it.get("html_url") in seen:
                        continue
                    if not re.search(r"\b" + re.escape(term) + r"\b", title.lower()):
                        continue
                    seen.add(it.get("html_url"))
                    out.append({"url": it.get("html_url"), "title": title, "text": strip_html(it.get("body") or "")[:1500],
                                "created": it.get("created_at"), "reactions": (it.get("reactions") or {}).get("total_count"),
                                "family": family})
            except Exception:
                pass
    return out


def se_pool(client, since):
    out = []
    for page in range(1, 11):
        try:
            r = client.get("https://api.stackexchange.com/2.3/questions", headers=census.UA, params={
                "site": "softwarerecs", "fromdate": since, "pagesize": 100, "page": page,
                "order": "desc", "sort": "creation", "filter": "withbody"})
            data = r.json()
        except Exception:
            break
        for q in data.get("items") or []:
            title = strip_html(q.get("title") or "")
            text = strip_html(q.get("body") or "")
            out.append({"url": q.get("link"), "title": title, "text": text[:1500], "created": q.get("creation_date"),
                        "score": q.get("score"), "family": family_of(title + " " + text)})
        if not data.get("has_more"):
            break
    return out


def main(argv):
    out_dir = Path(argv[1])
    since = int(time.time()) - census.DAYS * 86400
    gh = {"Accept": "application/vnd.github+json", **census.UA}
    if os.getenv("GITHUB_TOKEN"):
        gh["Authorization"] = "Bearer " + os.environ["GITHUB_TOKEN"]
    with httpx.Client(timeout=30) as client:
        pools = {
            "hn_pay_first_person": hn_pool(client, PAY_QUERIES, PAY_RE, since, "comment"),
            "hn_tool_seeking": hn_pool(client, SEEK_QUERIES, SEEK_RE, since, "(comment,ask_hn)"),
            "hn_product_validation": hn_pool(client, VALID_QUERIES, VALID_RE, since, "comment", require_show=True),
            "gh_feature_request": gh_pool(client, gh, since),
            "se_softwarerecs": se_pool(client, since),
        }
    rng = random.Random(SEED)
    rows = []
    for typ in TYPES:
        pick = list(pools[typ])
        rng.shuffle(pick)
        rows += [dict(r, type=typ) for r in pick[:PER_TYPE]]
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())
    (out_dir / f"maestro-sample-v3-{stamp}.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    (out_dir / f"maestro-pool-v3-{stamp}.jsonl").write_text("".join(json.dumps(dict(r, type=t), ensure_ascii=False) + "\n"
                                                                    for t in TYPES for r in pools[t]), encoding="utf-8")
    parts = [f"{t}: pool={len(pools[t])} with_family={sum(1 for r in pools[t] if r.get('family'))}" for t in TYPES]
    print("::notice title=maestro sample v3::" + " | ".join(parts) + f" | stamp={stamp}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
