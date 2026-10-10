"""Bounded HN research coverage observation; no commercial evidence or gate effect.

A single public search probes whether the existing few-hit retrieval limit
may hide query-relevant discussion threads. No source text, URLs, IDs or
requester identities are retained in the returned aggregate.
"""
from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

import httpx
from discovery_v3 import query_relevance

HN_ENDPOINT = "https://hn.algolia.com/api/v1/search_by_date"
SAMPLE_CAP = 60
BASELINE_CAP = 3
PROBE_TIMEOUT = 7.0


def empty_coverage(status: str = "NOT_MEASURED") -> dict[str, Any]:
    if status not in {"NOT_MEASURED", "NO_QUERY", "PROVIDER_ERROR", "TIMEOUT", "INVALID_PAYLOAD"}:
        status = "INVALID_PAYLOAD"
    return {
        "schema_v": 1, "mode": "shadow_only", "provider": "hn_algolia_public",
        "status": status, "sample_cap": SAMPLE_CAP, "baseline_cap": BASELINE_CAP,
        "received": 0, "provider_reported_matches": None,
        "provider_exhaustive": False, "source_complete": False,
        "relevant_first_baseline": 0, "relevant_in_sample": 0,
        "additional_relevant_in_sample": 0,
        "commercial_gate_influence": "NONE", "automatic_promotion": False,
        "verified_independent_buyers": 0, "raw_content_persisted": False,
    }


def assess_public_hn_coverage(
    payload: dict | None,
    search_seed: str,
    *,
    sample_cap: int = SAMPLE_CAP,
    baseline_cap: int = BASELINE_CAP,
) -> dict[str, Any]:
    """Machine relevance counts, *not* demand/buyer or growth validation."""
    if not isinstance(payload, dict) or not isinstance(payload.get("hits"), list):
        return empty_coverage("INVALID_PAYLOAD")
    if not isinstance(sample_cap, int) or not 1 <= sample_cap <= SAMPLE_CAP:
        raise ValueError("sample cap outside frozen read-only budget")
    if not isinstance(baseline_cap, int) or not 1 <= baseline_cap <= sample_cap:
        raise ValueError("invalid baseline")
    hits = payload["hits"]
    if len(hits) > sample_cap or any(not isinstance(hit, dict) for hit in hits):
        return empty_coverage("INVALID_PAYLOAD")
    reported = payload.get("nbHits")
    if isinstance(reported, bool) or not isinstance(reported, int) or reported < len(hits):
        reported = None
    exhaustive = payload.get("exhaustiveNbHits") is True
    # HN total match counts can be approximate even if the returned set is
    # smaller than the requested limit; never infer completeness from len().
    complete = bool(exhaustive and reported is not None and reported == len(hits))

    first, all_sample = set(), set()
    for i, item in enumerate(hits):
        object_id = str(item.get("objectID") or "")
        thread_id = str(item.get("story_id") or object_id)
        if not object_id or not thread_id:
            continue
        title = str(item.get("title") or item.get("story_title") or "")[:400]
        body = str(item.get("comment_text") or item.get("story_text") or "")[:2000]
        if not query_relevance(title, body, search_seed, {
            "search_alias_used": search_seed,
        }).get("relevant"):
            continue
        all_sample.add(thread_id)
        if i < baseline_cap:
            first.add(thread_id)

    base = empty_coverage()
    base.update({
        "status": "OBSERVED_COMPLETE" if complete else
                  "OBSERVED_INCOMPLETE" if reported is not None else "UNKNOWN_COVERAGE",
        "sample_cap": sample_cap, "baseline_cap": baseline_cap,
        "received": len(hits), "provider_reported_matches": reported,
        "provider_exhaustive": exhaustive, "source_complete": complete,
        "relevant_first_baseline": len(first),
        "relevant_in_sample": len(all_sample),
        "additional_relevant_in_sample": len(all_sample - first),
    })
    return base


async def probe_public_hn_coverage(
    search_seed: str,
    *,
    http_get: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    """Exactly one public request, with a bounded request and timeout."""
    seed = " ".join(str(search_seed or "").split())[:180]
    if not seed:
        return empty_coverage("NO_QUERY")
    params = {"query": seed, "hitsPerPage": SAMPLE_CAP}
    if http_get is not None:
        try:
            data = await asyncio.wait_for(http_get(HN_ENDPOINT, params), timeout=PROBE_TIMEOUT)
            return assess_public_hn_coverage(data, seed)
        except asyncio.TimeoutError:
            return empty_coverage("TIMEOUT")
        except Exception:
            return empty_coverage("PROVIDER_ERROR")
    try:
        async with httpx.AsyncClient(
            timeout=PROBE_TIMEOUT, follow_redirects=False, trust_env=False,
            headers={"User-Agent": "OSIXBAY-DemandCoverage-Shadow/1.0"},
        ) as client:
            response = await client.get(HN_ENDPOINT, params=params)
            response.raise_for_status()
            data = response.json()
        return assess_public_hn_coverage(data, seed)
    except httpx.TimeoutException:
        return empty_coverage("TIMEOUT")
    except (httpx.HTTPError, TypeError, ValueError):
        return empty_coverage("PROVIDER_ERROR")
