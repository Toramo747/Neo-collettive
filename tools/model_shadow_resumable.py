# SPDX-License-Identifier: BUSL-1.1
from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from collections import Counter
from pathlib import Path

from model_shadow_batch import (
    MODEL_LABELS,
    PRIVATE_FILES,
    REGISTRY,
    _case_text,
    _read_jsonl,
    _safe_metrics,
    _signals,
    _source_bucket,
    _student_training_selection,
    _write_jsonl_private,
    cluster_challenges,
    create_review_sample,
    evaluate_student,
    judge_private_archive,
    train_student,
    update_private_drift_history,
    validate_archive,
)

STATE_FILE = "model_shadow_state.json"
WRAPPER_VERSION = 1


def _source_signature(row: dict) -> str:
    payload = {
        "id": str(row.get("id") or ""),
        "normalized_text": str(row.get("normalized_text") or ""),
        "source": str(row.get("source") or ""),
        "title": str(row.get("title") or ""),
        "url": str(row.get("url") or ""),
        "date": str(row.get("date") or ""),
        "outcome_label": str(row.get("outcome_label") or ""),
        "structural_signals": row.get("structural_signals") if isinstance(row.get("structural_signals"), dict) else {},
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _manifest_hash(rows: list[dict]) -> str:
    registry_hash = hashlib.sha256(
        json.dumps(REGISTRY, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    payload = {
        "wrapper_version": WRAPPER_VERSION,
        "registry_sha256": registry_hash,
        "rows": sorted((str(r.get("id") or ""), _source_signature(r)) for r in rows),
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _load_valid_existing(private_dir: Path, train: list[dict]) -> dict[str, dict]:
    by_id = {str(r.get("id") or ""): r for r in train if str(r.get("id") or "")}
    valid = {}
    for row in _read_jsonl(private_dir / "train_labeled.jsonl"):
        case_id = str(row.get("id") or "")
        source = by_id.get(case_id)
        if not source:
            continue
        if str(row.get("_source_signature") or "") != _source_signature(source):
            continue
        valid[case_id] = row
    return valid


def _summarize_labeled(rows: list[dict]) -> dict:
    counters = Counter()
    distribution = Counter()
    source_distribution = Counter()
    label_source_distribution = Counter()
    threshold = float(REGISTRY["consensus"]["confidence_threshold"])
    buckets = ("reddit","hn","bing-rss","brave","github","stackexchange","pricing_page","job_board","marketplace","web","other")

    for row in rows:
        eligible = bool(row.get("eligible_for_training"))
        counters["processed"] += 1
        counters["eligible"] += int(eligible)
        counters["discarded"] += int(not eligible)
        label = str(row.get("final_label") or "")
        if label in MODEL_LABELS:
            distribution[label] += 1
            label_source_distribution[(label, _source_bucket(row))] += 1
        bucket = _source_bucket(row)
        source_distribution[bucket] += 1

        votes = {str(x.get("judge") or ""): x for x in row.get("judge_labels", []) if isinstance(x, dict)}
        nli = votes.get("nli", {})
        llm = votes.get("local_llm", {})
        structural = votes.get("structural", {})

        nli_score = float(nli.get("confidence") or 0.0)
        if nli_score < 0.50:
            band = "lt_050"
        elif nli_score < 0.70:
            band = "050_070"
        elif nli_score < 0.85:
            band = "070_085"
        else:
            band = "gte_085"
        llm_state = str(llm.get("diagnostic") or "first_invalid")
        structural_conf = float(structural.get("confidence") or 0.0)
        path = "triple" if structural_conf >= threshold else "pair"

        counters["consensus_path_" + path] += 1
        counters["source_" + bucket + "_consensus_path_" + path] += 1
        counters["nli_band_" + band] += 1
        counters["source_" + bucket + "_nli_band_" + band] += 1
        counters["llm_state_" + llm_state] += 1
        counters["source_" + bucket + "_llm_state_" + llm_state] += 1

        nli_label = str(nli.get("label") or "")
        llm_label = str(llm.get("label") or "")
        if nli_label in MODEL_LABELS and llm_label in MODEL_LABELS:
            counters["nli_llm_" + nli_label + "__" + llm_label] += 1
            counters["source_" + bucket + "_nli_llm_" + nli_label + "__" + llm_label] += 1

        if structural_conf < threshold:
            structural_state = "abstained"
        elif nli_label in MODEL_LABELS and llm_label in MODEL_LABELS and nli_label == llm_label == str(structural.get("label") or ""):
            structural_state = "concordant"
        else:
            structural_state = "contrary"
        counters["structural_state_" + structural_state] += 1
        counters["source_" + bucket + "_structural_state_" + structural_state] += 1

    metrics = {
        "processed": counters["processed"],
        "eligible": counters["eligible"],
        "discarded_disagreement": counters["discarded"],
        "judge_agreement_rate_ppm": int(counters["eligible"] * 1_000_000 / max(1, counters["processed"])),
    }
    for label in MODEL_LABELS:
        metrics["label_count_" + label] = int(distribution[label])
    for bucket in buckets:
        metrics["source_bucket_count_" + bucket] = int(source_distribution[bucket])
        for label in MODEL_LABELS:
            metrics["label_source_count_" + label + "_" + bucket] = int(label_source_distribution[(label, bucket)])
    for path in ("pair", "triple"):
        metrics["consensus_path_count_" + path] = int(counters["consensus_path_" + path])
    for band in ("lt_050", "050_070", "070_085", "gte_085"):
        metrics["nli_band_count_" + band] = int(counters["nli_band_" + band])
    for state in ("first_invalid", "second_invalid", "discordant", "concordant"):
        metrics["llm_state_count_" + state] = int(counters["llm_state_" + state])
    for state in ("abstained", "concordant", "contrary"):
        metrics["structural_state_count_" + state] = int(counters["structural_state_" + state])
    for nli_label in MODEL_LABELS:
        for llm_label in MODEL_LABELS:
            metrics["nli_llm_count_" + nli_label + "__" + llm_label] = int(counters["nli_llm_" + nli_label + "__" + llm_label])
    return metrics


def _write_safe(output_dir: Path, metrics: dict) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    safe = _safe_metrics(metrics)
    for key in ("batch_complete", "batch_idle", "batch_processed", "batch_remaining", "batch_total"):
        if key in metrics:
            safe[key] = metrics[key]
    (output_dir / "metrics.json").write_text(
        json.dumps(safe, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(safe, sort_keys=True, separators=(",", ":")))
    return safe


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--private-dir", default=os.getenv("MODEL_LABEL_PRIVATE_DIR", "private-labels"))
    p.add_argument("--output-dir", default="runtime/model-shadow")
    p.add_argument("--max-judge-cases", type=int, default=50)
    p.add_argument("--review-sample", action="store_true")
    args = p.parse_args()

    private_dir = Path(args.private_dir)
    output_dir = Path(args.output_dir)
    archive = validate_archive(private_dir)
    train = _read_jsonl(private_dir / PRIVATE_FILES["train"])
    valid = _load_valid_existing(private_dir, train)
    pending = [r for r in train if str(r.get("id") or "") not in valid]
    chunk = pending[: max(0, args.max_judge_cases)]

    if chunk:
        with tempfile.TemporaryDirectory(prefix="model-shadow-chunk-") as tmp:
            tmpdir = Path(tmp)
            _write_jsonl_private(tmpdir / PRIVATE_FILES["train"], chunk)
            _write_jsonl_private(tmpdir / PRIVATE_FILES["public"], [])
            _write_jsonl_private(tmpdir / PRIVATE_FILES["hidden"], [])
            judge_private_archive(tmpdir, use_models=True)
            for row in _read_jsonl(tmpdir / "train_labeled.jsonl"):
                case_id = str(row.get("id") or "")
                source = next((x for x in chunk if str(x.get("id") or "") == case_id), None)
                if source is None:
                    continue
                copy = dict(row)
                copy["_source_signature"] = _source_signature(source)
                valid[case_id] = copy

    ordered = [valid[str(r.get("id") or "")] for r in train if str(r.get("id") or "") in valid]
    _write_jsonl_private(private_dir / "train_labeled.jsonl", ordered)
    remaining = max(0, len(train) - len(ordered))

    base = {
        "cases": sum(int(x) for x in archive["splits"].values()),
        "train_cases": int(archive["splits"].get("train") or 0),
        "public_cases": int(archive["splits"].get("public") or 0),
        "hidden_cases": int(archive["splits"].get("hidden") or 0),
        "batch_total": len(train),
        "batch_processed": len(chunk),
        "batch_remaining": remaining,
        "batch_complete": remaining == 0,
    }

    if remaining:
        base.update({
            "batch_idle": False,
            "student_available": False,
            "promotion_eligible": False,
            "promotion_requires_manual_approval": True,
        })
        _write_safe(output_dir, base)
        return 0

    manifest = _manifest_hash(train)
    state_path = private_dir / STATE_FILE
    state = {}
    if state_path.is_file():
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
        except Exception:
            state = {}

    if state.get("manifest_sha256") == manifest and isinstance(state.get("safe_metrics"), dict):
        safe = dict(state["safe_metrics"])
        safe.update({
            "batch_complete": True,
            "batch_idle": True,
            "batch_processed": 0,
            "batch_remaining": 0,
            "batch_total": len(train),
        })
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "metrics.json").write_text(
            json.dumps(safe, sort_keys=True, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )
        print(json.dumps(safe, sort_keys=True, separators=(",", ":")))
        return 0

    metrics = dict(base)
    metrics["batch_idle"] = False
    metrics.update(_summarize_labeled(ordered))
    metrics.update(update_private_drift_history(private_dir, metrics))
    selected_rows, selection_metrics = _student_training_selection(private_dir)
    metrics.update(selection_metrics)

    if len(selected_rows) < 4 or int(selection_metrics.get("training_classes_used") or 0) < 2:
        metrics["student_available"] = False
        metrics["training_cases"] = len(selected_rows)
        metrics["promotion_eligible"] = False
        metrics["promotion_requires_manual_approval"] = True
        if args.review_sample:
            metrics.update(create_review_sample(private_dir, 5))
        safe = _write_safe(output_dir, metrics)
    else:
        student_path = output_dir / "student.json"
        metrics["student_available"] = True
        metrics.update(train_student(private_dir, student_path))
        metrics.update(evaluate_student(private_dir, student_path))
        metrics.update(cluster_challenges(private_dir, output_dir / "challenge-cluster-map.json"))
        if args.review_sample:
            metrics.update(create_review_sample(private_dir, 5))
        safe = _write_safe(output_dir, metrics)

    state_path.write_text(
        json.dumps({
            "schema_v": 1,
            "manifest_sha256": manifest,
            "safe_metrics": safe,
        }, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
