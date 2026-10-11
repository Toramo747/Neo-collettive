# SPDX-License-Identifier: BUSL-1.1
"""Shadow test: how production queries Hacker News vs cheap variants.

Production (cloud_mcp._hn_query_search) asks search_by_date for the bare
seed, stories only, 3 hits, usually without a time window.  This harness
measures, on the same topics and in the same run, what each variant
retrieves and how much of it is real demand according to the maestro
teacher (and, as a second opinion, the production lexicon).

Read-only, public HN API, counts only.  Nothing in production is read or
changed.  Decision rule preregistered in docs/hn-retrieval-shadow.md.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import maestro_teacher  # noqa: E402
from evidence_integrity import FAMILY_TERMS, demand_signal_type  # noqa: E402
from arena_research_algorithm import TOPICS  # noqa: E402

ENDPOINT = "https://hn.algolia.com/api/v1/search_by_date"
HOLDOUT = ("crm lead tracking", "employee onboarding paperwork", "pdf document extraction", "ecommerce inventory sync")
ARMS = {
    # name: (tags, hits, window_days)
    "PROD": ("story", 3, 0),
    "STORY10": ("story", 10, 0),
    "ALL10": (None, 10, 0),
    "COMMENT10": ("comment", 10, 0),
    "ALL10_45D": (None, 10, 45),
    "ALL30_45D": (None, 30, 45),
}


def topics() -> list[str]:
    out = list(TOPICS) + list(HOLDOUT) + [list(terms)[0] for _, terms in FAMILY_TERMS]
    seen, uniq = set(), []
    for t in out:
        if t not in seen:
            seen.add(t)
            uniq.append(t)
    return uniq


def lexicon(title: str, body: str) -> bool:
    tags = demand_signal_type(title, body, query_role="buyer", strong_pain_only=False, seller_launch_guard=True,
                              url="", source="hn-algolia-routed", vendor_content_guard=True, web_buyer_voice_guard=True,
                              supply_offer_guard=True, query_echo_guard=False, query="")
    return any(t in {"PAIN", "BUY_INTENT", "PAID_DEMAND"} for t in tags)


def fetch(client, query, tags, hits, window):
    params = {"query": query, "hitsPerPage": hits}
    if tags:
        params["tags"] = tags
    if window:
        params["numericFilters"] = f"created_at_i>{int(time.time()) - window * 86400}"
    for attempt in range(3):
        try:
            r = client.get(ENDPOINT, params=params)
            r.raise_for_status()
            return [h for h in r.json().get("hits") or [] if isinstance(h, dict)]
        except Exception:
            time.sleep(1.5 * (attempt + 1))
    return []


def main() -> int:
    model = maestro_teacher.load()
    if model is None:
        print("::error title=hn shadow::teacher model unavailable")
        return 1
    res = {}
    with httpx.Client(timeout=20, headers={"User-Agent": "MYCELIX-hn-shadow/1"}) as client:
        for arm, (tags, hits, window) in ARMS.items():
            texts, titles, threads, n_topics_with_demand = [], [], [], 0
            for topic in topics():
                rows = fetch(client, topic, tags, hits, window)
                before = len(texts)
                for h in rows:
                    title = str(h.get("title") or h.get("story_title") or "")
                    body = str(h.get("comment_text") or h.get("story_text") or "")
                    texts.append(body if body.strip() else title)
                    titles.append((title, body))
                    threads.append(str(h.get("story_id") or h.get("objectID") or ""))
                sc = maestro_teacher.scores(model, texts[before:])
                if any(v >= maestro_teacher.SHADOW_THRESHOLD for v in sc):
                    n_topics_with_demand += 1
            s = maestro_teacher.scores(model, texts)
            flagged = [i for i, v in enumerate(s) if v >= maestro_teacher.SHADOW_THRESHOLD]
            lex = sum(1 for t, b in titles if lexicon(t, b))
            res[arm] = {"requests": len(topics()), "hits": len(texts), "teacher_demand": len(flagged),
                        "teacher_threads": len({threads[i] for i in flagged if threads[i]}),
                        "teacher_precision": round(len(flagged) / max(1, len(texts)), 3),
                        "topics_with_demand": n_topics_with_demand, "lexicon_signals": lex}
    print(json.dumps({"topics": len(topics()), "arms": res}, sort_keys=True))
    for arm, m in res.items():
        print(f"::notice title=hn shadow {arm}::" + " ".join(f"{k}={v}" for k, v in m.items()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
