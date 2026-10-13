# SPDX-License-Identifier: BUSL-1.1
"""Maestro phase 2d: 3-year strict label pools for training.

Keeps only the precise label types measured in phases 2b/2c:
- hn_pay_first_person   (original 5 strict phrases; noisy variants dropped)
- hn_tool_seeking       (original 5 strict phrases)
- hn_product_validation (replies under Show HN)
- gh_feature_request    (feature/enhancement issues with >= 5 reactions,
                         ALL repositories, family assigned afterwards)
- se_softwarerecs       (every question is a tool request)
Window: 3 years, split by year (HN) and by month (GitHub) to get past the
1000-result cap of each API.  Pools go only to the private archive; logs
show counts per type and year, and per family.
"""
from __future__ import annotations

import json
import os
import random
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import maestro_label_census as census  # noqa: E402
from maestro_label_sample import strip_html  # noqa: E402
from maestro_label_sample_v2 import PAY_QUERIES, PAY_RE, SEEK_QUERIES, SEEK_RE, family_of  # noqa: E402
from maestro_label_sample_v3 import VALID_QUERIES, VALID_RE  # noqa: E402

YEARS = 3
SEED = 20261014
PER_TYPE_SAMPLE = 20
GH_PAGES_PER_MONTH = 3  # 300 issues per month max


def year_windows(now: int) -> list[tuple[int, int]]:
    return [(now - (i + 1) * 365 * 86400, now - i * 365 * 86400) for i in range(YEARS)]


def month_windows(now: datetime) -> list[tuple[str, str]]:
    out = []
    y, m = now.year, now.month
    for _ in range(YEARS * 12):
        start = f"{y:04d}-{m:02d}-01"
        ny, nm = (y + 1, 1) if m == 12 else (y, m + 1)
        end_dt = datetime(ny, nm, 1, tzinfo=timezone.utc).timestamp() - 86400
        out.append((start, datetime.fromtimestamp(end_dt, timezone.utc).strftime("%Y-%m-%d")))
        y, m = (y - 1, 12) if m == 1 else (y, m - 1)
    return out


def hn_pool(client, queries, regex, windows, tags, require_show=False):
    out, seen = [], set()
    for lo, hi in windows:
        for q in queries:
            for page in range(20):
                try:
                    data = client.get("https://hn.algolia.com/api/v1/search", headers=census.UA, params={
                        "query": q, "tags": tags, "hitsPerPage": 50, "page": page,
                        "numericFilters": f"created_at_i>{lo},created_at_i<={hi}"}).json()
                except Exception:
                    break
                for h in data.get("hits") or []:
                    oid = str(h.get("objectID"))
                    if oid in seen:
                        continue
                    text = strip_html(h.get("comment_text") or h.get("story_text") or "")
                    title = h.get("title") or h.get("story_title") or ""
                    show = str(h.get("story_title") or title).lower().startswith("show hn")
                    if not regex.search(title + " " + text) or (require_show and not show):
                        continue
                    seen.add(oid)
                    out.append({"url": "https://news.ycombinator.com/item?id=" + oid, "title": title,
                                "text": text[:1500], "created": h.get("created_at"),
                                "family": family_of(title + " " + text)})
                if page + 1 >= int(data.get("nbPages") or 0):
                    break
    return out


def gh_pool(client, headers, months):
    out, seen, month_totals = [], set(), {}
    for start, end in months:
        q = f'is:issue label:enhancement,feature,"feature request" reactions:>=5 created:{start}..{end}'
        for page in range(1, GH_PAGES_PER_MONTH + 1):
            try:
                r = client.get("https://api.github.com/search/issues", headers=headers,
                               params={"q": q, "per_page": 100, "page": page, "sort": "reactions"})
                if r.status_code in (403, 429):
                    time.sleep(30)
                    r = client.get("https://api.github.com/search/issues", headers=headers,
                                   params={"q": q, "per_page": 100, "page": page, "sort": "reactions"})
                time.sleep(2.2)
                data = r.json()
            except Exception:
                break
            if page == 1:
                month_totals[start[:7]] = int(data.get("total_count") or 0)
            items = data.get("items") or []
            for it in items:
                url = it.get("html_url")
                if url in seen:
                    continue
                seen.add(url)
                title = it.get("title") or ""
                body = strip_html(it.get("body") or "")
                out.append({"url": url, "title": title, "text": body[:1500], "created": it.get("created_at"),
                            "reactions": (it.get("reactions") or {}).get("total_count"),
                            "family": family_of(title + " " + body)})
            if len(items) < 100:
                break
    return out, month_totals


