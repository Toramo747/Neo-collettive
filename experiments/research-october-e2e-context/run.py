# SPDX-License-Identifier: BUSL-1.1
"""October full topic-query retrieval: matched legacy vs shadow review annotation.

16 public queries total, single immutable in-memory snapshot for both arms.
Source-context annotations cannot change any existing classifier result.
"""
from __future__ import annotations
import asyncio
import json
import sys
from collections import Counter
from importlib.util import spec_from_file_location,module_from_spec
from pathlib import Path
import httpx

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
def local(name,path):
    spec=spec_from_file_location(name,ROOT/path)
    mod=module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

screen=local("oxibay_e2e_screen","experiments/research-fresh-screen/screen.py")
review=local("oxibay_e2e_review","experiments/research-human-review/review.py")
diag=review.v2

P=Path(__file__).with_name("protocol.json")
OUT=Path("/tmp/oxibay-october-e2e-context-aggregate.json")
STAGES=tuple(diag.STAGES)
CONTEXTS=("applicant_offers","employer_job_posts","show_hn_projects","other_or_unknown")


def load():
    p=json.loads(P.read_text(encoding="utf-8"))
    old=screen.load()
    expected=[{"domain":x["domain"],"full":x["full"],"compact":x["compact"]} for x in old["topics"]]
    if p.get("schema_v")!=1 or p.get("source")!="hn_algolia_public_read_only":
        raise ValueError("Protocol schema/source drift")
    if p["source_window"]!={"id":"2026-10-01_to_2026-10-09_utc_exclusive",
                            "start_epoch":1790812800,"end_epoch":1791504000}:
        raise ValueError("Future/test window changed")
    if p["topics_source"]!="experiments/research-fresh-screen/protocol.json" or p["topics"]!=expected:
        raise ValueError("Frozen topic drift")
    baseline=screen.plan(old)[0]
    if baseline["id"]!="matched_baseline" or p["fixed_baseline"]!=baseline["search_genes"]:
        raise ValueError("Search gene drift")
    if p["query_budget"]!={"per_topic":4,"total":16,"hits_per_query":30,"max_public_requests":16}:
        raise ValueError("Query budget drift")
    if p["context_rules"]!={"applicant_offers":"ask hn: who wants to be hired?",
                            "employer_job_posts":"ask hn: who is hiring?",
                            "show_hn_projects":"show hn:",
                            "unrecognized":"other_or_unknown",
                            "effect":"REVIEW_QUEUE_ANNOTATION_ONLY"}:
        raise ValueError("Context rules changed")
    if p["arms"]!=["matched_legacy","same_scoring_with_source_context_review_only"]:
        raise ValueError("Arm definition changed")
    if p["decision_contract"]!={"minimum_relevant_baseline":8,
        "minimum_unique_threads_for_descriptive_result":1,
        "expected_score_difference":0,"automatic_promotion":False,
        "validated_independent_rounds":0,"precisions_compared_on_identical_corpus":True}:
        raise ValueError("Promotion / decision contract drift")
    must={"raw_source_content_persisted":False,"source_ids_persisted":False,
          "source_urls_persisted":False,"queries_logged":False,
          "private_sets_accessed":False,"production_write":False,
          "commercial_gate_influence":"NONE","commercial_evidence_influence":"NONE",
          "pricing_influence":"NONE","paid_api_calls":False,
          "human_reviewed":False,"automatic_promotion":False}
    for key,val in must.items():
        if p["safety"].get(key)!=val:
            raise ValueError("Safety contract changed: "+key)
    pairs=screen.make_pairs(old,p["fixed_baseline"])
    if len(pairs)!=16 or len({x["query"] for x in pairs})!=16:
        raise ValueError("Baseline pairs not 16 unique queries")
    return p,pairs


def context_for(hit):
    """Parent story title only; never infer buyers from comment content."""
    raw=str(hit.get("story_title") or hit.get("title") or "").strip().casefold()
    # Compare exact top-level titles by prefix. An author's mention inside a
    # comment body is not an authority to assign a discussion source type.
    if raw.startswith("ask hn: who wants to be hired?"):
        return "applicant_offers"
    if raw.startswith("ask hn: who is hiring?"):
        return "employer_job_posts"
    if raw.startswith("show hn:"):
        return "show_hn_projects"
    return "other_or_unknown"


