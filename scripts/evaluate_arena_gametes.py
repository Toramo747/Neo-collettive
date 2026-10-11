# SPDX-License-Identifier: BUSL-1.1
"""Offline-only evaluation harness for the ten bounded Arena gametes.

No live provider, model, registry call, Arena state write or production mutation.
Only standard Arena scoring/validation functions and the last committed reports.
A proxy score is NOT evidence of improved external results.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from arena_collective_mind import (
    _quality_guard_accepts,
    genome_fitness,
    load_routing_memory,
    load_score_genome,
    quality_guard_fitness,
    routing_genome_fitness,
    select_quality_guard,
    select_routing_genome,
)
from arena_llm_guided_search import make_mutation_prompt
from arena_research_algorithm import build_queries, clamp_genome
from arena_warp_propulsion import Candidate, score_candidate
from warp_physics import evaluate_candidate, reference_checks

PACK_PATH = ROOT / "data/arena/gametes/seed-2026-10-09.json"
DATA_DIR = ROOT / "data/arena"
REQUIRED = {"collective-mind": 4, "llm-guided-search": 3, "warp-propulsion": 2, "research-algorithm": 1}
KINDS = {
    "collective-mind": {"routing", "quality_guard", "score_genome"},
    "llm-guided-search": {"prompt_mutation"},
    "warp-propulsion": {"theoretical_candidate"},
    "research-algorithm": {"query_genome"},
}


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("expected an object: " + path.name)
    return value


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def require_isolation(pack: dict[str, Any]) -> None:
    if pack.get("status") != "SHADOW_CANDIDATES_NOT_VALIDATED":
        raise ValueError("candidate pack is not shadow-only")
    b = pack.get("boundary") or {}
    if b.get("arena_only") is not True or b.get("manual_review_required") is not True:
        raise ValueError("missing manual-review boundary")
    for key in ("network_calls", "external_agent_contact", "production_state_write",
                "automatic_promotion", "paid_provider_calls", "personal_data_included"):
        if b.get(key) is not False:
            raise ValueError("forbidden capability: " + key)
    for key in ("commercial_gate_influence", "commercial_evidence_influence"):
        if b.get(key) != "NONE":
            raise ValueError("gate/evidence influence requested")
    rows = pack.get("gametes")
    if not isinstance(rows, list) or len(rows) != sum(REQUIRED.values()):
        raise ValueError("unexpected gamete count")
    if len({r.get("id") for r in rows}) != len(rows):
        raise ValueError("duplicate gamete id")
    for arena, count in REQUIRED.items():
        if sum(r.get("arena") == arena for r in rows) != count:
            raise ValueError("incorrect arena allocation")
    if any(r.get("kind") not in KINDS.get(r.get("arena"), set()) for r in rows):
        raise ValueError("unknown arena/kind")


def evaluate_pack(pack: dict[str, Any] | None = None, data_dir: Path = DATA_DIR) -> dict[str, Any]:
    pack = load_json(PACK_PATH) if pack is None else pack
    require_isolation(pack)
    collective = load_json(data_dir / "collective-mind/latest.json")
    research = load_json(data_dir / "research-algorithm/latest.json")
    warp = load_json(data_dir / "warp-propulsion/latest.json")
    llm = load_json(data_dir / "llm-guided-search/latest.json")
    routing_memory = load_routing_memory(data_dir)
    routing_champion = select_routing_genome(routing_memory)
    quality_champion = select_quality_guard()
    current_score_genome = load_score_genome(data_dir)
    best_research = (research.get("ranked") or [])[0]
    baseline_queries = build_queries(best_research["genes"])
    best_warp = warp["best"]
    physics_checks = reference_checks()
    if not physics_checks["passed"]:
        raise ValueError("warp reference checks failed")
    # Adversarial out-of-domain fixture drawn from the observed failure class:
    # a formally valid structured answer that talks about authorization rather
    # than the domain task. The guard is not assumed to understand semantics.
    irrelevant = {
        "proposal": '{"controlPlane":{"capabilityGate":{"decision":"ABSTAIN"},"candidateCount":0}}',
        "method": "Test and compare the authorization sequence rather than a buyer problem.",
        "falsifier": "Reject if payment and authorization capability checks fail.",
    }
    results = []
    for row in pack["gametes"]:
        name, lane, genes = row["id"], row["arena"], row["genes"]
        base = {"id": name, "arena": lane, "kind": row["kind"],
                "production_promoted": False, "holdout_validated": False}
        if lane == "collective-mind" and row["kind"] == "routing":
            proxy = routing_genome_fitness(genes, routing_memory)
            comparator = routing_genome_fitness(routing_champion, routing_memory)
            result = {**base, "status": "PROXY_ONLY", "metric": "historical_routing_proxy",
                      "candidate_fitness": proxy, "reference_fitness": comparator,
                      "reference_name": routing_champion["name"],
                      "needs": "three independent task-verified external rounds; substantive proposal yield"}
        elif lane == "collective-mind" and row["kind"] == "quality_guard":
            candidate_fitness = quality_guard_fitness(genes)
            reference_fitness = quality_guard_fitness(quality_champion)
            false_accept = _quality_guard_accepts(irrelevant, genes)
            result = {**base, "status": "HOLD_ADVERSARIAL" if false_accept else "HOLD_UNSEEN_SET",
                      "metric": "existing_static_quality_holdout",
                      "candidate_fitness": candidate_fitness, "reference_fitness": reference_fitness,
                      "adversarial_controlplane_false_accept": false_accept,
                      "needs": "independent unseen relevance judgments; no promotion from lexical tests"}
        elif lane == "collective-mind" and row["kind"] == "score_genome":
            proposed = genome_fitness(collective, genes)
            current = genome_fitness(collective, current_score_genome)
            valid = int(collective.get("round1_valid_proposals") or 0)
            result = {**base, "status": "HOLD_INSUFFICIENT_PROPOSALS" if valid < 2 else "PROXY_ONLY",
                      "metric": "historical_single_round_rescore",
                      "candidate_fitness": proposed, "reference_fitness": current,
                      "proposal_count": valid,
                      "needs": "multiple independent supported proposals and blind ranking"}
        elif lane == "llm-guided-search":
            # Compile actual baseline-compatible prompts without invoking Ollama.
            prompts = []
            for topic, query in baseline_queries:
                text = make_mutation_prompt(topic, query, genes["parent_mutation"])
                text += " Additional bounded instruction: " + genes["instruction"]
                prompts.append({"topic": topic, "digest": _sha(text), "length": len(text)})
            result = {**base, "status": "PROMPT_COMPILED_UNMEASURED",
                      "metric": "offline_prompt_compilation",
                      "source_baseline_genome": best_research["genome_id"],
                      "prompt_count": len(prompts),
                      "unique_prompt_count": len({p["digest"] for p in prompts}),
                      "baseline_llm_status": llm.get("status"),
                      "needs": "local-model output and same-source independent signal, precision and vendor-noise comparison"}
        elif lane == "warp-propulsion":
            candidate = score_candidate(Candidate(**genes))
            physical = evaluate_candidate(genes)
            result = {**base, "status": "HEURISTIC_ONLY",
                      "metric": "existing_dimensionless_surrogate",
                      "candidate_fitness": candidate["fitness"],
                      "reference_fitness": best_warp["fitness"],
                      "candidate_hard_flags": candidate["hard_flags"],
                      "physical_status": physical["status"],
                      "physical_feasibility_established": False,
                      "needs": "explicit metric, full tensor/matter source, dynamic validation, independent scientific review"}
        elif lane == "research-algorithm":
            normalized = clamp_genome(genes)
            if normalized != genes:
                raise ValueError("research genome clamped; refusing unacknowledged mutation")
            pairs = build_queries(normalized)
            baseline_pairs = build_queries(best_research["genes"])
            result = {**base, "status": "QUERY_COMPILED_UNMEASURED",
                      "metric": "existing_query_builder",
                      "query_count": len(pairs),
                      "unique_query_count": len(set(pairs)),
                      "differs_from_champion": pairs != baseline_pairs,
                      "reference_genome": best_research["genome_id"],
                      "needs": "same-window provider benchmark with fresh independent signal threads and price-evidence controls"}
        else:
            raise ValueError("unknown candidate " + name)
        results.append(result)
    return {
        "schema_v": 1,
        "campaign": pack["campaign"],
        "mode": "OFFLINE_SHADOW_NO_NETWORK",
        "evaluation_scope": "native functions + committed public Arena reports",
        "gametes_total": len(results),
        "measured_live_provider_rounds": 0,
        "production_promoted": False,
        "writes_to_arena_state": False,
        "commercial_gate_influence": "NONE",
        "external_actions": False,
        "automatic_winners": [],
        "results": results,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=None,
                        help="Optional explicit JSON report destination; never Arena state")
    args = parser.parse_args()
    report = evaluate_pack()
    result = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output is not None:
        if args.output.resolve().is_relative_to(DATA_DIR.resolve()):
            raise SystemExit("Refusing to overwrite any Arena state/report under data/arena")
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(result, encoding="utf-8")
    print(result, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
