from __future__ import annotations

import argparse
import copy
import json
import random
from pathlib import Path

try:
    from .evaluate import load_dataset, load_proposal, metrics, validate_proposal
except ImportError:
    from evaluate import load_dataset, load_proposal, metrics, validate_proposal

BASE_SEED = 20260929
POPULATION = 192


def complexity(p: dict) -> int:
    return (
        sum(len(p["positive_markers"][k]) for k in ("pain", "buy", "paid"))
        + len(p["negative_markers"])
        + len(p["negations"])
        + len(p["vendor_exclusion"]["markers"])
        + len(p["vendor_exclusion"]["source_types"])
        + int(p["vendor_exclusion"]["enabled"])
    )


def canonical(p: dict) -> str:
    q = copy.deepcopy(p)
    q["name"] = "_"
    return json.dumps(q, sort_keys=True, separators=(",", ":"))


def mutate(parent: dict, rng: random.Random, vendor_markers: list[str], vendor_sources: list[str], index: int) -> dict:
    p = copy.deepcopy(parent)
    p["name"] = f"evolved-{index:04d}"

    for key in ("pain", "buy", "paid", "negative"):
        if rng.random() < 0.85:
            p["weights"][key] = max(0, min(10, p["weights"][key] + rng.choice([-2, -1, 1, 2])))

    if rng.random() < 0.90:
        p["thresholds"]["demand_score_min"] = max(
            1,
            min(30, p["thresholds"]["demand_score_min"] + rng.choice([-3, -2, -1, 1, 2, 3])),
        )
    p["thresholds"]["vendor_fp_rate_max"] = 0.0

    ven = p["vendor_exclusion"]
    if rng.random() < 0.15:
        ven["enabled"] = not ven["enabled"]

    if vendor_markers and rng.random() < 0.65:
        marker = rng.choice(vendor_markers)
        current = list(ven["markers"])
        if marker in current:
            current.remove(marker)
        elif len(current) < 32:
            current.append(marker)
        ven["markers"] = sorted(set(current))

    if vendor_sources and rng.random() < 0.35:
        source = rng.choice(vendor_sources)
        current = list(ven["source_types"])
        if source in current:
            current.remove(source)
        elif len(current) < 8:
            current.append(source)
        ven["source_types"] = sorted(set(current))

    return validate_proposal(p)


def rank(m: dict, p: dict) -> tuple:
    eligible = int(m["vendor_false_positives"] == 0)
    return (
        eligible,
        m["recall_real_demand"] if eligible else -1.0,
        m["precision_real_demand"] if eligible else -1.0,
        -complexity(p),
        canonical(p),
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--train", required=True)
    ap.add_argument("--proposals-dir", default="arena/commercial_signal/proposals")
    ap.add_argument("--state-in", default="")
    ap.add_argument("--candidate-out", required=True)
    ap.add_argument("--metrics-out", required=True)
    args = ap.parse_args()

    train = load_dataset(Path(args.train))
    parents = [load_proposal(p) for p in sorted(Path(args.proposals_dir).glob("*.json"))]
    previous = {}
    if args.state_in and Path(args.state_in).exists():
        previous = json.loads(Path(args.state_in).read_text(encoding="utf-8"))
        if isinstance(previous.get("optimizer_best_proposal"), dict):
            parents.append(validate_proposal(previous["optimizer_best_proposal"]))

    round_no = int(previous.get("round", 0)) + 1
    seed = BASE_SEED + round_no
    rng = random.Random(seed)

    marker_pool = sorted({m for p in parents for m in p["vendor_exclusion"]["markers"]})
    source_pool = sorted({m for p in parents for m in p["vendor_exclusion"]["source_types"]})

    population = [copy.deepcopy(p) for p in parents]
    seen = {canonical(p) for p in population}
    index = 0
    while len(population) < POPULATION:
        candidate = mutate(rng.choice(parents), rng, marker_pool, source_pool, index)
        index += 1
        sig = canonical(candidate)
        if sig not in seen:
            population.append(candidate)
            seen.add(sig)

    scored = []
    for proposal in population:
        proposal_metrics = metrics(train, proposal)
        scored.append((rank(proposal_metrics, proposal), proposal, proposal_metrics))
    scored.sort(key=lambda x: x[0], reverse=True)
    _, best, best_metrics = scored[0]

    Path(args.candidate_out).write_text(json.dumps(best, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    out = {
        "round": round_no,
        "seed": seed,
        "population": len(population),
        "train_cases": len(train),
        "train_metrics": best_metrics,
        "complexity": complexity(best),
        "candidate_name": best["name"],
    }
    Path(args.metrics_out).write_text(json.dumps(out, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        "round=%d seed=%d population=%d train_cases=%d train_recall=%.4f train_vendor_fp=%d complexity=%d"
        % (
            round_no,
            seed,
            len(population),
            len(train),
            best_metrics["recall_real_demand"],
            best_metrics["vendor_false_positives"],
            complexity(best),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