def evaluate(pairs,batches,genes):
    """Fixed in-memory records are shared between scorer and context review.

    Outputs only anonymous counts. Dedupe order identical to diagnostic_metrics.
    """
    if len(pairs)!=16 or len(batches)!=16 or any(len(x)>30 for x in batches):
        raise ValueError("Unexpected query/hit budget")
    baseline=diag.diagnostic_metrics(pairs,batches,genes)
    score=baseline["score"]
    stages=baseline["stages"]
    if (sum(stages.values())!=score["deduped_object_count"]
        or stages["valid_signal"]!=score["signal_hits"]
        or score["unique_signal_threads"]>score["signal_hits"]):
        raise ValueError("Diagnostic/scorer integrity failed")
    seen=set()
    counted=Counter()
    per_context={context:{"examined":0,"valid_signal":0,"review_queue_positive":0} for context in CONTEXTS}
    for pair,items in zip(pairs,batches):
        for hit in items:
            if not isinstance(hit,dict):
                continue
            identifier=str(hit.get("objectID") or "")
            if not identifier or identifier in seen:continue
            seen.add(identifier)
            stage=review.stage(pair["topic"],pair["query"],hit,genes)
            counted[stage]+=1
            context=context_for(hit)
            x=per_context[context]
            x["examined"]+=1
            if stage=="valid_signal":
                x["valid_signal"]+=1
                # Only known source categories go to additional manual review;
                # all classifications/accepted threads remain unchanged.
                if context!="other_or_unknown":
                    x["review_queue_positive"]+=1
    if set(counted)-set(STAGES) or any(counted[x]!=stages[x] for x in STAGES):
        raise ValueError("Review classifier mismatch with exact baseline stages")
    if len(seen)!=score["deduped_object_count"]:
        raise ValueError("Global dedup mismatch")
    if sum(x["valid_signal"] for x in per_context.values())!=score["signal_hits"]:
        raise ValueError("Context partition mismatch")
    positive=sum(x["review_queue_positive"] for x in per_context.values())
    if positive>score["signal_hits"]:raise ValueError("Context annotation inflated evidence")
    # The "shadow" branch cannot change the baseline; identical in-memory hits,
    # identical genes and no changes to a single label or scoring count.
    return {
        "queries":len(pairs),"deduplicated_objects":score["deduped_object_count"],
        "relevant_hits":score["relevant_hits"],"signal_hits":score["signal_hits"],
        "unique_signal_threads":score["unique_signal_threads"],
        "topic_coverage":score["topic_coverage"],"precision":score["precision"],
        "baseline_stage_counts":{stage:int(stages[stage]) for stage in STAGES},
        "context":per_context,"review_queue_positive_records":positive,
        "baseline_and_shadow_equal_scores":True,
        "baseline_and_shadow_equal_labels":True,
        "delta_unique_threads":0,"delta_precision":0.0,
        "metric_integrity":True
    }


async def execute():
    p,pairs=load()
    batches=[]
    failures=0
    # No query text, source text or identifiers enter logs or report.
    async with httpx.AsyncClient(timeout=22,follow_redirects=False,trust_env=False,
                                 headers={"User-Agent":"OXIBAY-October-Matched-Context-Shadow/1.0"}) as client:
        for pair in pairs:
            try:
                response=await client.get(screen.HN_ENDPOINT,params={
                    "query":pair["query"],"hitsPerPage":30,
                    "numericFilters":
                        f"created_at_i>={p['source_window']['start_epoch']},created_at_i<{p['source_window']['end_epoch']}"})
                response.raise_for_status()
                payload=response.json()
                if not isinstance(payload,dict) or not isinstance(payload.get("hits"),list):
                    raise ValueError("Provider response malformed")
                batches.append(payload["hits"][:30])
            except (httpx.HTTPError,ValueError,TypeError):
                failures+=1
                batches.append([])
    assessment=evaluate(pairs,batches,p["fixed_baseline"])
    if failures:
        verdict="INCONCLUSIVE_PROVIDER_FAILURE"
    elif assessment["relevant_hits"]<p["decision_contract"]["minimum_relevant_baseline"]:
        verdict="INCONCLUSIVE_WEAK_BASELINE"
    elif assessment["unique_signal_threads"]<p["decision_contract"]["minimum_unique_threads_for_descriptive_result"]:
        verdict="INCONCLUSIVE_NO_SIGNAL_THREADS"
    else:
        verdict="NO_COMPARATIVE_GAIN_REVIEW_ONLY"
    report={"schema_v":1,"experiment_id":p["experiment_id"],
            "status":verdict,
            "public_queries_completed":len(pairs)-failures,
            "public_queries_planned":16,
            "matched_search_queries_same_for_both_arms":True,
            "frozen_relevance_gate_applied":True,
            "assessment":assessment,
            "human_verified":False,"independent_replications":0,
            "commercial_validation":False,"context_manual_reviews_completed":0,
            "validated_source_buyer_cases":0,
            "automatic_promotion":False,"production_write":False,
            "commercial_gate_influence":"NONE",
            "source_ids_persisted":False,"source_text_persisted":False,
            "source_urls_persisted":False}
    OUT.write_text(json.dumps(report,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    print(json.dumps({
        "status":verdict,
        "queries_ok":report["public_queries_completed"],
        "matched_relevant":assessment["relevant_hits"],
        "baseline_threads":assessment["unique_signal_threads"],
        "context_annotated_valid_records":assessment["review_queue_positive_records"],
        "context_counts":assessment["context"],
        "score_delta":0,"labels_delta":0,
        "verified_buyer_cases":0},sort_keys=True))


def main():
    p,pairs=load()
    if sys.argv[1:]==[]:
        print(json.dumps({"mode":"PLAN_ONLY","query_count":len(pairs),
            "maximum_public_requests":p["query_budget"]["max_public_requests"],
            "no_production_write":True,"zero_independent_validations":True}))
    elif sys.argv[1:]==["--execute"]:
        asyncio.run(execute())
    else:
        raise SystemExit("Unknown arguments")


if __name__=="__main__":
    main()
