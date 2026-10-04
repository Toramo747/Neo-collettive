# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Andrea Gava
"""Isolated evolutionary research arena for MYCELIX search-strategy discovery.

This arena evolves *shadow* research strategies only. It never writes production
state, never changes the commercial gate, and never promotes a genome directly.
External collaborators are untrusted A2A agents selected only from the public
task-verified registry pool. Their output may propose bounded gene mutations;
raw responses are never executed and are not persisted.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import html
import json
import math
import random
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from evidence_integrity import (
    buyer_voice_present,
    first_person_buyer_voice_present,
    commercial_family,
    demand_signal_type,
    is_vendor_content,
    is_supply_offer,
)

NAMESPACE = "mycelix-arena"
ARENA_ID = "mycelix-research-algorithm"
HN_ENDPOINT = "https://hn.algolia.com/api/v1/search_by_date"
A2A_REGISTRY = "https://a2aregistry.org"
STATE_PATH = "data/arena/research-algorithm/state.json"
REPORT_PATH = "data/arena/research-algorithm/latest.json"

POPULATION_SIZE = 8
ELITE_COUNT = 2
MAX_QUERIES_PER_GENOME = 4
MAX_HITS_PER_QUERY = 30
MAX_COLLABORATORS = 2
MIN_SUCCESSFUL_QUERIES = 6
STAGNATION_WINDOW = 3
IMMIGRANT_COUNT = 2

TOPICS = (
    "manual data entry",
    "invoice reconciliation",
    "security compliance evidence",
    "spreadsheet workflow",
)

QUERY_SUFFIXES = {
    "core": {
        "pain": ("pain", "problem", "frustrating", "tedious"),
        "buyer": ("pay for", "budget", "hire", "pricing"),
        "workaround": ("workaround", "manual", "script", "spreadsheet"),
        "mixed": ("problem", "pay for", "workaround", "manual"),
    },
    "intent": {
        "pain": ("issue", "blocking", "bottleneck", "annoying"),
        "buyer": ("vendor", "service", "tool", "subscription"),
        "workaround": ("automation", "macro", "integration", "template"),
        "mixed": ("issue", "tool", "automation", "workflow"),
    },
    "ops": {
        "pain": ("rework", "delay", "overhead", "failure"),
        "buyer": ("spend", "license", "contract", "consultant"),
        "workaround": ("api", "macro", "bot", "pipeline"),
        "mixed": ("delay", "license", "api", "pipeline"),
    },
}
TOPIC_SHAPES = {
    "exact": {
        "manual data entry": "manual data entry",
        "invoice reconciliation": "invoice reconciliation",
        "security compliance evidence": "security compliance evidence",
        "spreadsheet workflow": "spreadsheet workflow",
    },
    "compact": {
        "manual data entry": "data entry",
        "invoice reconciliation": "invoice reconcile",
        "security compliance evidence": "compliance evidence",
        "spreadsheet workflow": "spreadsheet process",
    },
}

PAIN_MARKERS = {
    "pain", "problem", "frustrating", "tedious", "annoying", "difficult",
    "waste", "slow", "broken", "hate", "struggle",
}
BUYER_MARKERS = {
    "pay", "paid", "budget", "pricing", "price", "cost", "hire", "buy",
    "purchase", "customer",
}
WORKAROUND_MARKERS = {
    "manual", "manually", "workaround", "script", "spreadsheet", "copy",
    "paste", "csv", "excel",
}

GENE_BOUNDS = {
    "query_count": (2, MAX_QUERIES_PER_GENOME),
    "recency_days": (7, 45),
    "min_relevance_tokens": (1, 3),
}
QUERY_MODES = ("pain", "buyer", "workaround", "mixed")
SUFFIX_FAMILIES = tuple(QUERY_SUFFIXES)
TOPIC_SHAPE_MODES = tuple(TOPIC_SHAPES)
QUERY_FRAMES = ("plain", "need", "looking_for")
TERM_ORDERS = ("topic_first", "signal_first")
SOURCE_SCOPES = ("comments", "stories", "all")

BOUNDARY = {
    "namespace": NAMESPACE,
    "arena_id": ARENA_ID,
    "production_state_write": False,
    "commercial_gate_influence": "NONE",
    "qualified_hits_influence": "NONE",
    "commercial_evidence_influence": "NONE",
    "search_provider_budget_influence": "NONE",
    "production_variant_promotion": False,
    "promotion": "MANUAL_REVIEW_ONLY",
    "external_agent_contact": True,
    "external_agent_scope": "task_verified_a2a_registry_only",
    "external_output_trust": "UNTRUSTED_BOUNDED_MUTATION_ONLY",
}


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def save_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def stable_seed(value: str) -> int:
    return int(hashlib.sha256(value.encode()).hexdigest()[:16], 16)


def clamp_genome(genome: dict[str, Any]) -> dict[str, Any]:
    out = {
        "query_mode": str(genome.get("query_mode") or "mixed"),
        "query_count": int(genome.get("query_count") or 3),
        "recency_days": int(genome.get("recency_days") or 21),
        "min_relevance_tokens": int(genome.get("min_relevance_tokens") or 1),
        "suffix_family": str(genome.get("suffix_family") or "core"),
        "topic_shape": str(genome.get("topic_shape") or "exact"),
        "query_frame": str(genome.get("query_frame") or "plain"),
        "term_order": str(genome.get("term_order") or "topic_first"),
        "source_scope": str(genome.get("source_scope") or "comments"),
    }
    if out["query_mode"] not in QUERY_MODES:
        out["query_mode"] = "mixed"
    if out["suffix_family"] not in SUFFIX_FAMILIES:
        out["suffix_family"] = "core"
    if out["topic_shape"] not in TOPIC_SHAPE_MODES:
        out["topic_shape"] = "exact"
    if out["query_frame"] not in QUERY_FRAMES:
        out["query_frame"] = "plain"
    if out["term_order"] not in TERM_ORDERS:
        out["term_order"] = "topic_first"
    if out["source_scope"] not in SOURCE_SCOPES:
        out["source_scope"] = "comments"
    for key, (lo, hi) in GENE_BOUNDS.items():
        out[key] = max(lo, min(hi, int(out[key])))
    return out


def initial_population() -> list[dict[str, Any]]:
    seeds = [
        {"query_mode": "pain", "query_count": 3, "recency_days": 14, "min_relevance_tokens": 1},
        {"query_mode": "buyer", "query_count": 3, "recency_days": 21, "min_relevance_tokens": 1},
        {"query_mode": "workaround", "query_count": 3, "recency_days": 30, "min_relevance_tokens": 1},
        {"query_mode": "mixed", "query_count": 4, "recency_days": 14, "min_relevance_tokens": 1},
        {"query_mode": "mixed", "query_count": 3, "recency_days": 30, "min_relevance_tokens": 2},
        {"query_mode": "pain", "query_count": 2, "recency_days": 45, "min_relevance_tokens": 2},
        {"query_mode": "buyer", "query_count": 4, "recency_days": 14, "min_relevance_tokens": 2},
        {"query_mode": "workaround", "query_count": 2, "recency_days": 21, "min_relevance_tokens": 3},
    ]
    return [
        {"genome_id": f"g0-{i+1}", "generation": 0, "genes": clamp_genome(g), "origin": "seed"}
        for i, g in enumerate(seeds)
    ]


def text_tokens(text: str) -> set[str]:
    return {
        t for t in re.findall(r"[a-z0-9]+", str(text or "").lower())
        if len(t) >= 3
    }


def clean_text(value: Any) -> str:
    raw = html.unescape(re.sub(r"<[^>]+>", " ", str(value or "")))
    return " ".join(raw.split())[:1600]


def build_queries(genome: dict[str, Any]) -> list[tuple[str, str]]:
    genes = clamp_genome(genome)
    suffixes = QUERY_SUFFIXES[genes["suffix_family"]][genes["query_mode"]][: genes["query_count"]]
    rows: list[tuple[str, str]] = []
    shape = TOPIC_SHAPES[genes["topic_shape"]]
    for topic in TOPICS:
        query_topic = shape[topic]
        for suffix in suffixes:
            parts = (query_topic, suffix) if genes["term_order"] == "topic_first" else (suffix, query_topic)
            query = " ".join(parts)
            if genes["query_frame"] == "need":
                query = "need " + query
            elif genes["query_frame"] == "looking_for":
                query = "looking for " + query
            rows.append((topic, query))
    return rows


async def fetch_hn_query(client: httpx.AsyncClient, topic: str, query: str, recency_days: int, source_scope: str = "comments") -> dict[str, Any]:
    cutoff = int(datetime.now(timezone.utc).timestamp()) - int(recency_days) * 86400
    try:
        params = {
            "query": query,
            "hitsPerPage": MAX_HITS_PER_QUERY,
            "numericFilters": f"created_at_i>{cutoff}",
        }
        if source_scope == "comments":
            params["tags"] = "comment"
        elif source_scope == "stories":
            params["tags"] = "story"
        response = await client.get(
            HN_ENDPOINT,
            params=params,
        )
        response.raise_for_status()
        payload = response.json()
        hits = payload.get("hits") if isinstance(payload, dict) else []
        return {"ok": True, "topic": topic, "query": query, "hits": hits if isinstance(hits, list) else []}
    except Exception as exc:
        return {"ok": False, "topic": topic, "query": query, "hits": [], "error": type(exc).__name__}


def evaluate_control_cases(cases: list[dict[str, Any]]) -> dict[str, Any]:
    total=0
    correct=0
    details=[]
    for case in cases or []:
        if not isinstance(case,dict):
            continue
        total += 1
        title=str(case.get("title") or "")
        body=str(case.get("body") or "")
        source=str(case.get("source") or "")
        url=str(case.get("url") or "")
        expect=case.get("expect") if isinstance(case.get("expect"),dict) else {}
        tags=demand_signal_type(title,body,query_role="buyer",seller_launch_guard=True,url=url,source=source,vendor_content_guard=True,web_buyer_voice_guard=True,supply_offer_guard=True)
        observed={
            "buyer":buyer_voice_present(title,body),
            "first_person":first_person_buyer_voice_present(title,body),
            "family":commercial_family((title+" "+body).lower()),
            "positive":bool({"PAIN","BUY_INTENT","PAID_DEMAND"} & set(tags)),
        }
        ok=all(observed.get(k)==v for k,v in expect.items())
        correct += int(ok)
        details.append({"id":str(case.get("id") or "")[:80],"ok":ok})
    return {"cases":total,"correct":correct,"accuracy":round(correct/max(1,total),4),"used_for_evolution":False,"raw_external_text":False,"details":details}

def score_hits(genome: dict[str, Any], query_rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Score with the same buyer/demand primitives used by production."""
    genes = clamp_genome(genome)
    total_hits = 0
    relevant_hits = 0
    signal_hits = 0
    buyer_hits = 0
    first_person_buyer_hits = 0
    family_hits = 0
    vendor_rejected = 0
    supply_rejected = 0
    unique_threads: set[str] = set()

    for row in query_rows:
        topic_tokens = text_tokens(row.get("topic") or "")
        query = str(row.get("query") or "")
        for hit in row.get("hits") or []:
            if not isinstance(hit, dict):
                continue
            total_hits += 1
            title = clean_text(hit.get("title") or hit.get("story_title") or "")
            body = clean_text(hit.get("comment_text") or hit.get("story_text") or "")
            text = clean_text((title + " " + body).strip())
            tokens = text_tokens(text)
            if len(topic_tokens & tokens) < genes["min_relevance_tokens"]:
                continue
            relevant_hits += 1

            url = str(hit.get("url") or hit.get("story_url") or "")
            source = "hn-algolia-routed"
            vendor = is_vendor_content(title, body, url, source)
            supply = is_supply_offer(title, body, url, source)
            if vendor:
                vendor_rejected += 1
                continue
            if supply:
                supply_rejected += 1
                continue

            family = commercial_family(text)
            family_ok = family != "other"
            buyer = buyer_voice_present(title, body)
            first_person = first_person_buyer_voice_present(title, body)
            tags = demand_signal_type(
                title,
                body,
                query_role="buyer",
                strong_pain_only=False,
                seller_launch_guard=True,
                url=url,
                source=source,
                vendor_content_guard=True,
                web_buyer_voice_guard=True,
                supply_offer_guard=True,
                query_echo_guard=True,
                query=query,
            )
            positive = any(tag in {"PAIN","BUY_INTENT","PAID_DEMAND"} for tag in tags)

            family_hits += int(family_ok)
            buyer_hits += int(buyer)
            first_person_buyer_hits += int(first_person)
            if family_ok and buyer and positive:
                signal_hits += 1
                sid = str(hit.get("story_id") or hit.get("objectID") or "")
                if sid:
                    unique_threads.add(sid)

    production_precision = signal_hits / max(1, relevant_hits)
    family_match_rate = family_hits / max(1, relevant_hits)
    buyer_rate = buyer_hits / max(1, relevant_hits)
    first_person_rate = first_person_buyer_hits / max(1, relevant_hits)
    independent = min(len(unique_threads), 12) / 12.0
    support_relevant = min(relevant_hits, 6) / 6.0
    support_independent = min(len(unique_threads), 3) / 3.0
    support_factor = 0.5 * support_relevant + 0.5 * support_independent
    penalty = min(0.5, (vendor_rejected + supply_rejected) / max(1, relevant_hits))
    base_fitness = (
        production_precision * 45.0
        + buyer_rate * 20.0
        + first_person_rate * 10.0
        + family_match_rate * 10.0
        + independent * 15.0
    ) * (1.0 - penalty)
    fitness = base_fitness * support_factor
    return {
        "fitness": round(fitness, 4),
        "base_fitness": round(base_fitness, 4),
        "support_factor": round(support_factor, 4),
        "total_hits": total_hits,
        "relevant_hits": relevant_hits,
        "signal_hits": signal_hits,
        "unique_signal_threads": len(unique_threads),
        "buyer_hits": buyer_hits,
        "first_person_buyer_hits": first_person_buyer_hits,
        "family_hits": family_hits,
        "family_match_rate": round(family_match_rate, 4),
        "buyer_rate": round(buyer_rate, 4),
        "first_person_buyer_rate": round(first_person_rate, 4),
        "precision": round(production_precision, 4),
        "vendor_rejected": vendor_rejected,
        "supply_rejected": supply_rejected,
    }

