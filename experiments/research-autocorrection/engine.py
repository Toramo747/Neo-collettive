# SPDX-License-Identifier: BUSL-1.1
"""Feedback-guided, bounded gamete proposals. Pure shadow, no network or writes to arena."""
from __future__ import annotations

import hashlib
import json
import math
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from arena_research_algorithm import build_queries, clamp_genome  # noqa: E402

POLICY = Path(__file__).with_name("policy.json")
REPORT = Path("/tmp/oxibay-research-autocorrection-shadow.json")
REJECTION_STAGES = ("irrelevant", "unknown_family", "no_buyer_voice", "no_demand_tags")
STAGES = (*REJECTION_STAGES, "valid_signal", "vendor_or_supply")


def load_policy():
    p = json.loads(POLICY.read_text(encoding="utf-8"))
    if p.get("schema_v") != 1 or p["max_candidates"] != 8:
        raise ValueError("Policy version/candidate budget mismatch")
    for key, value in {
        "shadow_only": True, "production_state_write": False,
        "commercial_gate_influence": "NONE", "commercial_evidence_influence": "NONE",
        "price_cache_influence": "NONE", "commercial_policy_mutation": False,
        "private_dataset_access": False, "raw_external_text_persisted": False,
        "automatic_promotion": False, "provider_cost_eur": 0
    }.items():
        if p["safety"].get(key) != value:
            raise ValueError("Forbidden policy mutation: " + key)
    if p["evaluation_gate"]["automatic_promotion"] is not False:
        raise ValueError("Promotion is forbidden")
    if p["training_only"] != ["2026-05", "2026-06", "2026-07"]:
        raise ValueError("Training-window drift")
    for key, bound in {"exploration_rate": [0.1, 0.5],
                       "novelty_penalty": [0, 0.4],
                       "temporal_robustness": [0, 0.5]}.items():
        if p["knob_bounds"][key] != bound:
            raise ValueError("Unapproved knob bounds: " + key)
    if set(p["rejection_feedback"]) != set(REJECTION_STAGES):
        raise ValueError("Rejection feedback drift")
    return p


def load_training(p):
    path = ROOT / p["training_feedback"]
    if path != Path(__file__).with_name("feedback_2026-10-09.json"):
        raise ValueError("Feedback location drift")
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema_v") != 1 or data.get("allowed_use") != "TRAINING_HYPOTHESIS_GENERATION_ONLY":
        raise ValueError("Unapproved training data")
    source = data["provenance"]
    if source["run_id"] != 37892131295 or source["verdict"] != "NO_REPRODUCIBLE_TEMPORAL_GAIN_DEMONSTRATED":
        raise ValueError("Unexpected historical provenance")
    if [w["id"] for w in data["windows"]] != p["training_only"]:
        raise ValueError("Training window contamination")
    for w in data["windows"]:
        for arm in ("compact_matched", "evolved_g69"):
            row = w["arms"][arm]
            stages = row["rejection_reasons"]
            if (set(stages) != set(STAGES) or min(stages.values()) < 0
                or sum(stages.values()) != row["deduplicated_objects"]
                or stages["valid_signal"] != row["signal_hits"]
                or not 0 <= row["unique_signal_threads"] <= row["signal_hits"]
                or row["relevant_hits"] > row["deduplicated_objects"]):
                raise ValueError("Training stage integrity failure")
        if w["arms"]["evolved_g69"]["unique_signal_threads"] != w["arms"]["compact_matched"]["unique_signal_threads"]:
            raise ValueError("Baseline equality from historic run changed")
    return data


def rejection_priority(training):
    failures = Counter()
    for window in training["windows"]:
        stages = window["arms"]["evolved_g69"]["rejection_reasons"]
        failures.update({k: int(stages[k]) for k in REJECTION_STAGES})
    if not failures or max(failures.values(), default=0) == 0:
        raise ValueError("No diagnostic evidence for correction")
    # Published historical negative results only select which hypotheses to try.
    return sorted(REJECTION_STAGES, key=lambda k: (-failures[k], k)), dict(failures)


