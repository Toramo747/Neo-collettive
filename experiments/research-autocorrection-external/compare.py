# SPDX-License-Identifier: BUSL-1.1
"""Preregistered matched HN shadow screen for eight fixed autocorrection gametes."""
from __future__ import annotations

import asyncio
import hashlib
import json
import sys
from datetime import datetime, timezone
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
ENGINE = ROOT / "experiments/research-autocorrection/engine.py"
spec = spec_from_file_location("oxibay_frozen_autocorrection", ENGINE)
engine = module_from_spec(spec)
spec.loader.exec_module(engine)
OLD = ROOT / "experiments/research-replication-v3/replicate.py"
spec_v3 = spec_from_file_location("oxibay_matched_v3", OLD)
v3 = module_from_spec(spec_v3)
spec_v3.loader.exec_module(v3)

from arena_research_algorithm import HN_ENDPOINT, QUERY_SUFFIXES, MAX_HITS_PER_QUERY  # noqa: E402

PROTOCOL = Path(__file__).with_name("protocol.json")
REPORT = Path("/tmp/oxibay-autocorrection-external-aggregate.json")


def read_protocol():
    p = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    if p["schema_v"] != 1 or p["preregistered_before_external_calls"] is not True:
        raise ValueError("Protocol must be frozen before external evaluation")
    if p["source_pr"] != 230 or p["parent_commit"] != "b654fae076a585ad70760f178c7bc6e46391192f":
        raise ValueError("Parent source changed")
    provider = p["provider"]
    if (provider["endpoint"] != HN_ENDPOINT or provider["name"] != "hn_algolia_public_read_only"
        or provider["max_hits_per_query"] != MAX_HITS_PER_QUERY
        or provider["max_total_unique_query_requests"] != 288
        or provider["concurrency"] > 8):
        raise ValueError("Provider limit drift")
    expected = {
        "zero_paid_provider_queries": True, "historical_backtest_not_prospective": True,
        "selected_gametes_reuse_prior_training_feedback_only": True,
        "single_provider_only": True, "not_blind_human_verified": True,
        "no_raw_source_text_in_artifacts": True, "no_raw_source_ids_in_artifacts": True,
        "no_source_urls_in_artifacts": True, "no_source_query_strings_in_artifacts": True,
        "no_commercial_gate_influence": True, "no_runtime_or_arena_state_writes": True,
        "no_production_deploy": True, "no_student_promotion": True, "no_paid_model": True,
    }
    for key, value in expected.items():
        if p["constraints"].get(key) != value:
            raise ValueError("Safety boundary changed: " + key)
    gate = p["decision_rule"]
    if gate["allow_automatic_promotion"] is not False or gate["minimum_successful_windows"] != 2:
        raise ValueError("Forbidden promotion or weakened threshold")
    if p["training_only_months"] != ["2026-05", "2026-06", "2026-07"]:
        raise ValueError("Training set drift")
    if [w["id"] for w in p["evaluation_windows"]] != ["2026-08", "2026-09"]:
        raise ValueError("Evaluation periods changed")
    end_previous = None
    for item in p["evaluation_windows"]:
        start = datetime.fromisoformat(item["start"])
        end = datetime.fromisoformat(item["end"])
        if start.tzinfo is None or end.tzinfo is None or start >= end or (
            end_previous is not None and end_previous != start):
            raise ValueError("Invalid or overlapping time windows")
        end_previous = end
    policy = engine.load_policy()
    training = engine.load_training(policy)
    gametes = engine.propose(policy, training)
    if len(gametes) != p["arms"]["candidates"] != 8:
        raise ValueError("Candidate drift")
    if not all(g["external_score"] is None and g["validated"] is False
               and g["eligible_for_promotion"] is False for g in gametes):
        raise ValueError("Candidate pre-screen contaminated")
    if p["arms"]["planned_queries_per_arm_window"] != 16 or len(p["evaluation_topics"]) != 4:
        raise ValueError("Unfair provider budget")
    old_domains = {
        str(t["domain"]) for section in v3.load()["panels"] for t in section["topics"]
    }
    old_domains.update(t["domain"] for t in v3.v2.load_protocol()["holdout_topics"])
    old_domains.update(t["domain"] for t in
                       json.loads((ROOT / "experiments/research-temporal-holdout/protocol.json")
                                  .read_text(encoding="utf-8"))["topics"])
    seen = set()
    for topic in p["evaluation_topics"]:
        if topic["domain"] in old_domains or topic["domain"] in seen:
            raise ValueError("Repeated topic domain")
        seen.add(topic["domain"])
    baseline = p["baseline_genes"]
    if baseline != policy_baseline():
        raise ValueError("Matched baseline changed")
    return p, gametes, policy


def policy_baseline():
    return {
        "query_mode": "mixed", "query_count": 4, "recency_days": 45,
        "min_relevance_tokens": 1, "suffix_family": "core",
        "topic_shape": "compact", "query_frame": "plain",
        "term_order": "topic_first", "source_scope": "all",
    }