async def evaluate_genome(client: httpx.AsyncClient, item: dict[str, Any]) -> dict[str, Any]:
    genes = clamp_genome(item.get("genes") or {})
    tasks = [
        fetch_hn_query(client, topic, query, genes["recency_days"], genes["source_scope"])
        for topic, query in build_queries(genes)
    ]
    rows = await asyncio.gather(*tasks)
    successful = sum(1 for x in rows if x.get("ok"))
    metrics = score_hits(genes, rows)
    metrics["successful_queries"] = successful
    metrics["failed_queries"] = len(rows) - successful
    return {**item, "genes": genes, "metrics": metrics}


def mutate(parent: dict[str, Any], rng: random.Random, generation: int, suffix: str) -> dict[str, Any]:
    genes = dict(clamp_genome(parent.get("genes") or {}))
    key = rng.choice(["query_mode", "query_count", "recency_days", "min_relevance_tokens", "suffix_family", "topic_shape", "query_frame", "term_order", "source_scope"])
    if key == "query_mode":
        genes[key] = rng.choice([x for x in QUERY_MODES if x != genes[key]])
    elif key == "query_count":
        genes[key] += rng.choice([-1, 1])
    elif key == "recency_days":
        genes[key] += rng.choice([-7, 7, 14])
    elif key == "suffix_family":
        genes[key] = rng.choice([x for x in SUFFIX_FAMILIES if x != genes[key]])
    elif key == "topic_shape":
        genes[key] = rng.choice([x for x in TOPIC_SHAPE_MODES if x != genes[key]])
    elif key == "query_frame":
        genes[key] = rng.choice([x for x in QUERY_FRAMES if x != genes[key]])
    elif key == "term_order":
        genes[key] = rng.choice([x for x in TERM_ORDERS if x != genes[key]])
    elif key == "source_scope":
        genes[key] = rng.choice([x for x in SOURCE_SCOPES if x != genes[key]])
    else:
        genes[key] += rng.choice([-1, 1])
    return {
        "genome_id": f"g{generation}-{suffix}",
        "generation": generation,
        "genes": clamp_genome(genes),
        "origin": "mutation",
        "parent_id": parent.get("genome_id"),
    }


