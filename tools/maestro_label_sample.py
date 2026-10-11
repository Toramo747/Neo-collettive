# SPDX-License-Identifier: BUSL-1.1
"""Maestro phase 2a: sample natural labels to measure their precision.

For the label-rich families, collects a seeded random sample per label type
(GitHub bounty, GitHub reactions>=10, Ask HN, "would pay" comments, RemoteOK
jobs) and writes it to the PRIVATE archive (public texts + links, never to
the public repo or logs).  Prints only counts and the automatic lexical
check: does the matched text literally contain the family term (and, for
"would pay", the phrase)?  Semantic precision is annotated afterwards.
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

RICH = ("integration_api", "ai_tools", "crm_lead_ops", "developer_tools", "spreadsheet_process",
        "customer_support", "marketing_seo", "data_cleanup", "manual_data_entry", "workflow_automation",
        "compliance_tools", "it_hygiene", "cybersecurity_tools", "ecommerce_tools")
PER_TYPE = 20
POOL_PER_QUERY = 10
SEED = 20261011
TYPES = ("gh_bounty", "gh_reactions10", "hn_ask", "hn_would_pay", "remoteok_now")


def strip_html(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", str(text or ""))).strip()


def contains_term(text: str, term: str) -> bool:
    return re.search(r"\b" + re.escape(term.lower()) + r"\b", text.lower()) is not None


def collect(client: httpx.Client, gh_headers: dict, since: int) -> dict[str, list[dict]]:
    date = time.strftime("%Y-%m-%d", time.gmtime(since))
    terms = census.family_terms()
    pools: dict[str, list[dict]] = {t: [] for t in TYPES}
    jobs = []
    try:
        r = client.get("https://remoteok.com/api", headers=census.UA)
        jobs = [x for x in r.json() if isinstance(x, dict) and x.get("position")]
    except Exception:
        pass
    for family in RICH:
        for term in terms[family]:
            for typ, qual in (("gh_bounty", "label:bounty"), ("gh_reactions10", "reactions:>=10")):
                try:
                    r = client.get("https://api.github.com/search/issues", headers=gh_headers, params={
                        "q": f'"{term}" is:issue {qual} created:>={date}', "per_page": POOL_PER_QUERY})
                    time.sleep(2.2)
                    for it in (r.json().get("items") or []):
                        pools[typ].append({"family": family, "term": term, "url": it.get("html_url"),
                                           "title": it.get("title") or "", "text": strip_html(it.get("body") or "")[:1500],
                                           "created": it.get("created_at"), "reactions": (it.get("reactions") or {}).get("total_count")})
                except Exception:
                    pass
            for typ, query, tags in (("hn_ask", term, "ask_hn"), ("hn_would_pay", f'"would pay" {term}', "comment")):
                try:
                    r = client.get("https://hn.algolia.com/api/v1/search", headers=census.UA, params={
                        "query": query, "tags": tags, "hitsPerPage": POOL_PER_QUERY, "numericFilters": f"created_at_i>{since}"})
                    for h in (r.json().get("hits") or []):
                        pools[typ].append({"family": family, "term": term,
                                           "url": "https://news.ycombinator.com/item?id=" + str(h.get("objectID")),
                                           "title": h.get("title") or h.get("story_title") or "",
                                           "text": strip_html(h.get("comment_text") or h.get("story_text") or "")[:1500],
                                           "created": h.get("created_at")})
                except Exception:
                    pass
            for j in jobs:
                blob = " ".join(str(j.get(k) or "") for k in ("position", "description", "tags")).lower()
                if term in blob:
                    pools["remoteok_now"].append({"family": family, "term": term, "url": j.get("url"),
                                                  "title": j.get("position") or "", "text": strip_html(j.get("description") or "")[:1500],
                                                  "created": j.get("date")})
    return pools


def sample(pools: dict[str, list[dict]]) -> list[dict]:
    rng = random.Random(SEED)
    out = []
    for typ in TYPES:
        seen, uniq = set(), []
        for row in pools[typ]:
            if row["url"] and row["url"] not in seen:
                seen.add(row["url"])
                uniq.append(row)
        rng.shuffle(uniq)
        for row in uniq[:PER_TYPE]:
            text = row["title"] + " " + row["text"]
            row = dict(row, type=typ, term_literal=contains_term(text, row["term"]))
            if typ == "hn_would_pay":
                row["phrase_literal"] = "would pay" in text.lower()
            out.append(row)
    return out


def main(argv: list[str]) -> int:
    out_dir = Path(argv[1])
    since = int(time.time()) - census.DAYS * 86400
    gh = {"Accept": "application/vnd.github+json", **census.UA}
    if os.getenv("GITHUB_TOKEN"):
        gh["Authorization"] = "Bearer " + os.environ["GITHUB_TOKEN"]
    with httpx.Client(timeout=30) as client:
        pools = collect(client, gh, since)
    rows = sample(pools)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"maestro-sample-{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}.jsonl"
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    parts = []
    for typ in TYPES:
        sub = [r for r in rows if r["type"] == typ]
        lit = sum(1 for r in sub if r["term_literal"])
        extra = ""
        if typ == "hn_would_pay":
            extra = f" phrase={sum(1 for r in sub if r.get('phrase_literal'))}"
        parts.append(f"{typ}: pool={len(pools[typ])} sample={len(sub)} term_literal={lit}{extra}")
    print("::notice title=maestro sample::" + " | ".join(parts) + f" | file={path.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
