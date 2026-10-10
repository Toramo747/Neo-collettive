"""Bounded read-only HN observation -> experimental demand-pressure aggregates.

Human-independent demand is NOT established by a source username or lexical tag.
Raw API hits and opaque HMACs exist only in memory, never in output.
"""
from __future__ import annotations
import asyncio
import hashlib
import hmac
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from demand_pressure import demand_pressure_index, WEEK_SECONDS
from evidence_integrity import (
    buyer_voice_present, seller_voice_present, is_launch_title,
    demand_signal_type, is_self_contamination,
)
from discovery_v3 import query_relevance

ENDPOINT = "https://hn.algolia.com/api/v1/search_by_date"
# Limited scope: frozen topics rather than evolving/search-optimized queries.
TOPICS = (
    ("restaurant_booking", "restaurant booking"),
    ("inventory_alert", "inventory alert"),
    ("file_access", "file access"),
    ("returns_label", "return label"),
)
HITS_PER_QUERY = 30
MAX_REQUESTS = len(TOPICS) * 4
OUT = Path("/tmp/oxibay-ipd-hn-shadow-aggregates.json")


def plan(now_epoch: float) -> list[dict]:
    # Freeze an exact observation end across all 16 windows.
    anchor = int(now_epoch)
    return [
        {"topic": topic, "query": query, "week": week,
         "start": anchor - (week + 1) * WEEK_SECONDS,
         "end": anchor - week * WEEK_SECONDS}
        for topic, query in TOPICS for week in range(4)
    ]


def text_of(hit: dict) -> tuple[str, str]:
    # The story/title and comment content are available but never persisted.
    return (
        re.sub(r"<[^>]*>", " ", str(hit.get("title") or hit.get("story_title") or ""))[:400],
        re.sub(r"<[^>]*>", " ", str(hit.get("comment_text") or hit.get("story_text") or ""))[:1800],
    )


def convert(hits: list[dict], *, key: bytes, topic: str) -> list[dict]:
    """Conservatively filter; uncertainty is NOT a verified buyer request."""
    out = []
    for hit in hits:
        if not isinstance(hit, dict):
            continue
        oid = str(hit.get("objectID") or "")
        when = hit.get("created_at_i")
        if not oid or not isinstance(when, int) or isinstance(when, bool) or when <= 0:
            continue
        title, body = text_of(hit)
        if not title and not body:
            continue
        if not query_relevance(title, body, topic, {"search_alias_used": topic}).get("relevant"):
            continue
        if is_launch_title(title) or seller_voice_present(title, body):
            continue
        if is_self_contamination("https://news.ycombinator.com/", "hn-algolia-routed", title + " " + body):
            continue
        if not buyer_voice_present(title, body):
            continue
        tags = demand_signal_type(
            title, body, "buyer", strong_pain_only=True,
            seller_launch_guard=True, source="hn-algolia-routed",
            query_echo_guard=True, query=topic,
        )
        positive = next((tag for tag in ("PAID_DEMAND", "BUY_INTENT", "PAIN") if tag in tags), "")
        if not positive:
            continue
        # objectID identifies a comment. Deduplicate per HN *thread* rather
        # than comments; prevent two people in one thread counting as two asks.
        thread = str(hit.get("story_id") or hit.get("parent_id") or oid)
        request_id = hmac.new(key, ("hn-thread:" + thread).encode(), hashlib.sha256).hexdigest()
        author = str(hit.get("author") or "")
        actor = hmac.new(key, ("hn-author:" + author).encode(), hashlib.sha256).hexdigest() if author else ""
        out.append({
            "request_id": request_id, "actor_hmac": actor,
            "independent_requester_verified": False,
            "created_at_epoch": float(when),
            "origin_domain": "news.ycombinator.com",
            "source_screened": True,
            "demand_signal_tag": positive,
            "vendor_offer": False, "self_traffic": False, "agent_origin": False,
            "explicit_solution_request": bool(positive in {"BUY_INTENT", "PAID_DEMAND"}),
        })
    return out


