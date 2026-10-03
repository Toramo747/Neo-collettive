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

NAMESPACE = "mycelix-arena"
ARENA_ID = "mycelix-research-algorithm"
HN_ENDPOINT = "https://hn.algolia.com/api/v1/search_by_date"
A2A_REGISTRY = "https://a2aregistry.org"
STATE_PATH = "data/arena/research-algorithm/state.json"
REPORT_PATH = "data/arena/research-algorithm/latest.json"

POPULATION_SIZE = 6
ELITE_COUNT = 2
MAX_QUERIES_PER_GENOME = 4
MAX_HITS_PER_QUERY = 30
MAX_COLLABORATORS = 2
MIN_SUCCESSFUL_QUERIES = 6

TOPICS = (
    "manual data entry",
    "invoice reconciliation",
    "security compliance evidence",
    "spreadsheet workflow",
)

QUERY_SUFFIXES = {
    "pain": ("pain", "problem", "frustrating", "tedious"),
    "buyer": ("pay for", "budget", "hire", "pricing"),
    "workaround": ("workaround", "manual", "script", "spreadsheet"),
    "mixed": ("problem", "pay for", "workaround", "manual"),
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
QUERY_MODES = tuple(QUERY_SUFFIXES)

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
    }
    if out["query_mode"] not in QUERY_MODES:
        out["query_mode"] = "mixed"
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
    suffixes = QUERY_SUFFIXES[genes["query_mode"]][: genes["query_count"]]
    rows: list[tuple[str, str]] = []
    for topic in TOPICS:
        for suffix in suffixes:
            rows.append((topic, f"{topic} {suffix}"))
    return rows


async def fetch_hn_query(client: httpx.AsyncClient, topic: str, query: str, recency_days: int) -> dict[str, Any]:
    cutoff = int(datetime.now(timezone.utc).timestamp()) - int(recency_days) * 86400
    try:
        response = await client.get(
            HN_ENDPOINT,
            params={
                "query": query,
                "tags": "comment",
                "hitsPerPage": MAX_HITS_PER_QUERY,
                "numericFilters": f"created_at_i>{cutoff}",
            },
        )
        response.raise_for_status()
        payload = response.json()
        hits = payload.get("hits") if isinstance(payload, dict) else []
        return {"ok": True, "topic": topic, "query": query, "hits": hits if isinstance(hits, list) else []}
    except Exception as exc:
        return {"ok": False, "topic": topic, "query": query, "hits": [], "error": type(exc).__name__}


def score_hits(genome: dict[str, Any], query_rows: list[dict[str, Any]]) -> dict[str, Any]:
    genes = clamp_genome(genome)
    total_hits = 0
    relevant_hits = 0
    signal_hits = 0
    pain_hits = 0
    buyer_hits = 0
    workaround_hits = 0
    unique_threads: set[str] = set()

    for row in query_rows:
        topic_tokens = text_tokens(row.get("topic") or "")
        for hit in row.get("hits") or []:
            if not isinstance(hit, dict):
                continue
            total_hits += 1
            text = clean_text(hit.get("comment_text") or hit.get("story_text") or hit.get("title") or "")
            tokens = text_tokens(text)
            overlap = len(topic_tokens & tokens)
            if overlap < genes["min_relevance_tokens"]:
                continue
            relevant_hits += 1
            pain = bool(tokens & PAIN_MARKERS)
            buyer = bool(tokens & BUYER_MARKERS)
            workaround = bool(tokens & WORKAROUND_MARKERS)
            pain_hits += int(pain)
            buyer_hits += int(buyer)
            workaround_hits += int(workaround)
            if pain or buyer or workaround:
                signal_hits += 1
                sid = str(hit.get("story_id") or hit.get("objectID") or "")
                if sid:
                    unique_threads.add(sid)

    precision = signal_hits / max(1, relevant_hits)
    relevance_rate = relevant_hits / max(1, total_hits)
    independent = min(len(unique_threads), 15) / 15.0
    buyer_component = min(buyer_hits, 5) / 5.0
    pain_component = min(pain_hits, 10) / 10.0
    workaround_component = min(workaround_hits, 8) / 8.0
    fitness = (
        precision * 35.0
        + relevance_rate * 15.0
        + independent * 20.0
        + buyer_component * 10.0
        + pain_component * 10.0
        + workaround_component * 10.0
    )
    return {
        "fitness": round(fitness, 4),
        "total_hits": total_hits,
        "relevant_hits": relevant_hits,
        "signal_hits": signal_hits,
        "unique_signal_threads": len(unique_threads),
        "pain_hits": pain_hits,
        "buyer_hits": buyer_hits,
        "workaround_hits": workaround_hits,
        "precision": round(precision, 4),
        "relevance_rate": round(relevance_rate, 4),
    }


async def evaluate_genome(client: httpx.AsyncClient, item: dict[str, Any]) -> dict[str, Any]:
    genes = clamp_genome(item.get("genes") or {})
    tasks = [
        fetch_hn_query(client, topic, query, genes["recency_days"])
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
    key = rng.choice(["query_mode", "query_count", "recency_days", "min_relevance_tokens"])
    if key == "query_mode":
        genes[key] = rng.choice([x for x in QUERY_MODES if x != genes[key]])
    elif key == "query_count":
        genes[key] += rng.choice([-1, 1])
    elif key == "recency_days":
        genes[key] += rng.choice([-7, 7, 14])
    else:
        genes[key] += rng.choice([-1, 1])
    return {
        "genome_id": f"g{generation}-{suffix}",
        "generation": generation,
        "genes": clamp_genome(genes),
        "origin": "mutation",
        "parent_id": parent.get("genome_id"),
    }


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
        allowed = {k: raw[k] for k in ("query_mode", "query_count", "recency_days", "min_relevance_tokens") if k in raw}
        if allowed:
            bounded = {}
            if "query_mode" in allowed:
                mode = str(allowed["query_mode"])
                if mode in QUERY_MODES:
                    bounded["query_mode"] = mode
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
        "query_count (2-4), recency_days (7-45), min_relevance_tokens (1-3). "
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
        while len(children) < POPULATION_SIZE:
            if len(ranked) >= 2 and len(children) % 2 == 0:
                children.append(crossover(ranked[0], ranked[1], rng, next_generation, str(len(children)+1)))
            else:
                children.append(mutate(ranked[len(children) % min(ELITE_COUNT, len(ranked))], rng, next_generation, str(len(children)+1)))
        next_population = inject_collaborator_children(children[:POPULATION_SIZE], collaborators, champion, next_generation)
        evolution_status = "EVOLVED"

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
