# SPDX-License-Identifier: BUSL-1.1
"""Bounded public replay of legacy demand predicates versus review-only context.

No full-score claim: relevance-to-commercial-topic is not evaluated here.
No raw/source identifiers/URLs written to logs or artifacts.
"""
from __future__ import annotations
import asyncio
import json
import sys
from collections import Counter
from importlib.util import module_from_spec,spec_from_file_location
from pathlib import Path
import httpx

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
def import_file(name,relative):
    spec=spec_from_file_location(name,ROOT/relative)
    mod=module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

previous=import_file("oxibay_september_context","experiments/research-september-context/check.py")
v2=previous.previous.v2
P=Path(__file__).with_name("protocol.json")
OUT=Path("/tmp/oxibay-context-guard-replay-anonymous.json")
STAGES=("vendor_or_supply","unknown_family","no_buyer_voice","no_demand_tags","passes_content_only")
OUT_KEYS=("examined","family_and_buyer","review_flags","passes_content_only",
          "positive_demand_tags","no_decision_changes","vendor_or_supply",
          "unknown_family","no_buyer_voice","no_demand_tags")

def load():
    p=json.loads(P.read_text(encoding="utf-8"))
    if p.get("schema_v")!=1 or p.get("period") != {
        "name":"2026-09","start_epoch":1788220800,"end_epoch":1790812800}:
        raise ValueError("Protocol/date drift")
    if p.get("contexts")!=["applicant_offers","employer_job_posts","show_hn_projects"]:
        raise ValueError("Context drift")
    if p.get("public_requests_ceiling")!=5:
        raise ValueError("Provider budget drift")
    if p["comparison"] != {
        "legacy":"existing production-derived source content predicates, with topic relevance intentionally omitted",
        "shadow":"identical existing content predicates plus source_context review annotations",
        "allow_relevance_or_commercial_scorer_changes":False,
        "allow_context_based_rejection":False,
        "evaluate_positive_tags":["PAIN","BUY_INTENT","PAID_DEMAND"],
        "measures":["family_and_buyer","legacy_content_filter_stages","content_only_positive_tags",
                    "needs_context_review","decision_changes"],
        "require_decision_changes":0}:
        raise ValueError("Evaluation contract drift")
    required={
        "no_customer_demand_claim":True,"no_verified_false_positive_claim":True,
        "no_independent_validation_claim":True,"source_text_persisted":False,
        "source_ids_persisted":False,"source_urls_persisted":False,
        "human_labelled_cases":0,"commercial_gate_influence":"NONE",
        "commercial_evidence_influence":"NONE","production_write":False,
        "price_cache_influence":"NONE","paid_api_calls":False,
        "automatic_promotion":False,"full_production_score_emulated":False}
    for k,v in required.items():
        if p["boundaries"].get(k)!=v:
            raise ValueError("Safety invariant violated: "+k)
    old=previous.load()
    if [x["key"] for x in old["contexts"]] != p["contexts"]:
        raise ValueError("Prior source definitions changed")
    return p,old

def legacy_content_stage(hit,query=""):
    """Uses exact predicates and guard order except unavailable topic relevance.

    This is intentionally NOT the complete commercial scorer.
    """
    prior=v2.prior
    title=prior.clean_text(hit.get("title") or hit.get("story_title") or "")
    body=prior.clean_text(hit.get("comment_text") or hit.get("story_text") or "")
    text=prior.clean_text((title+" "+body).strip())
    url=str(hit.get("url") or hit.get("story_url") or "")
    vendor=prior.is_vendor_content(title,body,url,"hn-algolia-routed")
    supply=prior.is_supply_offer(title,body,url,"hn-algolia-routed")
    family=prior.commercial_family(text)!="other"
    buyer=prior.buyer_voice_present(title,body)
    positives=set()
    if not (vendor or supply) and family and buyer:
        tags=prior.demand_signal_type(
            title,body,query_role="buyer",strong_pain_only=False,
            seller_launch_guard=True,url=url,source="hn-algolia-routed",
            vendor_content_guard=True,web_buyer_voice_guard=True,
            supply_offer_guard=True,query_echo_guard=True,query=query)
        positives=set(tags)&{"PAIN","BUY_INTENT","PAID_DEMAND"}
    if vendor or supply:stage="vendor_or_supply"
    elif not family:stage="unknown_family"
    elif not buyer:stage="no_buyer_voice"
    elif not positives:stage="no_demand_tags"
    else:stage="passes_content_only"
    return {"stage":stage,"family_and_buyer":bool(family and buyer),
            "positives":bool(positives),"vendor":bool(vendor or supply)}

def context_overlay(context,old):
    """Returns review queue annotation, retaining the exact legacy decision."""
    annotation=previous.route(context,family=old["family_and_buyer"],
                              buyer=old["family_and_buyer"],vendor_or_supply=old["vendor"])
    return {"stage":old["stage"],"review":annotation,
            "changed":False,"content_only_pass":old["stage"]=="passes_content_only"}