def genome_key(item: dict[str, Any]) -> tuple:
    genes = clamp_genome(item.get("genes") or {})
    return (
        genes["query_mode"],
        genes["query_count"],
        genes["recency_days"],
        genes["min_relevance_tokens"],
        genes["suffix_family"],
        genes["topic_shape"],
        genes["query_frame"],
        genes["term_order"],
        genes["source_scope"],
    )


def diversify_mutation(parent: dict[str, Any], rng: random.Random, generation: int, suffix: str) -> dict[str, Any]:
    genes = dict(clamp_genome(parent.get("genes") or {}))
    keys = ["query_mode", "query_count", "recency_days", "min_relevance_tokens", "suffix_family", "topic_shape", "query_frame", "term_order", "source_scope"]
    for key in rng.sample(keys, k=2):
        if key == "query_mode":
            genes[key] = rng.choice([x for x in QUERY_MODES if x != genes[key]])
        elif key == "query_count":
            genes[key] += rng.choice([-1, 1])
        elif key == "recency_days":
            genes[key] += rng.choice([-14, -7, 7, 14])
        elif key == "suffix_family":
            genes[key] = rng.choice([x for x in SUFFIX_FAMILIES if x != genes[key]])
        elif key == "topic_shape":
            genes[key] = rng.choice([x for x in TOPIC_SHAPE_MODES if x != genes[key]])
        elif key == "query_frame":
            genes[key] = rng.choice([x for x in QUERY_FRAMES if x != genes[key]])
        elif key == "term_order":
            genes[key] = rng.choice([x for x in TERM_ORDERS if x != genes[key]])
        elif key == "source_scope":
            genes[key] = rng.choice([x for x in SOURCE_SCOPES if x != genes[key]])
        else:
            genes[key] += rng.choice([-1, 1])
    return {
        "genome_id": f"g{generation}-{suffix}",
        "generation": generation,
        "genes": clamp_genome(genes),
        "origin": "diversify_mutation",
        "parent_id": parent.get("genome_id"),
    }


