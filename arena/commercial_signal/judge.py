from __future__ import annotations

import argparse
import json
from pathlib import Path

try:
    from .evaluate import load_dataset, load_proposal, metrics, validate_proposal
except ImportError:
    from evaluate import load_dataset, load_proposal, metrics, validate_proposal


def marker_ceiling(rows: list[dict], proposals: list[dict]) -> float:
    demands = [r for r in rows if r["proposed_label"] == "REAL_DEMAND"]
    if not demands:
        return 0.0
    paid = {m for p in proposals for m in p["positive_markers"]["paid"]}
    buyer_or_pain = {
        m
        for p in proposals
        for family in ("buy", "pain")
        for m in p["positive_markers"][family]
    }
    possible = 0
    for row in demands:
        text = " ".join(str(row.get("evidence_text") or "").lower().split())
        if any(m in text for m in paid) and any(m in text for m in buyer_or_pain):
            possible += 1
    return possible / len(demands)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--holdout", required=True)
    ap.add_argument("--candidate", required=True)
    ap.add_argument("--train-metrics", required=True)
    ap.add_argument("--baseline", required=True)
    ap.add_argument("--proposals-dir", default="arena/commercial_signal/proposals")
    ap.add_argument("--state-in", default="")
    ap.add_argument("--state-out", required=True)
    ap.add_argument("--report-out", required=True)
    args = ap.parse_args()

    holdout = load_dataset(Path(args.holdout))
    candidate = validate_proposal(json.loads(Path(args.candidate).read_text(encoding="utf-8")))
    train_info = json.loads(Path(args.train_metrics).read_text(encoding="utf-8"))
    baseline = load_proposal(Path(args.baseline))
    prior = {}
    if args.state_in and Path(args.state_in).exists():
        prior = json.loads(Path(args.state_in).read_text(encoding="utf-8"))

    candidate_holdout = metrics(holdout, candidate)
    baseline_holdout = metrics(holdout, baseline)
    train_candidate = train_info["train_metrics"]

    eligible = (
        train_candidate["vendor_false_positives"] == 0
        and candidate_holdout["vendor_false_positives"] == 0
    )
    beats_baseline = eligible and (
        candidate_holdout["recall_real_demand"] > baseline_holdout["recall_real_demand"]
    )

    success_streak = int(prior.get("success_streak", 0)) + 1 if beats_baseline else 0
    previous_best = float(
        prior.get("best_eligible_holdout_recall", baseline_holdout["recall_real_demand"])
    )
    improved = eligible and candidate_holdout["recall_real_demand"] > previous_best
    stall_count = 0 if improved else int(prior.get("stall_count", 0)) + 1

    status = "RUNNING"
    if success_streak >= 3:
        status = "SUCCESS"
    elif stall_count >= 10:
        status = "STALLED"

    proposal_pool = [load_proposal(p) for p in sorted(Path(args.proposals_dir).glob("*.json"))]
    ceiling = marker_ceiling(holdout, proposal_pool)
    diagnosis = "undetermined"
    if status == "STALLED":
        if ceiling <= baseline_holdout["recall_real_demand"]:
            diagnosis = "proposal_schema_or_marker_space_insufficient"
        else:
            diagnosis = "more_data_needed"

    entry = {
        "round": train_info["round"],
        "seed": train_info["seed"],
        "train_recall": train_candidate["recall_real_demand"],
        "train_vendor_fp": train_candidate["vendor_false_positives"],
        "holdout_recall": candidate_holdout["recall_real_demand"],
        "holdout_vendor_fp": candidate_holdout["vendor_false_positives"],
        "baseline_holdout_recall": baseline_holdout["recall_real_demand"],
        "baseline_holdout_vendor_fp": baseline_holdout["vendor_false_positives"],
        "beats_baseline": beats_baseline,
    }
    history = list(prior.get("history", [])) + [entry]

    state = {
        "status": status,
        "round": train_info["round"],
        "success_streak": success_streak,
        "stall_count": stall_count,
        "best_eligible_holdout_recall": max(
            previous_best,
            candidate_holdout["recall_real_demand"] if eligible else previous_best,
        ),
        "optimizer_best_proposal": candidate,
        "history": history[-20:],
        "stall_diagnosis": diagnosis,
        "search_space_holdout_recall_ceiling": round(ceiling, 4),
    }
    Path(args.state_out).write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    report = {
        "status": status,
        "round": train_info["round"],
        "seed": train_info["seed"],
        "train": train_candidate,
        "holdout": candidate_holdout,
        "baseline_holdout": baseline_holdout,
        "success_streak": success_streak,
        "stall_count": stall_count,
        "beats_baseline": beats_baseline,
        "search_space_holdout_recall_ceiling": round(ceiling, 4),
        "stall_diagnosis": diagnosis,
    }
    Path(args.report_out).write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        "round=%d holdout_recall=%.4f baseline_recall=%.4f holdout_vendor_fp=%d streak=%d stall=%d status=%s"
        % (
            train_info["round"],
            candidate_holdout["recall_real_demand"],
            baseline_holdout["recall_real_demand"],
            candidate_holdout["vendor_false_positives"],
            success_streak,
            stall_count,
            status,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
