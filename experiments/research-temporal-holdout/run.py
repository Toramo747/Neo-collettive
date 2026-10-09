# SPDX-License-Identifier: BUSL-1.1
"""Falsifiable historical time-sliced search test, shadow-only and aggregate-only."""
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
SPEC = spec_from_file_location("oxibay_research_v3", ROOT / "experiments/research-replication-v3/replicate.py")
v3 = module_from_spec(SPEC)
SPEC.loader.exec_module(v3)
from arena_research_algorithm import HN_ENDPOINT, MAX_HITS_PER_QUERY  # noqa: E402

PROTOCOL = Path(__file__).with_name("protocol.json")
REPORT = Path("/tmp/oxibay-temporal-holdout-aggregate.json")


def load():
    p = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    old = v3.load()
    if p["schema_v"] != 1 or p["preregistered_before_first_execution"] is not True:
        raise ValueError("Protocol not preregistered")
    if p["api_endpoint"] != HN_ENDPOINT or p["source"] != "hn_algolia_public_read_only":
        raise ValueError("Provider changed")
    if p["query_budget"]["hits_per_query"] != MAX_HITS_PER_QUERY:
        raise ValueError("Response size changed")
    if p["pinned_parent_commit"] != "45037cbc84579ac227bb006077838e3e8a6fcd45":
        raise ValueError("Unexpected parent")
    expected = {
        "source_provider_independence": False, "human_verified": False,
        "historical_backtest_not_prospective": True,
        "count_as_independent_validation": False,
        "synthetic_controls_only": True, "no_raw_text_urls_ids_in_artifact": True,
        "commercial_gate_influence": "NONE", "production_state_write": False,
        "commercial_evidence_influence": "NONE", "private_datasets_access": False,
        "paid_api_calls": False, "automatic_promotion": False,
    }
    for key, value in expected.items():
        if p["constraints"].get(key) != value:
            raise ValueError("Safety contract failed: " + key)
    if p["decision_rule"]["promote"] is not False:
        raise ValueError("Promotion is forbidden")
    if len(p["temporal_windows"]) != 3 or len(p["topics"]) != 4:
        raise ValueError("Invalid temporal or topical sample")
    for arm, key in (("compact_matched", "compact_matched"), ("evolved_g69", "evolved")):
        expected_genes = {**old["shared_genes"], **old["arms"][key]}
        if p["arms"][arm] != expected_genes:
            raise ValueError("Genome drift: " + arm)
    if p["query_suffixes"] != list(v3.QUERY_SUFFIXES["core"]["mixed"][:4]):
        raise ValueError("Query suffix drift")
    prior = {t["full"] for panel in old["panels"] for t in panel["topics"]}
    prior.update(t["full"] for t in v3.v2.load_protocol()["holdout_topics"])
    prior.update(t["full"] for t in v3.v2.prior.load_protocol()["holdout_topics"])
    prior.update(json.loads((ROOT / "data/arena/research-algorithm/latest.json").read_text())["benchmark"]["topics"])
    domains = set()
    for t in p["topics"]:
        if t["full"] in prior or t["domain"] in domains:
            raise ValueError("Leaked or repeated topical name")
        domains.add(t["domain"])
    if len(domains) != 4:
        raise ValueError("Insufficient topic diversity")
    previous_end = None
    for w in p["temporal_windows"]:
        start = datetime.fromisoformat(w["start"])
        end = datetime.fromisoformat(w["end"])
        if start.tzinfo is None or end.tzinfo is None or start >= end:
            raise ValueError("Invalid UTC window")
        if previous_end is not None and start != previous_end:
            raise ValueError("Windows must be non-overlapping contiguous intervals")
        previous_end = end
    return p


def plan(p):
    return {
        arm: [{"topic": topic["full"],
               "query": " ".join((topic["compact"], suffix) if genes["term_order"] == "topic_first"
                                 else (suffix, topic["compact"]))}
              for topic in p["topics"] for suffix in p["query_suffixes"]]
        for arm, genes in p["arms"].items()
    }


def decide(matched, candidate, p, controls_pass):
    if not controls_pass:
        return "INVALID_SYNTHETIC_CONTROLS"
    if not all(v3.metric_audit(a)["consistent"] for a in (matched, candidate)):
        return "INCONCLUSIVE_METRIC_DISAGREEMENT"
    if matched["ok"] != 16 or candidate["ok"] != 16:
        return "INCONCLUSIVE_PROVIDER_FAILURE"
    a, b = matched["score"]["score"], candidate["score"]["score"]
    criteria = p["decision_rule"]
    if a["relevant_hits"] < criteria["matched_min_relevant_hits"]:
        return "INCONCLUSIVE_WEAK_BASELINE"
    if (b["unique_signal_threads"] >= a["unique_signal_threads"] + criteria["minimum_unique_thread_gain"]
        and b["topic_coverage"] >= criteria["minimum_signal_topics"]
        and b["precision"] >= a["precision"] * criteria["precision_ratio_min"]):
        return "TEMPORAL_CANDIDATE_NOT_VALIDATED"
    return "NO_DEMONSTRATED_GAIN"


def aggregate(arm):
    score = arm["score"]["score"]
    diag = arm["score"]["stages"]
    return {
        "query_success": arm["ok"], "relevant_hits": score["relevant_hits"],
        "deduplicated_objects": score["deduped_object_count"],
        "signal_hits": score["signal_hits"],
        "unique_signal_threads": score["unique_signal_threads"],
        "topic_coverage": score["topic_coverage"], "precision": score["precision"],
        "stage_counts": diag, "metric_integrity": v3.metric_audit(arm)["consistent"],
    }


