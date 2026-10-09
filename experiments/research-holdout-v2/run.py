# SPDX-License-Identifier: BUSL-1.1
"""Preregistered disjoint-domain HN shadow holdout. No production writes."""
from __future__ import annotations

import argparse
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
OLD = ROOT / "experiments/research-holdout/compare.py"
_spec = spec_from_file_location("oxibay_prior_holdout", OLD)
prior = module_from_spec(_spec)
_spec.loader.exec_module(prior)
from arena_research_algorithm import HN_ENDPOINT, MAX_HITS_PER_QUERY, QUERY_SUFFIXES  # noqa: E402

PROTOCOL = Path(__file__).with_name("protocol.json")
REPORT = Path("/tmp/oxibay-research-disjoint-holdout.json")
POSITIVE_TEXT = "I need a tool for manual data entry because this workaround wastes time"
NEGATIVE_TEXT = "A release note describing manual data entry features was published"
STAGES = ("irrelevant", "vendor_or_supply", "unknown_family", "no_buyer_voice",
          "no_demand_tags", "valid_signal")


def load_protocol():
    obj = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    old = prior.load_protocol()
    assert obj["schema_v"] == 1
    assert obj["prior_experiment_id"] == old["experiment_id"]
    assert obj["source"] == "hn_algolia_public_read_only"
    assert obj["hit_limit_per_query"] == MAX_HITS_PER_QUERY == 30
    assert obj["decision_rule"]["promote_to_production"] is False
    assert obj["controls"]["synthetic_not_external"] is True
    assert obj["controls"]["labels_author_defined_not_human_verified"] is True
    assert obj["controls"]["never_count_controls_in_live_results"] is True
    for key, val in (
        ("production_state_write", False), ("automatic_promotion", False),
        ("commercial_gate_influence", "NONE"), ("commercial_evidence_influence", "NONE"),
        ("private_datasets_access", False), ("paid_api_calls", False),
        ("raw_external_text_persisted", False),
    ):
        if obj["boundary"].get(key) != val:
            raise ValueError("Isolation violation: " + key)
    assert obj["baseline_definition"] == old["baseline_definition"]
    assert obj["expected_treatment_genes"] == old["expected_treatment_genes"]
    assert len(obj["holdout_topics"]) == 4
    names = [t["full"] for t in obj["holdout_topics"]]
    compact = [t["compact"] for t in obj["holdout_topics"]]
    domains = [t["domain"] for t in obj["holdout_topics"]]
    assert len(set(names)) == len(set(compact)) == len(set(domains)) == 4
    excluded = {t["full"] for t in old["holdout_topics"]}
    evolution = set(json.loads((ROOT / "data/arena/research-algorithm/latest.json")
                               .read_text(encoding="utf-8"))["benchmark"]["topics"])
    assert not set(names) & (evolution | excluded)
    assert not set(domains) & set(obj["excluded_topic_domains"])
    assert len(obj["excluded_topic_domains"]) >= 8
    for t in obj["holdout_topics"]:
        assert 2 <= len(t["full"].split()) <= 7
        assert 1 <= len(t["compact"].split()) <= 4
    return obj


def planned_queries(protocol):
    champion_report = json.loads((ROOT / "data/arena/research-algorithm/latest.json")
                                  .read_text(encoding="utf-8"))
    champ = champion_report["ranked"][0]
    if champ["genome_id"] != protocol["candidate_id"]:
        raise ValueError("Pinned champion identifier changed")
    return prior.plans(protocol, champ["genes"])


def synthetic_controls():
    # These are labelled synthetic test fixtures, not observations or human review.
    g = load_protocol()["baseline_definition"]
    pairs = [{"topic": "manual data entry", "query": "manual data entry workaround"}]
    good = {"objectID": "fixture-positive", "story_id": "fixture-positive",
            "comment_text": POSITIVE_TEXT}
    bad = {"objectID": "fixture-negative", "story_id": "fixture-negative",
           "comment_text": NEGATIVE_TEXT}
    one = prior.valid_thread_metrics(pairs, [[good]], g)
    zero = prior.valid_thread_metrics(pairs, [[bad]], g)
    positive = one["rejection_reasons"]["valid_signal"] == 1
    negative = zero["rejection_reasons"]["valid_signal"] == 0
    return {
        "fixture_type": "AUTHOR_LABELLED_SYNTHETIC_ONLY",
        "positive_expected": 1, "positive_observed": one["rejection_reasons"]["valid_signal"],
        "negative_expected": 0, "negative_observed": zero["rejection_reasons"]["valid_signal"],
        "pass": bool(positive and negative),
        "included_in_live_metrics": False,
    }