def random_immigrant(rng: random.Random, generation: int, suffix: str) -> dict[str, Any]:
    genes = {
        "query_mode": rng.choice(list(QUERY_MODES)),
        "query_count": rng.randint(*GENE_BOUNDS["query_count"]),
        "recency_days": rng.randint(*GENE_BOUNDS["recency_days"]),
        "min_relevance_tokens": rng.randint(*GENE_BOUNDS["min_relevance_tokens"]),
        "suffix_family": rng.choice(list(SUFFIX_FAMILIES)),
        "topic_shape": rng.choice(list(TOPIC_SHAPE_MODES)),
        "query_frame": rng.choice(list(QUERY_FRAMES)),
        "term_order": rng.choice(list(TERM_ORDERS)),
        "source_scope": rng.choice(list(SOURCE_SCOPES)),
    }
    return {
        "genome_id": f"g{generation}-{suffix}",
        "generation": generation,
        "genes": clamp_genome(genes),
        "origin": "random_immigrant",
        "parent_id": None,
    }


def stagnating(history: list[dict[str, Any]]) -> bool:
    rows=[x for x in history[-STAGNATION_WINDOW:] if isinstance(x,dict)]
    if len(rows) < STAGNATION_WINDOW:
        return False
    vals=[float(x.get("champion_fitness") or 0.0) for x in rows]
    return max(vals)-min(vals) < 0.001