async def execute():
    p = load()
    q = plan(p)
    if any(len(queries) != 16 for queries in q.values()) or set(q) != {"compact_matched", "evolved_g69"}:
        raise ValueError("Unequal query budget")
    unique_queries = sorted({x["query"] for arm in q.values() for x in arm})
    if not 16 <= len(unique_queries) <= p["query_budget"]["max_queries_per_window"]:
        raise ValueError("Unexpected provider budget")
    controls = v3.v2.synthetic_controls()
    outcomes = []
    async with httpx.AsyncClient(timeout=20, follow_redirects=False, trust_env=False,
                                 headers={"User-Agent": "OXIBAY-Temporal-Shadow-Holdout/1.0"}) as client:
        for window in p["temporal_windows"]:
            start = int(datetime.fromisoformat(window["start"]).timestamp())
            end = int(datetime.fromisoformat(window["end"]).timestamp())
            collected = {}
            for query in unique_queries:
                try:
                    response = await client.get(HN_ENDPOINT, params={
                        "query": query, "hitsPerPage": MAX_HITS_PER_QUERY,
                        "numericFilters": f"created_at_i>={start},created_at_i<{end}"
                    })
                    response.raise_for_status()
                    body = response.json()
                    if not isinstance(body, dict) or not isinstance(body.get("hits"), list):
                        raise ValueError("Unexpected provider payload")
                    collected[query] = {"ok": True, "hits": body["hits"]}
                except (ValueError, TypeError, httpx.HTTPError):
                    collected[query] = {"ok": False, "hits": []}
            evaluated = {}
            for arm, genes in p["arms"].items():
                pairs = q[arm]
                measured = v3.v2.diagnostic_metrics(
                    pairs, [collected[x["query"]]["hits"] for x in pairs], genes)
                evaluated[arm] = {
                    "ok": sum(int(collected[x["query"]]["ok"]) for x in pairs),
                    "score": measured,
                }
            status = decide(evaluated["compact_matched"], evaluated["evolved_g69"], p, controls["pass"])
            outcomes.append({
                "window": window["id"], "verdict": status,
                "arms": {name: aggregate(data) for name, data in evaluated.items()},
                "provider_unique_queries": len(unique_queries),
            })
            collected.clear()
    complete = all(
        w["arms"][arm]["query_success"] == 16
        for w in outcomes for arm in ("compact_matched", "evolved_g69")
    )
    candidates = sum(w["verdict"] == "TEMPORAL_CANDIDATE_NOT_VALIDATED" for w in outcomes)
    minimum = p["decision_rule"]["minimum_passed_windows_for_temporal_robustness"]
    broad_verdict = (
        "INCONCLUSIVE_PROVIDER_OR_METRIC_ERROR"
        if (not complete or any(w["verdict"].startswith(("INVALID_", "INCONCLUSIVE_METRIC_")) for w in outcomes))
        else ("TEMPORAL_EXPLORATORY_SUPPORT_ONLY" if candidates >= minimum
              else "NO_REPRODUCIBLE_TEMPORAL_GAIN_DEMONSTRATED")
    )
    report = {
        "schema_v": 1, "experiment_id": p["experiment_id"],
        "protocol_sha256": hashlib.sha256(PROTOCOL.read_bytes()).hexdigest(),
        "source_commit": p["pinned_parent_commit"], "captured_at_utc": datetime.now(timezone.utc).isoformat(),
        "source": p["source"], "historical_backtest": True,
        "same_provider_and_evaluator": True, "human_verified": False,
        "synthetic_controls": {"pass": controls["pass"], "author_labelled_only": True},
        "windows": outcomes, "candidate_windows": candidates,
        "all_query_success": complete, "verdict": broad_verdict,
        "validated_independent_replications": 0, "cross_source_validation": False,
        "automatic_promotion": False, "production_state_write": False,
        "commercial_gate_influence": "NONE", "raw_external_text_persisted": False,
    }
    REPORT.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "experiment": p["experiment_id"], "verdict": broad_verdict, "controls_pass": controls["pass"],
        "candidate_windows": candidates, "validated_independent_replications": 0,
        "windows": [
            {"window": w["window"], "verdict": w["verdict"],
             "matched": {k: w["arms"]["compact_matched"][k] for k in (
                 "query_success", "relevant_hits", "signal_hits", "unique_signal_threads",
                 "topic_coverage", "precision", "metric_integrity")},
             "evolved": {k: w["arms"]["evolved_g69"][k] for k in (
                 "query_success", "relevant_hits", "signal_hits", "unique_signal_threads",
                 "topic_coverage", "precision", "metric_integrity")}}
            for w in outcomes], "report_path": str(REPORT)
    }, sort_keys=True))


def main():
    p = load()
    if sys.argv[1:] == []:
        q = plan(p)
        print(json.dumps({"mode": "PLAN_ONLY", "windows": len(p["temporal_windows"]),
                          "queries_per_arm_per_window": len(q["compact_matched"]),
                          "max_total_public_requests": p["query_budget"]["max_queries_total"],
                          "production_state_write": False}))
    elif sys.argv[1:] == ["--execute"]:
        asyncio.run(execute())
    else:
        raise SystemExit("Only --execute is accepted")


if __name__ == "__main__":
    main()