def diagnostic_metrics(pairs, batches, genes):
    # Exactly the dedup order and rejection predicates of the prior frozen holdout.
    base = prior.valid_thread_metrics(pairs, batches, genes)
    reasons = {key: 0 for key in STAGES}
    per_topic = {p["topic"]: dict(unique_objects=0, **{k: 0 for k in STAGES})
                 for p in pairs}
    visited = set()
    for pair, hits in zip(pairs, batches):
        topic = pair["topic"]
        for hit in hits:
            if not isinstance(hit, dict):
                continue
            object_id = str(hit.get("objectID") or "")
            if not object_id or object_id in visited:
                continue
            visited.add(object_id)
            per_topic[topic]["unique_objects"] += 1
            title = prior.clean_text(hit.get("title") or hit.get("story_title") or "")
            body = prior.clean_text(hit.get("comment_text") or hit.get("story_text") or "")
            url = str(hit.get("url") or hit.get("story_url") or "")
            stage = "valid_signal"
            if len(prior.text_tokens(topic) & prior.text_tokens(title + " " + body)) < genes["min_relevance_tokens"]:
                stage = "irrelevant"
            elif prior.is_vendor_content(title, body, url, "hn-algolia-routed") or prior.is_supply_offer(title, body, url, "hn-algolia-routed"):
                stage = "vendor_or_supply"
            elif prior.commercial_family((title + " " + body).lower()) == "other":
                stage = "unknown_family"
            elif not prior.buyer_voice_present(title, body):
                stage = "no_buyer_voice"
            else:
                tags = prior.demand_signal_type(
                    title, body, query_role="buyer", strong_pain_only=False,
                    seller_launch_guard=True, url=url, source="hn-algolia-routed",
                    vendor_content_guard=True, web_buyer_voice_guard=True,
                    supply_offer_guard=True, query_echo_guard=True, query=pair["query"])
                if not set(tags) & {"PAIN", "BUY_INTENT", "PAID_DEMAND"}:
                    stage = "no_demand_tags"
                elif not str(hit.get("story_id") or hit.get("objectID") or ""):
                    stage = "no_demand_tags"
            reasons[stage] += 1
            per_topic[topic][stage] += 1
    if reasons != base["rejection_reasons"]:
        raise ValueError("Diagnostic does not match frozen evaluator")
    if len(visited) != base["deduped_object_count"]:
        raise ValueError("Deduplication drift")
    for t, counts in per_topic.items():
        if sum(counts[k] for k in STAGES) != counts["unique_objects"]:
            raise ValueError("Stage accounting failed: " + t)
    return {"score": base, "stages": reasons, "per_topic": per_topic}


def verdict(baseline, treatment, valid_controls, full_success, decision):
    if not valid_controls:
        return "INVALID_CONTROL"
    if not full_success:
        return "INCONCLUSIVE_PROVIDER_FAILURE"
    a, b = baseline["score"], treatment["score"]
    improved = (
        b["unique_signal_threads"] >= a["unique_signal_threads"] +
        decision["candidate_min_unique_thread_gain"]
        and b["unique_signal_threads"] > 0
        and b["precision"] >= a["precision"] *
        decision["candidate_min_precision_ratio_vs_baseline"]
        and b["topic_coverage"] >= decision["candidate_min_topic_coverage"]
    )
    return "CANDIDATE_FOR_FUTURE_REPLICATION" if improved else "NO_DEMONSTRATED_GAIN"