def crossover(a: dict[str, Any], b: dict[str, Any], rng: random.Random, generation: int, suffix: str) -> dict[str, Any]:
    ga, gb = clamp_genome(a.get("genes") or {}), clamp_genome(b.get("genes") or {})
    genes = {k: rng.choice([ga[k], gb[k]]) for k in ga}
    return {
        "genome_id": f"g{generation}-{suffix}",
        "generation": generation,
        "genes": clamp_genome(genes),
        "origin": "crossover",
        "parent_id": [a.get("genome_id"), b.get("genome_id")],
    }


def recursive_text(value: Any, depth: int = 0) -> list[str]:
    if depth > 5:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        out: list[str] = []
        for item in value[:20]:
            out.extend(recursive_text(item, depth + 1))
        return out
    if isinstance(value, dict):
        out: list[str] = []
        for item in list(value.values())[:30]:
            out.extend(recursive_text(item, depth + 1))
        return out
    return []


def parse_mutation(value: Any) -> dict[str, Any] | None:
    candidates: list[Any] = []
    if isinstance(value, dict):
        candidates.append(value)
    for text in recursive_text(value):
        text = text.strip()
        if len(text) > 4000:
            text = text[:4000]
        try:
            candidates.append(json.loads(text))
        except Exception:
            match = re.search(r"\{[^{}]{1,1200}\}", text, re.S)
            if match:
                try:
                    candidates.append(json.loads(match.group(0)))
                except Exception:
                    pass
    for row in candidates:
        if not isinstance(row, dict):
            continue
        raw = row.get("mutation") if isinstance(row.get("mutation"), dict) else row
        if not isinstance(raw, dict):
            continue
        allowed = {k: raw[k] for k in ("query_mode", "query_count", "recency_days", "min_relevance_tokens", "suffix_family", "topic_shape", "query_frame", "term_order", "source_scope") if k in raw}
        if allowed:
            bounded = {}
            if "query_mode" in allowed:
                mode = str(allowed["query_mode"])
                if mode in QUERY_MODES:
                    bounded["query_mode"] = mode
            if "suffix_family" in allowed:
                family = str(allowed["suffix_family"])
                if family in SUFFIX_FAMILIES:
                    bounded["suffix_family"] = family
            if "topic_shape" in allowed:
                shape = str(allowed["topic_shape"])
                if shape in TOPIC_SHAPE_MODES:
                    bounded["topic_shape"] = shape
            if "query_frame" in allowed:
                frame = str(allowed["query_frame"])
                if frame in QUERY_FRAMES:
                    bounded["query_frame"] = frame
            if "term_order" in allowed:
                order = str(allowed["term_order"])
                if order in TERM_ORDERS:
                    bounded["term_order"] = order
            if "source_scope" in allowed:
                scope = str(allowed["source_scope"])
                if scope in SOURCE_SCOPES:
                    bounded["source_scope"] = scope
            for key in ("query_count", "recency_days", "min_relevance_tokens"):
                if key not in allowed:
                    continue
                lo, hi = GENE_BOUNDS[key]
                try:
                    bounded[key] = max(lo, min(hi, int(allowed[key])))
                except Exception:
                    continue
            return bounded or None
    return None