def build_arm_queries(p, genes):
    topics = p["evaluation_topics"]
    suffixes = QUERY_SUFFIXES[genes["suffix_family"]][genes["query_mode"]][:genes["query_count"]]
    if len(suffixes) != 4 or genes["source_scope"] != "all" or genes["min_relevance_tokens"] != 1:
        raise ValueError("Query/source budget mismatch")
    rows = []
    for topic in topics:
        shaped = topic["full"] if genes["topic_shape"] == "exact" else topic["compact"]
        for suffix in suffixes:
            parts = (shaped, suffix) if genes["term_order"] == "topic_first" else (suffix, shaped)
            query = " ".join(parts)
            if genes["query_frame"] == "need":
                query = "need " + query
            elif genes["query_frame"] == "looking_for":
                query = "looking for " + query
            elif genes["query_frame"] != "plain":
                raise ValueError("Invalid query frame")
            rows.append({"topic": topic["full"], "query": query})
    if len(rows) != 16:
        raise ValueError("Expected precisely 16 queries for every arm")
    return rows


def make_plan(p, gametes):
    arm_genes = {"baseline": p["baseline_genes"]}
    arm_genes.update({g["id"]: g["search_genes"] for g in gametes})
    if len(arm_genes) != 9:
        raise ValueError("Not eight distinct gametes plus baseline")
    queries = {arm: build_arm_queries(p, genes) for arm, genes in arm_genes.items()}
    unique = sorted({q["query"] for rows in queries.values() for q in rows})
    if len(unique) > p["provider"]["max_unique_queries_per_window"]:
        raise ValueError("Provider query cap exceeded")
    return arm_genes, queries, unique


def duplicate_ratio(pairs, batches, score):
    total = sum(len(batch) for batch in batches)
    count = score["deduped_object_count"]
    if total < count:
        raise ValueError("Impossible source deduplication")
    return round((total - count) / total, 6) if total else 0.0


def measure(rows, payloads, genes, controls):
    hits = [payloads[r["query"]]["hits"] for r in rows]
    success = sum(int(payloads[r["query"]]["ok"]) for r in rows)
    if not controls:
        return {"ok": success, "valid": False, "reason": "INVALID_SYNTHETIC_CONTROL"}
    try:
        diag = v3.v2.diagnostic_metrics(rows, hits, genes)
        complete = {"ok": success, "score": diag}
        audit = v3.metric_audit(complete)["consistent"]
        score = diag["score"]
        return {
            "ok": success,
            "valid": bool(audit and success == 16),
            "reason": "OK" if audit and success == 16 else "PROVIDER_OR_METRIC_INCONCLUSIVE",
            "score": score,
            "duplicate_ratio": duplicate_ratio(rows, hits, score),
            "rejection_stages": diag["stages"],
        }
    except (ValueError, TypeError, KeyError):
        return {"ok": success, "valid": False, "reason": "DIAGNOSTIC_EXCEPTION"}


def public_metrics(result):
    if not result["valid"]:
        return {"query_success": result["ok"], "valid": False, "reason": result["reason"]}
    s = result["score"]
    return {
        "query_success": result["ok"], "valid": True,
        "relevant_hits": s["relevant_hits"], "signal_hits": s["signal_hits"],
        "unique_signal_threads": s["unique_signal_threads"], "topic_coverage": s["topic_coverage"],
        "precision": s["precision"], "deduped_objects": s["deduped_object_count"],
        "duplicate_ratio": result["duplicate_ratio"], "rejection_stages": result["rejection_stages"],
    }


def to_engine_aggregate(m, controls):
    if not m["valid"]:
        return {"queries_ok": m["ok"], "metric_integrity": False, "synthetic_controls_pass": controls}
    s = m["score"]
    return {
        "queries_ok": m["ok"], "metric_integrity": True,
        "synthetic_controls_pass": controls, "relevant_hits": s["relevant_hits"],
        "unique_signal_threads": s["unique_signal_threads"],
        "topic_coverage": s["topic_coverage"], "precision": s["precision"],
        "duplicate_ratio": m["duplicate_ratio"]
    }


