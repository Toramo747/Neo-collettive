# SPDX-License-Identifier: BUSL-1.1
"""Read-only April HN matched-budget query A/B plus source-context review queue.

Arms differ in exactly one existing gene: query_mode mixed -> pain.
This is a screen for hypothesis generation, not commercial validation.
"""
from __future__ import annotations
import asyncio
import hashlib
import json
import sys
from collections import Counter
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import httpx

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
def load_script(name,relative):
    spec=spec_from_file_location(name,ROOT/relative)
    obj=module_from_spec(spec)
    spec.loader.exec_module(obj)
    return obj

screen=load_script("oxibay_screen_april","experiments/research-fresh-screen/screen.py")
previous=load_script("oxibay_october_context","experiments/research-october-e2e-context/run.py")
review=previous.review
v2=previous.diag
P=Path(__file__).with_name("protocol.json")
OUT=Path("/tmp/oxibay-research-april-pain-query-aggregates.json")
STAGES=tuple(v2.STAGES)
CONTEXTS=("applicant_offers","employer_job_posts","show_hn_projects","other_or_unknown")

def load():
    p=json.loads(P.read_text(encoding="utf-8"))
    august=screen.load()
    if p.get("schema_v")!=1 or p.get("provider_endpoint")!=screen.HN_ENDPOINT:
        raise ValueError("Provider schema mismatch")
    if p["window"]!={"id":"2026-04","start_epoch":1775001600,"end_epoch":1777593600}:
        raise ValueError("Experiment window drift")
    if p["topics_source"]!="experiments/research-fresh-screen/protocol.json" or (
        p["topic_domains"]!=[t["domain"] for t in august["topics"]]):
        raise ValueError("Topics were mutated after experiment design")
    if p["budget"]!={"queries_per_arm":16,"hits_per_query":30,"maximum_public_api_calls":32}:
        raise ValueError("Query budget changed")
    if p["arms"]!=["legacy_mixed","candidate_pain"]:
        raise ValueError("Arm definitions changed")
    mutation=p["candidate_mutation"]
    if (mutation["gene"],mutation["from"],mutation["to"],
        mutation["other_gene_changes_allowed"])!=("query_mode","mixed","pain",False):
        raise ValueError("Treatment mutation drift")
    if p["context_review"]!={"enable":True,"review_queue_only":True,
        "max_review_slots":8,"rank_known_applicant_or_hiring_or_show_hn_first":True,
        "never_reject_due_to_context":True}:
        raise ValueError("Context rule drift")
    rule=p["decision_rule"]
    if rule!={"require_all_queries":True,"min_baseline_relevant_hits":8,
              "min_unique_thread_gain":2,"min_signal_topic_coverage":2,
              "nondecreasing_signal_precision":True,
              "positive_label":"SCREEN_CANDIDATE_NOT_VALIDATED",
              "negative_label":"NO_REPRODUCIBLE_GAIN_DEMONSTRATED","automatic_promotion":False}:
        raise ValueError("Unapproved gate drift")
    must={"production_state_write":False,"commercial_gate_influence":"NONE",
          "commercial_evidence_influence":"NONE","prices_influence":"NONE",
          "private_data_used":False,"paid_api_calls":False,
          "raw_external_text_persisted":False,"source_urls_persisted":False,
          "source_ids_persisted":False,"query_strings_persisted":False,
          "automatic_promotion":False,"student_promotion":False,
          "human_verified":False,"independent_replications":0}
    for k,v in must.items():
        if p["safety"].get(k)!=v:raise ValueError("Safety contract drift: "+k)
    a=screen.plan(august)[0]["search_genes"]
    b={**a,"query_mode":"pain"}
    if a["query_mode"]!="mixed" or [k for k in a if a[k]!=b[k]]!=["query_mode"]:
        raise ValueError("Changed more than one search gene")
    left=screen.make_pairs(august,a)
    right=screen.make_pairs(august,b)
    if len(left)!=16 or len(right)!=16:
        raise ValueError("Asymmetric query plans")
    union=set(row["query"] for row in left+right)
    if len(union)>p["budget"]["maximum_public_api_calls"]:
        raise ValueError("Public provider request budget exceeded")
    return p,{"legacy_mixed":{"genes":a,"pairs":left},
              "candidate_pain":{"genes":b,"pairs":right}}