def compare_rows(context,rows,max_hits=60):
    if len(rows)>max_hits:
        raise ValueError("Unbounded public source results")
    seen=set();counts=Counter()
    for hit in rows:
        if not isinstance(hit,dict):continue
        obj=str(hit.get("objectID") or "")
        if not obj or obj in seen:continue
        seen.add(obj)
        old=legacy_content_stage(hit)
        shadow=context_overlay(context,old)
        if shadow["stage"]!=old["stage"] or shadow["changed"]:
            raise ValueError("Shadow altered legacy decision")
        counts["examined"]+=1
        counts["family_and_buyer"]+=int(old["family_and_buyer"])
        counts["review_flags"]+=int(shadow["review"]!="NO_HEURISTIC_OVERLAP")
        counts["passes_content_only"]+=int(shadow["content_only_pass"])
        counts["positive_demand_tags"]+=int(old["positives"])
        counts[old["stage"]]+=1
    if sum(counts[k] for k in STAGES)!=counts["examined"]:
        raise ValueError("Mutually exclusive legacy stages drifted")
    if counts["family_and_buyer"]<counts["passes_content_only"]:
        raise ValueError("Content guards inverted")
    if counts["passes_content_only"]>counts["review_flags"]:
        raise ValueError("Context flags missed positive content-only candidates")
    if counts["positive_demand_tags"]!=counts["passes_content_only"]:
        raise ValueError("Positive tags mismatch")
    return {key:int(counts.get(key,0)) for key in OUT_KEYS}

async def fetch_context(client,context,p):
    old=previous.load()
    range_filter=f"created_at_i>={p['period']['start_epoch']},created_at_i<{p['period']['end_epoch']}"
    max_hits=old["query_budget"]["per_context_hits"]
    if context["mode"]=="tagged_stories":
        hits=await previous.response_hits(client,previous.HN_ENDPOINT,
            {"tags":"show_hn","hitsPerPage":max_hits,"numericFilters":range_filter})
        if not hits:return {"status":"INCONCLUSIVE_EMPTY_SOURCE","counts":compare_rows(context["key"],[])}
        return {"status":"AGGREGATED_PREDICATES_ONLY","counts":compare_rows(context["key"],hits)}
    stories=await previous.response_hits(client,"https://hn.algolia.com/api/v1/search",
        {"query":context["exact_title"],"tags":"story","hitsPerPage":old["query_budget"]["story_lookup_max_hits"],
         "numericFilters":range_filter})
    exact=[x for x in stories if isinstance(x,dict)
           and str(x.get("title") or "").strip().casefold()==context["exact_title"].casefold()]
    if len(exact)!=1:return {"status":"INCONCLUSIVE_STORY_NOT_UNIQUE","counts":compare_rows(context["key"],[])}
    id_=str(exact[0].get("objectID") or "")
    if not id_.isascii() or not id_.isdigit():
        return {"status":"INCONCLUSIVE_STORY_ID_UNAVAILABLE","counts":compare_rows(context["key"],[])}
    hits=await previous.response_hits(client,previous.HN_ENDPOINT,{
        "tags":f"comment,story_{id_}","hitsPerPage":max_hits,"numericFilters":range_filter})
    if not hits:return {"status":"INCONCLUSIVE_EMPTY_SOURCE","counts":compare_rows(context["key"],[])}
    return {"status":"AGGREGATED_PREDICATES_ONLY","counts":compare_rows(context["key"],hits)}

async def execute():
    p,old=load()
    results={}
    async with httpx.AsyncClient(timeout=25,follow_redirects=False,trust_env=False,
                                 headers={"User-Agent":"OXIBAY-ContentGuard-Replay/1.0"}) as client:
        for ctx in old["contexts"]:
            try:
                results[ctx["key"]]=await fetch_context(client,ctx,p)
            except (httpx.HTTPError,ValueError,TypeError):
                results[ctx["key"]]={"status":"INCONCLUSIVE_PROVIDER_FAILURE",
                    "counts":compare_rows(ctx["key"],[])}
    total={key:sum(x["counts"][key] for x in results.values()) for key in OUT_KEYS}
    complete=all(row["status"]=="AGGREGATED_PREDICATES_ONLY" for row in results.values())
    report={"schema_v":1,"experiment_id":p["experiment_id"],
        "status":"CONTENT_GUARD_DIAGNOSTIC_COMPLETE" if complete else "INCONCLUSIVE_PARTIAL_SOURCE",
        "contexts":results,"overall":total,
        "legacy_vs_context_shadow_decision_changes":0,
        "strict_topic_relevance_evaluated":False,
        "human_labels":0,"verified_false_positives":0,"verified_false_negatives":0,
        "new_commercial_signals_claimed":0,
        "independent_validation":False,
        "source_text_persisted":False,"source_ids_persisted":False,
        "source_urls_persisted":False,"automatic_promotion":False,
        "production_write":False,"commercial_gate_influence":"NONE"}
    OUT.write_text(json.dumps(report,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    print(json.dumps({"status":report["status"],"contexts":results,
        "total":total,"decision_changes":0,"verified_false_positives":0,
        "verified_false_negatives":0,"human_labels":0},sort_keys=True))

def main():
    p,_=load()
    if sys.argv[1:]==[]:
        print(json.dumps({"mode":"PLAN_ONLY","max_requests":p["public_requests_ceiling"],
            "commercial_gate_influence":"NONE","production_write":False}))
    elif sys.argv[1:]==["--execute"]:asyncio.run(execute())
    else:raise SystemExit("Unsupported argument")

if __name__=="__main__":main()