async def execute():
    p, gametes, policy = read_protocol()
    genes, plans, queries = make_plan(p, gametes)
    controls = v3.v2.synthetic_controls()["pass"]
    if not controls:
        raise ValueError("Shadow synthetic controls failed")
    output = []
    timeout = httpx.Timeout(p["provider"]["http_timeout_seconds"])
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=False, trust_env=False,
                                 headers={"User-Agent": "OXIBAY-Research-Autocorrection-Screen/1.0"}) as client:
        semaphore = asyncio.Semaphore(p["provider"]["concurrency"])
        for window in p["evaluation_windows"]:
            start = int(datetime.fromisoformat(window["start"]).timestamp())
            end = int(datetime.fromisoformat(window["end"]).timestamp())
            async def fetch(query):
                async with semaphore:
                    try:
                        response = await client.get(HN_ENDPOINT, params={
                            "query": query, "hitsPerPage": MAX_HITS_PER_QUERY,
                            "numericFilters": f"created_at_i>={start},created_at_i<{end}"
                        })
                        response.raise_for_status()
                        body = response.json()
                        if not isinstance(body, dict) or not isinstance(body.get("hits"), list):
                            raise ValueError("Malformed provider response")
                        return query, {"ok": True, "hits": body["hits"]}
                    except (httpx.HTTPError, ValueError, TypeError):
                        return query, {"ok": False, "hits": []}
            # Bound in-memory results to one historical month; raw source data
            # never enters a public artifact, stdout, GitHub commit, or durable cache.
            replies = await asyncio.gather(*(fetch(q) for q in queries))
            results = dict(replies)
            measured = {arm: measure(rows, results, genes[arm], controls)
                        for arm, rows in plans.items()}
            public = {arm: public_metrics(m) for arm, m in measured.items()}
            output.append({
                "window_id": window["id"], "public_provider_requests": len(queries),
                "provider_success": sum(int(v["ok"]) for v in results.values()),
                "arms": public,
            })
            del results, replies, measured
    verdicts = []
    for candidate in gametes:
        evaluations = []
        for month in output:
            matched = month["arms"]["baseline"]
            tested = month["arms"][candidate["id"]]
            if not matched["valid"] or not tested["valid"]:
                evaluations.append({
                    "id": month["window_id"],
                    "matched": {"queries_ok": matched["query_success"], "metric_integrity": False},
                    "candidate": {"queries_ok": tested["query_success"], "metric_integrity": False}
                })
            else:
                def translate(row):
                    return {
                        "queries_ok": row["query_success"], "metric_integrity": row["valid"],
                        "synthetic_controls_pass": controls, "relevant_hits": row["relevant_hits"],
                        "unique_signal_threads": row["unique_signal_threads"],
                        "topic_coverage": row["topic_coverage"], "precision": row["precision"],
                        "duplicate_ratio": row["duplicate_ratio"]
                    }
                evaluations.append({"id": month["window_id"], "matched": translate(matched),
                                    "candidate": translate(tested)})
        verdict = engine.evaluate_external(candidate, evaluations, policy)
        verdicts.append({
            "gamete_id": candidate["id"],
            "rejection_feedback": candidate["knobs"]["rejection_feedback"],
            "verdict": verdict["verdict"], "windows_passed": verdict.get("passed_windows", 0),
            "eligible_for_promotion": False, "human_verified": False,
        })
    full_source = all(w["provider_success"] == w["public_provider_requests"] for w in output)
    any_valid = any(x["verdict"] == "SHADOW_REVIEW_CANDIDATE_NOT_VALIDATED" for x in verdicts)
    overall = ("INVALID_OR_INCOMPLETE_PROVIDER_DATA" if not full_source else
               "EXPLORATORY_SCREEN_HIT_UNVALIDATED" if any_valid else
               "NO_REPLICATED_ADVANTAGE_DEMONSTRATED")
    report = {
        "schema_v": 1, "experiment_id": p["experiment_id"],
        "protocol_sha256": hashlib.sha256(PROTOCOL.read_bytes()).hexdigest(),
        "captured_at_utc": datetime.now(timezone.utc).isoformat(),
        "training_months_excluded": p["training_only_months"],
        "provider": p["provider"]["name"], "time_windows": output,
        "gamete_verdicts": verdicts, "candidate_count": len(gametes),
        "unique_provider_requests_total": len(output) * len(queries),
        "all_provider_requests_succeeded": full_source,
        "synthetic_controls_passed": controls, "multiple_comparisons": 8,
        "overall_verdict": overall, "human_review": "NOT_PERFORMED",
        "prospective_or_cross_source_validation": False,
        "independent_validated_replications": 0, "automatic_promotion": False,
        "production_state_write": False, "commercial_gate_influence": "NONE",
        "raw_external_text_or_identifiers_persisted": False,
    }
    REPORT.write_text(json.dumps(report, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "overall_verdict": overall, "candidate_count": len(gametes),
        "provider_queries_attempted": report["unique_provider_requests_total"],
        "provider_all_ok": full_source, "independent_validated_replications": 0,
        "windows": [{
            "month": month["window_id"],
            "matched_threads": month["arms"]["baseline"].get("unique_signal_threads"),
            "candidate_threads": {
                c["id"]: month["arms"][c["id"]].get("unique_signal_threads") for c in gametes
            },
        } for month in output],
        "verdicts": [{"id": v["gamete_id"], "result": v["verdict"]} for v in verdicts],
        "report": str(REPORT)
    }, sort_keys=True))


def main():
    p, gametes, _ = read_protocol()
    _, arms, unique = make_plan(p, gametes)
    if sys.argv[1:] == []:
        print(json.dumps({
            "mode": "PLAN_ONLY", "arms": len(arms), "time_windows": len(p["evaluation_windows"]),
            "queries_per_arm_window": 16, "max_unique_provider_requests": len(unique) * 2,
            "production_state_write": False
        }, sort_keys=True))
    elif sys.argv[1:] == ["--execute"]:
        asyncio.run(execute())
    else:
        raise SystemExit("Unknown flags")


if __name__ == "__main__":
    main()