def evaluate(plan_rows: list[dict], batches: list[dict], *, key: bytes, now_epoch: float) -> dict:
    if len(plan_rows) != MAX_REQUESTS or len(batches) != MAX_REQUESTS:
        raise ValueError("plan/provider budget mismatch")
    output = {}
    for topic, _query in TOPICS:
        indices = [i for i, row in enumerate(plan_rows) if row["topic"] == topic]
        ok = all(batches[i].get("ok") is True for i in indices)
        # Provider failures must be INCONCLUSIVE, never a negative demand rate.
        if not ok:
            output[topic] = {"status": "INCONCLUSIVE_PROVIDER_FAILURE",
                             "queries_ok": sum(batches[i].get("ok") is True for i in indices)}
            continue
        batches_by_week = {plan_rows[i]["week"]: batches[i]["hits"] for i in indices}
        if any(not isinstance(v, list) or len(v) > HITS_PER_QUERY for v in batches_by_week.values()):
            raise ValueError("provider result limit violation")
        # A query result truncated to N records is NOT a complete denominator.
        truncated = any(len(batch) == HITS_PER_QUERY for batch in batches_by_week.values())
        # Keep a per-topic unique thread count, never number of matched comments.
        input_rows = []
        for week in range(4):
            # A provider bug or wrong numericFilter cannot create artificial growth.
            eligible = [hit for hit in batches_by_week[week]
                        if isinstance(hit, dict)
                        and isinstance(hit.get("created_at_i"), int)
                        and not isinstance(hit.get("created_at_i"), bool)
                        and plan_rows[indices[week]]["start"] <= hit["created_at_i"] < plan_rows[indices[week]]["end"]]
            input_rows.extend(convert(eligible, key=key, topic=topic))
        # A source from one provider has no validated independent humans.
        score = demand_pressure_index(
            input_rows, now_epoch=now_epoch,
            exposure_current=len(batches_by_week[0]) if batches_by_week[0] else None,
            exposure_previous=len(batches_by_week[1]) if batches_by_week[1] else None,
            sampling_comparable=not truncated and all(len(x) for x in batches_by_week.values()),
        )
        # Same-source and possible API ranking shifts make trend exploratory.
        if truncated:
            score["growth_status"] = "SOURCE_TRUNCATED"
            score["growth_percent"] = None
            score["components"]["growth"] = 0
            score["ipd_score"] = round(sum(score["components"][k] * score["component_weights"][k]
                                           for k in score["component_weights"]) / 100)
        output[topic] = {
            "status": "EXPLORATORY_UNVERIFIED",
            "queries_ok": 4,
            "source_truncated": truncated,
            "ipd": score,
        }
    return {
        "schema_v": 1, "mode": "public_hn_shadow",
        "topics": output, "queries_planned": MAX_REQUESTS,
        "provider": "hn_algolia_public",
        "independent_human_labels": 0,
        "verified_unique_human_buyers": 0,
        "paid_api_calls": False,
        "raw_text_persisted": False,
        "external_ids_persisted": False,
        "commercial_gate_influence": "NONE",
        "production_state_write": False,
        "automatic_promotion": False,
    }


async def execute():
    now = datetime.now(timezone.utc).timestamp()
    queries = plan(now)
    payload = []
    async with httpx.AsyncClient(timeout=18, follow_redirects=False,
            trust_env=False, headers={"User-Agent": "OXIBAY-IPD-HN-Shadow/1.0"}) as client:
        for row in queries:
            try:
                response = await client.get(ENDPOINT, params={
                    "query": row["query"], "hitsPerPage": HITS_PER_QUERY,
                    "numericFilters": f"created_at_i>={row['start']},created_at_i<{row['end']}",
                })
                response.raise_for_status()
                doc = response.json()
                if not isinstance(doc, dict) or not isinstance(doc.get("hits"), list):
                    raise ValueError("invalid search response")
                payload.append({"ok": True, "hits": doc["hits"][:HITS_PER_QUERY]})
            except (httpx.HTTPError, ValueError, TypeError):
                payload.append({"ok": False, "hits": []})
    output = evaluate(queries, payload, key=os.urandom(32), now_epoch=int(now))
    OUT.write_text(json.dumps(output, indent=2, sort_keys=True) + "\n")
    print(json.dumps({
        "status": "SHADOW_ONLY",
        "queries_ok": sum(row.get("queries_ok", 0) for row in output["topics"].values()),
        "topics": {key: {
            "status": result["status"],
            "distinct_threads": result.get("ipd", {}).get("unique_request_threads", 0),
            "ipd_score": result.get("ipd", {}).get("ipd_score"),
            "human_verified": False,
        } for key, result in output["topics"].items()},
        "production_state_write": False,
    }, sort_keys=True))


if __name__ == "__main__":
    if sys.argv[1:] == ["--execute"]:
        asyncio.run(execute())
    elif not sys.argv[1:]:
        print(json.dumps({"mode": "PLAN_ONLY", "max_public_queries": MAX_REQUESTS,
                          "no_network": True, "no_deploy": True, "commercial_gate_influence": "NONE"}))
    else:
        raise SystemExit("unsupported arguments")
