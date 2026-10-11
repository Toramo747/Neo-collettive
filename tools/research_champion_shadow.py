# SPDX-License-Identifier: BUSL-1.1
"""Shadow comparison: research-arena champion vs production HN retrieval.

Read-only.  Queries the public HN Algolia API, scores every arm with the SAME
scorer (``arena_research_algorithm.score_hits``, built on production's
buyer/demand primitives) and prints aggregate counts only.  No raw text,
no URLs, no thread ids are persisted or printed.  Nothing in production is
read or written.

Arms (preregistered, see docs/research-champion-shadow.md):
  PROD         production call shape: bare topic phrase, stories, 3 hits
  PROD_EQ      production wording at the champion's hit budget
               (bare topic, stories, 120 hits, same 45-day window)
  CHAMP        champion genome exactly as the arena runs it
  CHAMP_BUDGET champion's first query at production budget (stories, 3 hits)

Topic sets:
  training  the 4 arena topics the champion evolved on
  holdout   4 topics fixed before the first run, never seen by the arena
"""
from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import arena_research_algorithm as arena  # noqa: E402

CHAMPION_ID = "g75-elite-1"
CHAMPION = {
    "query_mode": "mixed", "query_count": 4, "recency_days": 45, "min_relevance_tokens": 1,
    "suffix_family": "core", "topic_shape": "compact", "query_frame": "plain",
    "term_order": "signal_first", "source_scope": "all",
}
# Topic -> compact form (champion uses the compact shape).
TRAINING = {topic: arena.TOPIC_SHAPES["compact"][topic] for topic in arena.TOPICS}
# Preregistered holdout, chosen from production commercial families not used
# by the arena (crm_lead_ops, hr_tools, document_processing, ecommerce_tools).
HOLDOUT = {
    "crm lead tracking": "lead tracking",
    "employee onboarding paperwork": "onboarding paperwork",
    "pdf document extraction": "pdf extraction",
    "ecommerce inventory sync": "inventory sync",
}
SCORER = {"min_relevance_tokens": 1}  # identical scoring for every arm
WINDOW_DAYS = 45
CHAMP_HITS = 30


def champion_queries(compact: str) -> list[str]:
    genes = arena.clamp_genome(CHAMPION)
    suffixes = arena.QUERY_SUFFIXES[genes["suffix_family"]][genes["query_mode"]][: genes["query_count"]]
    return [f"{s} {compact}" if genes["term_order"] == "signal_first" else f"{compact} {s}" for s in suffixes]


def arm_plan(arm: str, topic: str, compact: str) -> list[tuple[str, str | None, int]]:
    """(query, tag, hits) per call."""
    if arm == "PROD":
        return [(topic, "story", 3)]
    if arm == "PROD_EQ":
        return [(topic, "story", CHAMP_HITS * 4)]
    if arm == "CHAMP":
        return [(q, None, CHAMP_HITS) for q in champion_queries(compact)]  # scope "all": no tag
    if arm == "CHAMP_BUDGET":
        return [(champion_queries(compact)[0], "story", 3)]
    raise ValueError(arm)


async def fetch(client: httpx.AsyncClient, query: str, tag: str | None, hits: int, cutoff: int) -> list[dict]:
    params = {"query": query, "hitsPerPage": hits, "numericFilters": f"created_at_i>{cutoff}"}
    if tag:
        params["tags"] = tag
    for attempt in range(3):
        try:
            r = await client.get(arena.HN_ENDPOINT, params=params)
            r.raise_for_status()
            data = r.json()
            return [h for h in (data.get("hits") or []) if isinstance(h, dict)]
        except Exception:
            await asyncio.sleep(1.5 * (attempt + 1))
    raise RuntimeError("hn_unavailable")


def thread_ids(rows: list[dict]) -> set[str]:
    out = set()
    for row in rows:
        for h in row["hits"]:
            out.add(str(h.get("story_id") or h.get("objectID") or ""))
    return out


async def run() -> dict:
    cutoff = int(time.time()) - WINDOW_DAYS * 86400
    results: dict[str, dict] = {}
    async with httpx.AsyncClient(timeout=20, headers={"User-Agent": "MYCELIX-shadow/1"}) as client:
        for set_name, topics in (("training", TRAINING), ("holdout", HOLDOUT)):
            for arm in ("PROD", "PROD_EQ", "CHAMP", "CHAMP_BUDGET"):
                rows = []
                for topic, compact in topics.items():
                    for query, tag, hits in arm_plan(arm, topic, compact):
                        rows.append({"topic": topic, "query": query, "hits": await fetch(client, query, tag, hits, cutoff)})
                metrics = arena.score_hits(SCORER, rows)
                metrics["queries"] = len(rows)
                metrics["signals_per_100_hits"] = round(100 * metrics["signal_hits"] / max(1, metrics["total_hits"]), 2)
                metrics["_threads"] = thread_ids(rows)
                results[f"{set_name}:{arm}"] = metrics
    # Overlap of retrieved threads (counts only): how much CHAMP adds beyond PROD_EQ.
    for set_name in ("training", "holdout"):
        a = results[f"{set_name}:CHAMP"]["_threads"]
        b = results[f"{set_name}:PROD_EQ"]["_threads"]
        results[f"{set_name}:overlap"] = {"champ_threads": len(a), "prod_eq_threads": len(b), "shared": len(a & b), "champ_only": len(a - b)}
    for v in results.values():
        v.pop("_threads", None)
    return results


KEYS = ("queries", "total_hits", "relevant_hits", "signal_hits", "unique_signal_threads", "buyer_hits",
        "precision", "signals_per_100_hits", "vendor_rejected", "supply_rejected", "fitness")


def main() -> int:
    results = asyncio.run(run())
    print(json.dumps({"champion": CHAMPION_ID, "window_days": WINDOW_DAYS, "results": results}, sort_keys=True))
    # GitHub keeps at most 10 notices per step: 8 arms + 1 overlap line.
    print("::notice title=shadow overlap::" + " | ".join(
        key.split(":")[0] + " " + " ".join(f"{k}={v}" for k, v in m.items())
        for key, m in results.items() if key.endswith(":overlap")))
    for key, m in results.items():
        if key.endswith(":overlap"):
            continue
        else:
            print(f"::notice title=shadow {key}::" + " ".join(f"{k}={m.get(k)}" for k in KEYS))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
