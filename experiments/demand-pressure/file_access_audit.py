"""Single-topic public HN audit of exploratory IPD file-access signals.

The first live IPD run retained only aggregate statistics. Re-query the
approximately same fixed four-week period and show bounded, count-only risk
annotations. This is NOT exact-case replay or human demand validation.
"""
from __future__ import annotations

import asyncio
from collections import Counter
from importlib.util import module_from_spec, spec_from_file_location
import json
import os
from pathlib import Path
import re
import sys

import httpx

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
spec = spec_from_file_location("oxibay_ipd_hn_base", Path(__file__).with_name("hn_shadow.py"))
hn = module_from_spec(spec)
spec.loader.exec_module(hn)
from discovery_v3 import query_relevance

# First successful aggregate-only run occurred 2026-10-10 04:58 UTC.
# This is an approximate anchor, NOT the original unrecorded exact epoch.
# Never call an equal count proof of identical discussions.
APPROX_FIRST_RUN_EPOCH = 1791608320
TOPIC = "file_access"
QUERY = "file access"
WEEKS = 4
HITS_PER_QUERY = 30
MAX_CALLS = 4
OUTPUT = Path("/tmp/oxibay-ipd-file-access-audit-aggregates.json")

SELLER_RISK = re.compile(
    r"\b(?:i|we)\s+(?:offer|provide|sell)\b|"
    r"\blooking\s+for\s+(?:new\s+)?(?:clients|customers)\b|"
    r"\bavailable\s+for\s+(?:freelance|consulting)\b",
    re.I,
)
# Source-domain nouns are weak heuristics: they only prioritize private review.
FILE_CONTEXT = re.compile(
    r"\b(?:files?|folders?|directories|directory|shares?|"
    r"permissions?|read[- ]only|access[- ]control|acl|"
    r"documents?|smb|nfs|drive|filesystem)\b", re.I
)
TOPIC_TYPES = {
    "access_control": re.compile(r"\b(?:permissions?|read[- ]only|acl|denied|unauthorized|access[- ]control)\b", re.I),
    "sharing_sync": re.compile(r"\b(?:share|sharing|shared|drive|sync|collaborat)\b", re.I),
    "retrieval": re.compile(r"\b(?:recover|backup|restore|lost|deleted|find|search)\b", re.I),
}


def protocol() -> list[dict]:
    p = hn.plan(APPROX_FIRST_RUN_EPOCH)
    selected = [row for row in p if row["topic"] == TOPIC]
    if len(selected) != WEEKS or any(row["week"] != i for i,row in enumerate(selected)):
        raise ValueError("frozen audit window mismatch")
    return selected