def shadow_review_stats(pairs,batches,genes):
    """Only aggregate context counts; never touch the base classifier score."""
    seen=set()
    items=[]
    by_source={c:{"valid_signal_rows":0,"total_deduped_rows":0} for c in CONTEXTS}
    for pair,hits in zip(pairs,batches):
        if len(hits)>30:raise ValueError("Hits query budget exceeded")
        for hit in hits:
            if not isinstance(hit,dict):continue
            oid=str(hit.get("objectID") or "")
            if not oid or oid in seen:continue
            seen.add(oid)
            stage=review.stage(pair["topic"],pair["query"],hit,genes)
            ctx=previous.context_for(hit)
            if ctx not in by_source:raise ValueError("Context policy mismatch")
            by_source[ctx]["total_deduped_rows"]+=1
            if stage=="valid_signal":
                by_source[ctx]["valid_signal_rows"]+=1
                # Stored only as in-memory category, not HN object ID or source text.
                items.append(ctx)
    if sum(v["total_deduped_rows"] for v in by_source.values())!=len(seen):
        raise ValueError("Source partition integrity failure")
    if sum(v["valid_signal_rows"] for v in by_source.values())!=len(items):
        raise ValueError("Source-valid partition integrity failure")
    known={"applicant_offers","employer_job_posts","show_hn_projects"}
    # Baseline queue is HN query/order. Shadow queue ranks known source contexts
    # first to prioritize independent adjudication of suspected supply confusion.
    n=p["context_review"]["max_review_slots"]
    baseline_top=items[:n]
    re_ranked=sorted(items,key=lambda c:(c not in known,CONTEXTS.index(c)))[:n]
    return {
        "source_categories":by_source,
        "accepted_records":len(items),
        "context_flagged_accepted_records":sum(v["valid_signal_rows"] for k,v in by_source.items() if k in known),
        "baseline_review_slots_used":len(baseline_top),
        "baseline_top_slots_known_source_count":sum(c in known for c in baseline_top),
        "context_first_review_slots_used":len(re_ranked),
        "context_first_top_slots_known_source_count":sum(c in known for c in re_ranked),
        "all_existing_accept_decisions_preserved":True,
        "review_queue_only":True
    }

def evaluate(p,plan,payload):
    output={}
    for name,arm in plan.items():
        pairs=arm["pairs"];g=arm["genes"]
        batches=[payload[q["query"]]["hits"] for q in pairs]
        query_ok=sum(int(payload[q["query"]]["ok"]) for q in pairs)
        metrics=v2.diagnostic_metrics(pairs,batches,g)
        score=metrics["score"]
        if (sum(metrics["stages"].values())!=score["deduped_object_count"]
            or metrics["stages"]["valid_signal"]!=score["signal_hits"]
            or score["unique_signal_threads"]>score["signal_hits"]):
            raise ValueError("Stage/score mismatch")
        context=shadow_review_stats(pairs,batches,g,p) if False else shadow_review_stats(pairs,batches,g,p)
        output[name]={"queries_ok":query_ok,
                      "deduplicated_objects":score["deduped_object_count"],
                      "relevant_hits":score["relevant_hits"],
                      "valid_signal_rows":score["signal_hits"],
                      "unique_signal_threads":score["unique_signal_threads"],
                      "topic_coverage":score["topic_coverage"],"precision":score["precision"],
                      "rejection_stages":{stage:int(metrics["stages"][stage]) for stage in STAGES},
                      "context_review":context,
                      "metric_integrity":True}
        if context["accepted_records"]!=score["signal_hits"]:
            raise ValueError("Review stage count does not agree with scorer")
    return output

