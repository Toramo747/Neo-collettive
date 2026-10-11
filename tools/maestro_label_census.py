# SPDX-License-Identifier: BUSL-1.1
"""Maestro phase 1: census of natural demand labels on approved public APIs.

Question: over the last 6 months, how many public traces exist where someone
*proved* a need for a software tool (bounty, explicit tool request, many
reactions, paid job), per NEO commercial family?  If there are too few, the
"teacher genome" idea is not viable and we stop here.

Read-only, public APIs only, counts only: no text, URLs, ids or user names
are stored or printed.  Approved sources (chosen with Andrea, 2026-10-11):
Stack Exchange (softwarerecs), GitHub, Hacker News (Algolia), RemoteOK.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from evidence_integrity import FAMILY_TERMS  # noqa: E402

DAYS = 182
TERMS_PER_FAMILY = 2
UA = {"User-Agent": "MYCELIX-maestro-census/1 (read-only research)"}


def family_terms() -> dict[str, list[str]]:
    return {name: list(terms)[:TERMS_PER_FAMILY] for name, terms in FAMILY_TERMS}


class Census:
    def __init__(self, client: httpx.Client, since: int, gh_token: str | None):
        self.c = client
        self.since = since
        self.gh_headers = {"Accept": "application/vnd.github+json", **UA}
        if gh_token:
            self.gh_headers["Authorization"] = f"Bearer {gh_token}"
        self.errors: dict[str, int] = {}

    def _err(self, source: str) -> None:
        self.errors[source] = self.errors.get(source, 0) + 1

    def softwarerecs(self, term: str) -> int:
        """Explicit 'recommend me software for X' questions (buyer intent)."""
        try:
            r = self.c.get("https://api.stackexchange.com/2.3/search/advanced", params={
                "site": "softwarerecs", "q": term, "fromdate": self.since, "filter": "total"}, headers=UA)
            r.raise_for_status()
            return int(r.json().get("total") or 0)
        except Exception:
            self._err("softwarerecs")
            return 0

    def github(self, qualifier: str, term: str) -> int:
        date = time.strftime("%Y-%m-%d", time.gmtime(self.since))
        q = f'"{term}" is:issue {qualifier} created:>={date}'
        for attempt in range(3):
            try:
                r = self.c.get("https://api.github.com/search/issues", params={"q": q, "per_page": 1}, headers=self.gh_headers)
                if r.status_code in (403, 429):
                    time.sleep(20 * (attempt + 1))
                    continue
                r.raise_for_status()
                time.sleep(2.2)  # stay under 30 search requests/min
                return int(r.json().get("total_count") or 0)
            except Exception:
                time.sleep(3)
        self._err("github")
        return 0

    def hn(self, query: str, tags: str) -> int:
        try:
            r = self.c.get("https://hn.algolia.com/api/v1/search", params={
                "query": query, "tags": tags, "hitsPerPage": 0,
                "numericFilters": f"created_at_i>{self.since}"}, headers=UA)
            r.raise_for_status()
            return int(r.json().get("nbHits") or 0)
        except Exception:
            self._err("hn")
            return 0


def remoteok_jobs(client: httpx.Client) -> list[str]:
    try:
        r = client.get("https://remoteok.com/api", headers=UA)
        r.raise_for_status()
        rows = [x for x in r.json() if isinstance(x, dict) and x.get("position")]
        return [(" ".join(str(x.get(k) or "") for k in ("position", "description", "tags"))).lower() for x in rows]
    except Exception:
        return []


def run() -> dict:
    since = int(time.time()) - DAYS * 86400
    out: dict[str, dict[str, int]] = {}
    with httpx.Client(timeout=30) as client:
        census = Census(client, since, os.getenv("GITHUB_TOKEN"))
        jobs = remoteok_jobs(client)
        for family, terms in family_terms().items():
            row = {"softwarerecs": 0, "gh_bounty": 0, "gh_reactions10": 0, "hn_ask": 0, "hn_would_pay": 0, "remoteok_now": 0}
            for term in terms:
                row["softwarerecs"] += census.softwarerecs(term)
                row["gh_bounty"] += census.github("label:bounty", term)
                row["gh_reactions10"] += census.github("reactions:>=10", term)
                row["hn_ask"] += census.hn(term, "ask_hn")
                row["hn_would_pay"] += census.hn(f'"would pay" {term}', "comment")
                row["remoteok_now"] += sum(1 for j in jobs if term in j)
            row["proof_total"] = sum(v for k, v in row.items())
            out[family] = row
        return {"days": DAYS, "families": out, "remoteok_jobs_seen": len(jobs), "errors": census.errors}


def verdict(result: dict) -> dict:
    """Preregistered viability rule (docs/maestro.md)."""
    fams = result["families"]
    total = sum(r["proof_total"] for r in fams.values())
    strong = sum(1 for r in fams.values() if r["proof_total"] >= 30)
    return {"total_proofs": total, "families_with_30": strong, "families": len(fams),
            "viable": bool(total >= 1000 and strong >= 15)}


def main() -> int:
    result = run()
    v = verdict(result)
    print(json.dumps({**result, "verdict": v}, sort_keys=True))
    totals = {k: sum(r[k] for r in result["families"].values()) for k in next(iter(result["families"].values()))}
    print("::notice title=maestro census verdict::" + " ".join(f"{k}={val}" for k, val in v.items())
          + f" errors={result['errors']} remoteok_jobs_seen={result['remoteok_jobs_seen']}")
    print("::notice title=maestro census by source::" + " ".join(f"{k}={val}" for k, val in totals.items()))
    rows = sorted(result["families"].items(), key=lambda kv: -kv[1]["proof_total"])
    half = (len(rows) + 1) // 2
    for title, chunk in (("families A", rows[:half]), ("families B", rows[half:])):
        print(f"::notice title=maestro census {title}::" + " | ".join(
            f"{name} tot={r['proof_total']} sr={r['softwarerecs']} ghb={r['gh_bounty']} ghr={r['gh_reactions10']} "
            f"ask={r['hn_ask']} pay={r['hn_would_pay']} rok={r['remoteok_now']}" for name, r in chunk))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