def candidate_score(agent: dict[str, Any]) -> int:
    text = " ".join([
        str(agent.get("name") or ""),
        str(agent.get("description") or ""),
        json.dumps(agent.get("skills") or [], ensure_ascii=False),
    ]).lower()
    score = sum(3 for marker in ("research", "analysis", "market", "business", "evidence", "search") if marker in text)
    task = agent.get("task_conformance") or {}
    if isinstance(task, dict) and task.get("category") == "WORKING":
        score += 8
    if agent.get("is_healthy") is True:
        score += 3
    if agent.get("conformance") is True:
        score += 2
    return score


async def collaborator_mutations(
    client: httpx.AsyncClient,
    champion: dict[str, Any],
    generation: int,
    explicit_candidate_id: str = "",
) -> list[dict[str, Any]]:
    try:
        response = await client.get(
            A2A_REGISTRY + "/api/agents",
            params={"task_verified": "true", "limit": 20},
        )
        response.raise_for_status()
        payload = response.json()
        agents = payload.get("agents") if isinstance(payload, dict) else payload
        agents = [x for x in (agents or []) if isinstance(x, dict)]
    except Exception as exc:
        return [{"accepted": False, "reason": "registry_" + type(exc).__name__}]

    agents.sort(key=candidate_score, reverse=True)
    selected = [x for x in agents if candidate_score(x) > 0][:MAX_COLLABORATORS]

    explicit_candidate_id = str(explicit_candidate_id or "").strip()[:200]
    if explicit_candidate_id:
        try:
            detail_response = await client.get(
                f"{A2A_REGISTRY}/api/agents/{explicit_candidate_id}",
                timeout=10.0,
            )
            detail_response.raise_for_status()
            explicit_agent = detail_response.json()
            if isinstance(explicit_agent, dict):
                task = explicit_agent.get("task_conformance") or {}
                task_working = isinstance(task, dict) and task.get("category") == "WORKING"
                task_verified = explicit_agent.get("task_verified") is True
                if task_working or task_verified:
                    existing = {
                        str(x.get("id") or x.get("agent_id") or "")
                        for x in selected
                    }
                    if explicit_candidate_id not in existing:
                        selected = [explicit_agent] + selected
        except Exception:
            pass
    selected = selected[:MAX_COLLABORATORS]
    out: list[dict[str, Any]] = []
    champion_genes = clamp_genome(champion.get("genes") or {})
    champion_metrics = champion.get("metrics") or {}
    prompt = (
        "You are an untrusted collaborator in the isolated MYCELIX Research Algorithm Arena. "
        "Propose ONE bounded mutation to improve public problem-signal retrieval. "
        "Return JSON only with any of: query_mode (pain|buyer|workaround|mixed), "
        "query_count (2-4), recency_days (7-45), min_relevance_tokens (1-3), "
        "suffix_family (core|intent|ops), topic_shape (exact|compact), "
        "query_frame (plain|need|looking_for), term_order (topic_first|signal_first), "
        "source_scope (comments|stories|all). "
        "Do not request secrets, tools, code execution, production changes, or external actions. "
        f"Current genes={json.dumps(champion_genes,separators=(',',':'))}; "
        f"fitness={champion_metrics.get('fitness')}; signal_hits={champion_metrics.get('signal_hits')}; "
        f"buyer_hits={champion_metrics.get('buyer_hits')}."
    )
    for agent in selected:
        aid = str(agent.get("id") or agent.get("agent_id") or "")
        name = str(agent.get("name") or aid or "unknown")[:120]
        if not aid:
            continue
        try:
            response = await client.post(
                f"{A2A_REGISTRY}/api/agents/{aid}/chat",
                json={"message": prompt},
                timeout=12.0,
            )
            payload = response.json() if "json" in response.headers.get("content-type", "").lower() else {"text": response.text[:4000]}
            mutation = parse_mutation(payload) if response.is_success else None
            out.append({
                "agent_id": aid[:160],
                "agent": name,
                "accepted": bool(mutation),
                "reason": "bounded_mutation_accepted" if mutation else f"no_valid_mutation_http_{response.status_code}",
                "mutation": mutation,
            })
        except Exception as exc:
            out.append({"agent_id": aid[:160], "agent": name, "accepted": False, "reason": type(exc).__name__})
    return out