def decide(p,out):
    a=out["legacy_mixed"];b=out["candidate_pain"]
    rule=p["decision_rule"]
    if a["queries_ok"]!=16 or b["queries_ok"]!=16:
        return "INCONCLUSIVE_PROVIDER_FAILURE"
    if a["relevant_hits"]<rule["min_baseline_relevant_hits"]:
        return "INCONCLUSIVE_WEAK_BASELINE"
    if (b["unique_signal_threads"]>=a["unique_signal_threads"]+rule["min_unique_thread_gain"]
        and b["topic_coverage"]>=rule["min_signal_topic_coverage"]
        and b["precision"]>=a["precision"]):
        return rule["positive_label"]
    return rule["negative_label"]

async def execute():
    p,plan=load()
    all_queries=sorted({r["query"] for arm in plan.values() for r in arm["pairs"]})
    if len(all_queries)>p["budget"]["maximum_public_api_calls"]:
        raise ValueError("Provider budget exceeded")
    payload={}
    async with httpx.AsyncClient(timeout=20,follow_redirects=False,trust_env=False,
                                 headers={"User-Agent":"OXIBAY-April-Query-AB-Shadow/1.0"}) as client:
        for q in all_queries:
            try:
                response=await client.get(screen.HN_ENDPOINT,params={
                    "query":q,"hitsPerPage":p["budget"]["hits_per_query"],
                    "numericFilters":
                        f"created_at_i>={p['window']['start_epoch']},created_at_i<{p['window']['end_epoch']}"})
                response.raise_for_status()
                doc=response.json()
                if not isinstance(doc,dict) or not isinstance(doc.get("hits"),list):
                    raise ValueError("Unrecognized HN payload")
                payload[q]={"ok":True,"hits":doc["hits"][:p["budget"]["hits_per_query"]]}
            except (httpx.HTTPError,ValueError,TypeError):
                payload[q]={"ok":False,"hits":[]}
    out=evaluate(p,plan,payload)
    verdict=decide(p,out)
    report={"schema_v":1,"experiment_id":p["experiment_id"],"source_month":p["window"]["id"],
            "provider_unique_queries":len(all_queries),
            "arms":out,"verdict":verdict,
            "measured_commercial_gain":False,"independently_validated":False,
            "human_labelled_cases":0,"independent_replications":0,
            "automatic_promotion":False,"production_state_write":False,
            "commercial_gate_influence":"NONE","raw_external_text_persisted":False,
            "source_ids_persisted":False,"source_urls_persisted":False,
            "query_strings_persisted":False}
    OUT.write_text(json.dumps(report,sort_keys=True,indent=2)+"\n")
    print(json.dumps({"status":verdict,"provider_unique_queries":len(all_queries),
          "arms":{name:{k:row[k] for k in (
            "queries_ok","relevant_hits","valid_signal_rows","unique_signal_threads","topic_coverage","precision")}
             for name,row in out.items()},
          "review_counts":{name:{"flagged_valid_rows":row["context_review"]["context_flagged_accepted_records"],
                "baseline_top8_flags":row["context_review"]["baseline_top_slots_known_source_count"],
                "context_first_top8_flags":row["context_review"]["context_first_top_slots_known_source_count"]}
             for name,row in out.items()},
          "human_verified":False,"production_unchanged":True},sort_keys=True))

def main():
    p,plan=load()
    if sys.argv[1:]==[]:
        print(json.dumps({"mode":"PLAN_ONLY","arms":len(plan),
            "queries_per_arm":16,"max_provider_queries":32,
            "no_promotion":True,"commercial_gate_influence":"NONE"},sort_keys=True))
    elif sys.argv[1:]==["--execute"]:
        asyncio.run(execute())
    else:
        raise SystemExit("Only --execute supported")

if __name__=="__main__":
    main()