async def execute():
    protocol = load_protocol()
    plans = planned_queries(protocol)
    controls = synthetic_controls()
    cutoff = int(datetime.now(timezone.utc).timestamp()) - 45 * 86400
    all_queries = {row["query"] for arm in plans.values() for row in arm}
    if len(plans["baseline"]) != 16 or len(plans["treatment"]) != 16:
        raise ValueError("Asymmetric query budget")
    if len(all_queries) > 32 or len(all_queries) < 16:
        raise ValueError("Unexpected source request count")
    if HN_ENDPOINT != "https://hn.algolia.com/api/v1/search_by_date":
        raise ValueError("Source endpoint drift")
    payloads = {}
    async with httpx.AsyncClient(timeout=20, follow_redirects=False, trust_env=False,
                                 headers={"User-Agent": "OXIBAY-Disjoint-Research-Holdout/1.0"}) as client:
        for query in sorted(all_queries):
            try:
                response = await client.get(
                    HN_ENDPOINT,
                    params={"query": query, "hitsPerPage": MAX_HITS_PER_QUERY,
                            "numericFilters": f"created_at_i>{cutoff}"})
                response.raise_for_status()
                doc = response.json()
                if not isinstance(doc, dict) or not isinstance(doc.get("hits"), list):
                    raise ValueError("Unrecognized provider data")
                payloads[query] = {"ok": True, "hits": doc["hits"]}
            except (httpx.HTTPError, ValueError, TypeError):
                payloads[query] = {"ok": False, "hits": []}
    result = {}
    for name, genes in (("baseline", protocol["baseline_definition"]),
                        ("treatment", protocol["expected_treatment_genes"])):
        pairs = plans[name]
        measure = diagnostic_metrics(pairs, [payloads[p["query"]]["hits"] for p in pairs], genes)
        result[name] = {
            "queries": len(pairs),
            "successful_queries": sum(bool(payloads[p["query"]]["ok"]) for p in pairs),
            "metrics": measure,
        }
    full = all(x["successful_queries"] == x["queries"] for x in result.values())
    outcome = verdict(result["baseline"]["metrics"], result["treatment"]["metrics"],
                      controls["pass"], full, protocol["decision_rule"])
    report = {
        "schema_v": 1, "experiment_id": protocol["experiment_id"],
        "protocol_sha256": hashlib.sha256(PROTOCOL.read_bytes()).hexdigest(),
        "prior_experiment_id": protocol["prior_experiment_id"],
        "prior_experiment_verdict": "NO_DEMONSTRATED_GAIN",
        "observed_at_utc": datetime.now(timezone.utc).isoformat(),
        "provider": "hn_algolia_public_read_only",
        "provider_unique_queries": len(all_queries),
        "cutoff_epoch": cutoff, "controls": controls, "results": result,
        "verdict": outcome, "validated_independent_rounds": 0,
        "required_independent_rounds": protocol["decision_rule"]["required_independent_rounds_before_validation"],
        "human_verified_external_labels": False,
        "topical_disjointness": "PREREGISTERED_MANUAL_JUDGMENT_NOT_SEMANTICALLY_CERTIFIED",
        "automatic_promotion": False, "commercial_gate_influence": "NONE",
        "raw_external_text_persisted": False, "production_state_write": False,
    }
    REPORT.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "verdict": outcome, "control_pass": controls["pass"],
        "queries_baseline": result["baseline"]["successful_queries"],
        "queries_treatment": result["treatment"]["successful_queries"],
        "baseline_threads": result["baseline"]["metrics"]["score"]["unique_signal_threads"],
        "treatment_threads": result["treatment"]["metrics"]["score"]["unique_signal_threads"],
        "report": str(REPORT),
    }, sort_keys=True))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute", action="store_true", help="explicit public HN read-only calls")
    args = parser.parse_args()
    protocol = load_protocol()
    planned_queries(protocol)
    if not args.execute:
        print(json.dumps({"mode": "PLAN_ONLY", "experiment_id": protocol["experiment_id"],
                          "planned_queries_per_arm": 16, "source": protocol["source"],
                          "production_state_write": False}))
        return
    asyncio.run(execute())


if __name__ == "__main__":
    main()