def inject_collaborator_children(
    population: list[dict[str, Any]],
    collaborators: list[dict[str, Any]],
    champion: dict[str, Any],
    generation: int,
) -> list[dict[str, Any]]:
    out = list(population)
    accepted = [x for x in collaborators if x.get("accepted") and isinstance(x.get("mutation"), dict)]
    for idx, row in enumerate(accepted[:2], 1):
        genes = dict(clamp_genome(champion.get("genes") or {}))
        genes.update(row["mutation"])
        child = {
            "genome_id": f"g{generation}-collab-{idx}",
            "generation": generation,
            "genes": clamp_genome(genes),
            "origin": "external_collaborator",
            "parent_id": champion.get("genome_id"),
            "collaborator_agent_id": row.get("agent_id"),
        }
        if len(out) < POPULATION_SIZE:
            out.append(child)
        else:
            out[-idx] = child
    return out[:POPULATION_SIZE]


async def run(data_dir: Path, explicit_candidate_id: str = "") -> dict[str, Any]:
    state_path = data_dir / "research-algorithm" / "state.json"
    report_path = data_dir / "research-algorithm" / "latest.json"
    state = load_json(state_path, {})
    control_data=load_json(data_dir / "research-algorithm" / "control_cases.json", {})
    control_metrics=evaluate_control_cases(control_data.get("cases") or [])
    generation = int(state.get("generation") or 0)
    population = state.get("population") if isinstance(state.get("population"), list) else initial_population()
    if not population:
        population = initial_population()

    async with httpx.AsyncClient(
        timeout=10.0,
        headers={"User-Agent": "MYCELIX-Research-Arena/1.0"},
        follow_redirects=False,
        trust_env=False,
    ) as client:
        evaluated = await asyncio.gather(*(evaluate_genome(client, x) for x in population))
        successful_queries = sum(int((x.get("metrics") or {}).get("successful_queries") or 0) for x in evaluated)
        measured = successful_queries >= MIN_SUCCESSFUL_QUERIES
        ranked = sorted(evaluated, key=lambda x: float((x.get("metrics") or {}).get("fitness") or 0), reverse=True)
        champion = ranked[0] if ranked else population[0]
        collaborators = (
            await collaborator_mutations(client, champion, generation + 1, explicit_candidate_id)
            if measured else []
        )

    next_population = list(population)
    next_generation = generation
    evolution_status = "NO_MEASUREMENT"
    if measured and ranked:
        next_generation = generation + 1
        rng = random.Random(stable_seed(f"{next_generation}|{champion.get('genome_id')}"))
        elites = [
            {
                "genome_id": f"g{next_generation}-elite-{i+1}",
                "generation": next_generation,
                "genes": clamp_genome(x.get("genes") or {}),
                "origin": "elite",
                "parent_id": x.get("genome_id"),
            }
            for i, x in enumerate(ranked[:ELITE_COUNT])
        ]
        children = list(elites)
        history_so_far = list(state.get("history") or [])
        force_diversity = stagnating(history_so_far)
        seen = {genome_key(x) for x in children}
        attempts = 0
        while len(children) < POPULATION_SIZE and attempts < 64:
            attempts += 1
            suffix=str(len(children)+1)
            if force_diversity and len(children) < ELITE_COUNT + IMMIGRANT_COUNT:
                child = random_immigrant(rng, next_generation, suffix)
            elif force_diversity:
                child = diversify_mutation(
                    ranked[len(children) % min(ELITE_COUNT, len(ranked))],
                    rng,
                    next_generation,
                    suffix,
                )
            elif len(ranked) >= 2 and len(children) % 2 == 0:
                child = crossover(ranked[0], ranked[1], rng, next_generation, suffix)
            else:
                child = mutate(
                    ranked[len(children) % min(ELITE_COUNT, len(ranked))],
                    rng,
                    next_generation,
                    suffix,
                )
            key = genome_key(child)
            if key in seen:
                child = random_immigrant(rng, next_generation, suffix)
                key = genome_key(child)
            if key in seen:
                continue
            seen.add(key)
            children.append(child)
        while len(children) < POPULATION_SIZE:
            children.append(random_immigrant(rng, next_generation, str(len(children)+1)))
        next_population = inject_collaborator_children(children[:POPULATION_SIZE], collaborators, champion, next_generation)
        evolution_status = "EVOLVED_DIVERSITY" if force_diversity else "EVOLVED"

    history = list(state.get("history") or [])
    history.append({
        "generation": generation,
        "measured_at_utc": now_utc(),
        "status": evolution_status,
        "champion_genome_id": champion.get("genome_id"),
        "champion_fitness": (champion.get("metrics") or {}).get("fitness"),
        "successful_queries": successful_queries,
    })
    history = history[-80:]

    next_state = {
        "schema_v": 1,
        "namespace": NAMESPACE,
        "arena_id": ARENA_ID,
        "generation": next_generation,
        "population": next_population,
        "history": history,
        "boundary": dict(BOUNDARY),
        "promotion_candidate": {
            "genome_id": champion.get("genome_id"),
            "genes": clamp_genome(champion.get("genes") or {}),
            "fitness": (champion.get("metrics") or {}).get("fitness"),
            "manual_review_required": True,
            "production_promoted": False,
        },
    }
    report = {
        "schema_v": 1,
        "namespace": NAMESPACE,
        "arena_id": ARENA_ID,
        "captured_at_utc": now_utc(),
        "status": evolution_status,
        "evaluated_generation": generation,
        "next_generation": next_generation,
        "benchmark": {
            "provider": "hn_algolia_public_read_only",
            "topics": list(TOPICS),
            "successful_queries": successful_queries,
            "minimum_successful_queries": MIN_SUCCESSFUL_QUERIES,
            "raw_text_persisted": False,
            "population_size": POPULATION_SIZE,
            "stagnation_window": STAGNATION_WINDOW,
            "diversity_boost_enabled": True,
        },
        "ranked": [
            {
                "genome_id": x.get("genome_id"),
                "genes": clamp_genome(x.get("genes") or {}),
                "origin": x.get("origin"),
                "metrics": x.get("metrics") or {},
            }
            for x in ranked
        ],
        "collaborators": collaborators,
        "control_metrics": control_metrics,
        "promotion_candidate": next_state["promotion_candidate"],
        "boundary": dict(BOUNDARY),
    }
    save_json(state_path, next_state)
    save_json(report_path, report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", default="data/arena")
    parser.add_argument("--candidate-agent-id", default="")
    args = parser.parse_args()
    report = asyncio.run(run(Path(args.data_dir), args.candidate_agent_id))
    print(json.dumps({
        "ok": True,
        "status": report["status"],
        "evaluated_generation": report["evaluated_generation"],
        "next_generation": report["next_generation"],
        "champion": report["promotion_candidate"],
        "collaborators": report["collaborators"],
        "boundary": report["boundary"],
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