def propose(p, training):
    prioritized, counts = rejection_priority(training)
    seed = {
        "query_mode": "mixed", "query_count": 4, "recency_days": 45,
        "min_relevance_tokens": 1, "suffix_family": "core",
        "topic_shape": "compact", "query_frame": "plain",
        "term_order": "signal_first", "source_scope": "all",
    }
    # Knobs are experimental controls. These proposals are untested hypotheses.
    mapping = {
        "no_buyer_voice": {"query_mode": "buyer", "suffix_family": "core", "topic_shape": "compact"},
        "irrelevant": {"query_mode": "mixed", "suffix_family": "intent", "topic_shape": "exact"},
        "unknown_family": {"query_mode": "workaround", "suffix_family": "intent", "topic_shape": "exact"},
        "no_demand_tags": {"query_mode": "pain", "suffix_family": "ops", "topic_shape": "compact"},
    }
    variants = []
    unique = set()
    for i in range(p["max_candidates"]):
        focus = prioritized[i // 2]
        high_exploration = bool(i % 2)
        rate = 0.5 if high_exploration else 0.1
        knobs = {
            "rejection_feedback": focus,
            "exploration_rate": rate,
            "novelty_penalty": 0.1 + 0.1 * (i % 3),
            "temporal_robustness": 0.25 if (i // 2) % 2 == 0 else 0.5,
        }
        if not (0.1 <= rate <= 0.5 and 0 <= knobs["novelty_penalty"] <= 0.4
                and 0 <= knobs["temporal_robustness"] <= 0.5):
            raise ValueError("Gamete parameter out of bounds")
        genes = clamp_genome({**seed, **mapping[focus],
                              "query_frame": "need" if high_exploration else "plain",
                              "term_order": "topic_first" if high_exploration else "signal_first"})
        if genes["query_count"] != seed["query_count"] or genes["source_scope"] != "all":
            raise ValueError("Unfair query budget/source change")
        signature = json.dumps(genes, sort_keys=True)
        if signature in unique:
            raise ValueError("Duplicate query gamete")
        unique.add(signature)
        if len(build_queries(genes)) != 16:
            raise ValueError("Provider budget increased")
        identity = hashlib.sha256((signature + json.dumps(knobs, sort_keys=True)).encode()).hexdigest()[:14]
        variants.append({
            "id": "gamete-" + identity, "knobs": knobs, "search_genes": genes,
            "training_rejections_targeted": counts[focus],
            "external_score": None, "validated": False,
            "eligible_for_promotion": False,
        })
    if len(variants) != p["max_candidates"]:
        raise ValueError("Candidate budget not met")
    return variants


def evaluate_external(candidate, windows, p):
    """Evaluate only previously unseen aggregate windows, never the training months."""
    if not isinstance(windows, list) or len(windows) < p["evaluation_gate"]["windows_required"]:
        return {"verdict": "INSUFFICIENT_EVALUATION_WINDOWS", "eligible_for_promotion": False}
    names = [w.get("id") for w in windows]
    if len(set(names)) != len(names) or set(names) & set(p["training_only"]):
        return {"verdict": "EVALUATION_LEAKAGE_BLOCKED", "eligible_for_promotion": False}
    outcomes = []
    deltas = []
    for w in windows:
        a, b = w.get("matched"), w.get("candidate")
        if not isinstance(a, dict) or not isinstance(b, dict):
            return {"verdict": "INVALID_AGGREGATE", "eligible_for_promotion": False}
        for item in (a, b):
            if (item.get("queries_ok") != 16 or not item.get("metric_integrity")
                or not item.get("synthetic_controls_pass")
                or not isinstance(item.get("precision"), (float, int))
                or not 0 <= item["precision"] <= 1
                or not 0 <= item.get("duplicate_ratio", -1) <= 1
                or min(item.get("relevant_hits", -1),
                       item.get("unique_signal_threads", -1),
                       item.get("topic_coverage", -1)) < 0):
                return {"verdict": "INVALID_OR_INCOMPLETE_EVALUATION", "eligible_for_promotion": False}
        gain = b["unique_signal_threads"] - a["unique_signal_threads"]
        novelty_cost = candidate["knobs"]["novelty_penalty"] * max(
            0, b["duplicate_ratio"] - a["duplicate_ratio"]) * max(1, b["unique_signal_threads"])
        adjusted = gain - novelty_cost
        ok = (a["relevant_hits"] >= p["evaluation_gate"]["matched_min_relevant_hits"]
              and b["topic_coverage"] >= p["evaluation_gate"]["min_signal_topics"]
              and b["precision"] >= a["precision"]
              and gain >= p["evaluation_gate"]["min_unique_thread_gain"]
              and adjusted >= p["evaluation_gate"]["min_unique_thread_gain"])
        outcomes.append(ok)
        deltas.append(gain)
    # Robustness knob penalizes inconsistent window gains; it cannot relax any hard gate.
    spread = max(deltas) - min(deltas)
    stability_cost = candidate["knobs"]["temporal_robustness"] * spread
    passed = sum(outcomes)
    verdict = ("SHADOW_REVIEW_CANDIDATE_NOT_VALIDATED"
               if passed >= 2 and min(deltas) + 0.00001 >= stability_cost
               else "NO_REPRODUCIBLE_GAIN")
    return {
        "verdict": verdict, "passed_windows": passed,
        "temporal_stability_penalty": round(stability_cost, 4),
        "eligible_for_promotion": False,
        "human_verified": False,
        "independent_replications": 0,
    }


def run():
    p = load_policy()
    training = load_training(p)
    candidates = propose(p, training)
    order, counts = rejection_priority(training)
    report = {
        "schema_v": 1, "experiment_id": p["experiment_id"],
        "source_run_id": training["provenance"]["run_id"],
        "source_artifact_id": training["provenance"]["artifact_id"],
        "training_only_windows": p["training_only"],
        "rejection_priority": order, "rejection_counts": counts,
        "candidate_count": len(candidates), "candidates": candidates,
        "decision": "GENERATED_SHADOW_GAMETES_UNVALIDATED",
        "validated_independent_rounds": 0, "automatic_promotion": False,
        "production_state_write": False, "commercial_gate_influence": "NONE",
        "training_is_independent_test": False, "raw_external_text_persisted": False,
    }
    REPORT.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": report["decision"], "dominant_rejection": order[0],
        "candidate_count": len(candidates), "validated_independent_rounds": 0,
        "automatic_promotion": False, "report": str(REPORT)
    }, sort_keys=True))


if __name__ == "__main__":
    if sys.argv[1:]:
        raise SystemExit("No network or production modes supported")
    run()