def se_pool(client, since):
    out = []
    for page in range(1, 41):
        try:
            data = client.get("https://api.stackexchange.com/2.3/questions", headers=census.UA, params={
                "site": "softwarerecs", "fromdate": since, "pagesize": 100, "page": page,
                "order": "desc", "sort": "creation", "filter": "withbody"}).json()
        except Exception:
            break
        for q in data.get("items") or []:
            title = strip_html(q.get("title") or "")
            text = strip_html(q.get("body") or "")
            out.append({"url": q.get("link"), "title": title, "text": text[:1500],
                        "created": q.get("creation_date"), "score": q.get("score"),
                        "family": family_of(title + " " + text)})
        if not data.get("has_more"):
            break
        if data.get("backoff"):
            time.sleep(int(data["backoff"]) + 1)
    return out


def year_of(row) -> str:
    c = row.get("created")
    if isinstance(c, (int, float)):
        return time.strftime("%Y", time.gmtime(c))
    return str(c or "")[:4]


def main(argv):
    out_dir = Path(argv[1])
    now = int(time.time())
    windows = year_windows(now)
    gh = {"Accept": "application/vnd.github+json", **census.UA}
    if os.getenv("GITHUB_TOKEN"):
        gh["Authorization"] = "Bearer " + os.environ["GITHUB_TOKEN"]
    with httpx.Client(timeout=40) as client:
        gh_rows, gh_months = gh_pool(client, gh, month_windows(datetime.now(timezone.utc)))
        pools = {
            "hn_pay_first_person": hn_pool(client, PAY_QUERIES, PAY_RE, windows, "comment"),
            "hn_tool_seeking": hn_pool(client, SEEK_QUERIES, SEEK_RE, windows, "(comment,ask_hn)"),
            "hn_product_validation": hn_pool(client, VALID_QUERIES, VALID_RE, windows, "comment", require_show=True),
            "gh_feature_request": gh_rows,
            "se_softwarerecs": se_pool(client, now - YEARS * 365 * 86400),
        }
    stamp = time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())
    out_dir.mkdir(parents=True, exist_ok=True)
    with (out_dir / f"maestro-pool-v4-{stamp}.jsonl").open("w", encoding="utf-8") as fh:
        for t, rows in pools.items():
            for r in rows:
                fh.write(json.dumps(dict(r, type=t), ensure_ascii=False) + "\n")
    rng = random.Random(SEED)
    with (out_dir / f"maestro-sample-v4-{stamp}.jsonl").open("w", encoding="utf-8") as fh:
        for t, rows in pools.items():
            pick = list(rows)
            rng.shuffle(pick)
            for r in pick[:PER_TYPE_SAMPLE]:
                fh.write(json.dumps(dict(r, type=t), ensure_ascii=False) + "\n")
    by_type = " | ".join(
        f"{t}={len(rows)} (" + ",".join(f"{y}:{n}" for y, n in sorted(
            {y: sum(1 for r in rows if year_of(r) == y) for y in {year_of(r) for r in rows}}.items())) + ")"
        for t, rows in pools.items())
    fam_counts = {}
    for rows in pools.values():
        for r in rows:
            if r.get("family"):
                fam_counts[r["family"]] = fam_counts.get(r["family"], 0) + 1
    print(f"::notice title=maestro pool v4 types::{by_type} | stamp={stamp}")
    print("::notice title=maestro pool v4 families::" + " ".join(f"{k}={v}" for k, v in sorted(fam_counts.items(), key=lambda kv: -kv[1]))
          + f" | no_family={sum(len(r) for r in pools.values()) - sum(fam_counts.values())}")
    gh_total = sum(gh_months.values())
    print(f"::notice title=maestro gh months::reported_total={gh_total} fetched={len(gh_rows)} months={len(gh_months)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