def analyze(batches: list[dict], *, secret: bytes) -> dict:
    planned = protocol()
    if len(batches) != MAX_CALLS:
        raise ValueError("audit budget mismatch")
    ok = sum(item.get("ok") is True for item in batches)
    base = {
        "schema_v": 1, "mode": "public_hn_file_access_audit_shadow",
        "window_anchor_approximate": True, "reference_initial_unique_threads": 8,
        "replayed_exact_original_cases": False, "queries_planned": MAX_CALLS,
        "queries_ok": ok, "provider": "hn_algolia_public",
        "commercial_gate_influence": "NONE", "production_state_write": False,
        "automated_rejection_or_promotion": False,
        "human_reviewed_cases": 0, "independently_verified_buyers": 0,
        "raw_content_persisted": False, "source_identifiers_persisted": False,
        "requester_identifiers_persisted": False,
    }
    if ok != MAX_CALLS:
        return {**base, "status": "INCONCLUSIVE_PROVIDER_FAILURE"}
    rows_by_thread = {}
    counts = Counter()
    week_counts = []
    for p, batch in zip(planned, batches):
        hits = batch.get("hits")
        if not isinstance(hits, list) or len(hits) > HITS_PER_QUERY:
            raise ValueError("source limits violated")
        counts["source_rows"] += len(hits)
        if len(hits) >= HITS_PER_QUERY:
            counts["truncated_weeks"] += 1
        week_threads = set()
        for hit in hits:
            if not isinstance(hit, dict):
                counts["invalid_source_rows"] += 1
                continue
            born = hit.get("created_at_i")
            if not isinstance(born, int) or isinstance(born, bool) or not p["start"] <= born < p["end"]:
                counts["outside_week_rows"] += 1
                continue
            title, body = hn.text_of(hit)
            converted = hn.convert([hit], key=secret, topic=QUERY)
            if not converted:
                counts["rejected_by_existing_shadow_guards"] += 1
                continue
            row = converted[0]
            token = row["request_id"]
            week_threads.add(token)
            rel = query_relevance(title, body, QUERY, {"search_alias_used": QUERY})
            overlap = len(rel.get("overlap") or [])
            text = title + " " + body
            group = rows_by_thread.setdefault(token, {
                "week": p["week"], "matched_rows": 0, "author_tokens": set(),
                "one_token_match": False, "seller_risk": False,
                "file_nouns": False, "explicit_request": False,
                "types": set(), "source_content_missing": False,
            })
            group["matched_rows"] += 1
            group["one_token_match"] |= overlap < 2
            group["seller_risk"] |= bool(SELLER_RISK.search(text))
            group["file_nouns"] |= bool(FILE_CONTEXT.search(text))
            group["explicit_request"] |= bool(row["explicit_solution_request"])
            group["source_content_missing"] |= not bool(body.strip())
            for kind, pattern in TOPIC_TYPES.items():
                if pattern.search(text):
                    group["types"].add(kind)
            if row.get("actor_hmac"):
                group["author_tokens"].add(row["actor_hmac"])
        week_counts.append(len(week_threads))
    c = Counter()
    for group in rows_by_thread.values():
        c["candidate_threads"] += 1
        c["candidate_rows"] += group["matched_rows"]
        c["multiple_comments_per_thread"] += group["matched_rows"] > 1
        c["multiple_unverified_authors_in_thread"] += len(group["author_tokens"]) > 1
        c["single_token_topic_overlap"] += group["one_token_match"]
        c["seller_role_review_flags"] += group["seller_risk"]
        c["missing_file_context_noun_flags"] += not group["file_nouns"]
        c["explicit_solution_request_machine_flags"] += group["explicit_request"]
        c["source_body_missing_flags"] += group["source_content_missing"]
        c["review_priority_threads"] += (
            group["one_token_match"] or group["seller_risk"]
            or not group["file_nouns"] or group["source_content_missing"]
        )
        for kind in group["types"]:
            c["theme_" + kind] += 1
        c["theme_unspecified"] += not group["types"]
    # Counts do not create or replace human labels. Percent precision is unknown.
    return {
        **base, "status": "MACHINE_TRIAGE_ONLY",
        "provider_counts": {key:int(counts[key]) for key in (
            "source_rows", "invalid_source_rows", "outside_week_rows",
            "rejected_by_existing_shadow_guards", "truncated_weeks")},
        "candidate_counts": {key:int(c[key]) for key in (
            "candidate_threads", "candidate_rows",
            "multiple_comments_per_thread", "multiple_unverified_authors_in_thread",
            "single_token_topic_overlap", "seller_role_review_flags",
            "missing_file_context_noun_flags",
            "explicit_solution_request_machine_flags", "source_body_missing_flags",
            "review_priority_threads", "theme_access_control",
            "theme_sharing_sync", "theme_retrieval", "theme_unspecified")},
        "weekly_unique_candidate_threads": week_counts,
        "candidate_count_matches_prior_aggregate": c["candidate_threads"] == 8,
        "source_complete": counts["truncated_weeks"] == 0 and counts["outside_week_rows"] == 0,
        "interpretation": "NEEDS_INDEPENDENT_HUMAN_REVIEW",
    }


async def run() -> None:
    batches = []
    async with httpx.AsyncClient(
        timeout=20, follow_redirects=False, trust_env=False,
        headers={"User-Agent": "OXIBAY-IPD-FileAccess-Audit/1.0"},
    ) as client:
        for row in protocol():
            try:
                response = await client.get(hn.ENDPOINT, params={
                    "query": QUERY, "hitsPerPage": HITS_PER_QUERY,
                    "numericFilters": f"created_at_i>={row['start']},created_at_i<{row['end']}",
                })
                response.raise_for_status()
                payload = response.json()
                hits = payload.get("hits") if isinstance(payload, dict) else None
                if not isinstance(hits, list):
                    raise ValueError("invalid HN response")
                batches.append({"ok": True, "hits": hits[:HITS_PER_QUERY]})
            except (httpx.HTTPError, ValueError, TypeError):
                batches.append({"ok": False, "hits": []})
    aggregate = analyze(batches, secret=os.urandom(32))
    OUTPUT.write_text(json.dumps(aggregate, sort_keys=True, indent=2) + "\n")
    print(json.dumps(aggregate, sort_keys=True))


if __name__ == "__main__":
    if sys.argv[1:] == ["--execute"]:
        asyncio.run(run())
    elif not sys.argv[1:]:
        print(json.dumps({"mode":"PLAN_ONLY","calls":MAX_CALLS,
                          "privacy":"AGGREGATES_ONLY","production_state_write":False}))
    else:
        raise SystemExit("unsupported mode")
