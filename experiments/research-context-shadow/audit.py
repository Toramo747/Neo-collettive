# SPDX-License-Identifier: BUSL-1.1
"""Read-only contextual-confounder probe. Only aggregates leave the Python process."""
from __future__ import annotations
import asyncio
import json
import sys
from collections import Counter
from importlib.util import spec_from_file_location, module_from_spec
from pathlib import Path

import httpx

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
old=ROOT/"experiments/research-holdout-v2/run.py"
spec=spec_from_file_location("oxibay_context_prior",old)
v2=module_from_spec(spec)
spec.loader.exec_module(v2)
from arena_research_algorithm import HN_ENDPOINT,clean_text

P=Path(__file__).with_name("protocol.json")
OUT=Path("/tmp/oxibay-research-context-shadow-aggregates.json")

def load():
    p=json.loads(P.read_text(encoding="utf-8"))
    if p.get("schema_v")!=1 or p.get("source")!="hn_algolia_public_read_only":
        raise ValueError("Unrecognized context experiment")
    if p["endpoint_comments"]!=HN_ENDPOINT:
        raise ValueError("Provider mismatch")
    if p["max_requests"]!=4 or p["max_comments_per_context"]!=60:
        raise ValueError("Request budget mismatch")
    if [x["key"] for x in p["contexts"]] != ["employment_supply","project_showcase"]:
        raise ValueError("Unexpected source contexts")
    if p["period"]!="2026-08" or p["start_epoch"]>=p["end_epoch"]:
        raise ValueError("Source period drift")
    required={"read_only_public_api":True,"raw_text_to_artifact":False,
              "raw_text_to_stdout":False,"source_ids_to_artifact":False,
              "source_ids_to_source_code":False,"source_urls_to_artifact":False,
              "paid_api_calls":False,"production_state_write":False,
              "commercial_gate_influence":"NONE","commercial_evidence_influence":"NONE",
              "automatic_promotion":False,"independent_validation_claim":False}
    for k,val in required.items():
        if p["boundary"].get(k)!=val:
            raise ValueError("Boundary violation: "+k)
    return p

def review_priority(context, *, buyer=False, family=False, vendor=False):
    """Pure triage annotation, never an automatic change to machine scoring."""
    if context=="employment_supply":
        return "SUPPLY_CONTEXT_REVIEW" if buyer or family else "LOW_PRIORITY_CONTEXT"
    if context=="project_showcase":
        if buyer and family:
            return "MIXED_CONTEXT_REVIEW"
        return "MIXED_CONTEXT_NO_ASSUMED_DEMAND"
    raise ValueError("Unapproved review context")

def analyze_public_records(context,hits,p):
    counts=Counter()
    seen=set()
    for row in hits:
        if not isinstance(row,dict):
            continue
        obj=str(row.get("objectID") or "")
        if not obj or obj in seen: continue
        seen.add(obj)
        title=clean_text(row.get("title") or row.get("story_title") or "")
        body=clean_text(row.get("comment_text") or row.get("story_text") or "")
        text=clean_text((title+" "+body).strip())
        url=str(row.get("url") or row.get("story_url") or "")
        vendor=v2.prior.is_vendor_content(title,body,url,"hn-algolia-routed")
        supply=v2.prior.is_supply_offer(title,body,url,"hn-algolia-routed")
        family=v2.prior.commercial_family(text)!="other"
        buyer=v2.prior.buyer_voice_present(title,body)
        counts["examined"]+=1
        counts["buyer_voice_heuristic"]+=int(buyer)
        counts["commercial_family_heuristic"]+=int(family)
        counts["vendor_or_supply_heuristic"]+=int(vendor or supply)
        counts["review_priority_"+review_priority(context,buyer=buyer,family=family,vendor=vendor)]+=1
    if counts["examined"]>p["max_comments_per_context"]:
        raise ValueError("Comment limit exceeded")
    return {k:int(counts.get(k,0)) for k in (
        "examined","buyer_voice_heuristic","commercial_family_heuristic",
        "vendor_or_supply_heuristic","review_priority_SUPPLY_CONTEXT_REVIEW",
        "review_priority_LOW_PRIORITY_CONTEXT",
        "review_priority_MIXED_CONTEXT_REVIEW",
        "review_priority_MIXED_CONTEXT_NO_ASSUMED_DEMAND")}

async def fetch_context(client,context,p):
    params={"query":context["exact_title"],"tags":"story",
            "hitsPerPage":p["max_story_lookup_hits"],
            "numericFilters":f"created_at_i>={p['start_epoch']},created_at_i<{p['end_epoch']}"}
    response=await client.get(p["endpoint_search"],params=params)
    response.raise_for_status()
    data=response.json()
    if not isinstance(data,dict) or not isinstance(data.get("hits"),list):
        raise ValueError("Malformed public story response")
    stories=[row for row in data["hits"] if isinstance(row,dict)
             and str(row.get("title") or "").strip().casefold()==context["exact_title"].casefold()]
    if len(stories)!=1:
        return {"status":"INCONCLUSIVE_STORY_NOT_UNIQUELY_FOUND","counts":analyze_public_records(context["key"],[],p)}
    story_id=str(stories[0].get("objectID") or "")
    if not story_id.isascii() or not story_id.isdigit():
        return {"status":"INCONCLUSIVE_STORY_ID_UNAVAILABLE","counts":analyze_public_records(context["key"],[],p)}
    params={"tags":f"comment,story_{story_id}","hitsPerPage":p["max_comments_per_context"],
            "numericFilters":f"created_at_i>={p['start_epoch']},created_at_i<{p['end_epoch']}"}
    response=await client.get(p["endpoint_comments"],params=params)
    response.raise_for_status()
    payload=response.json()
    if not isinstance(payload,dict) or not isinstance(payload.get("hits"),list):
        raise ValueError("Malformed public comment response")
    return {"status":"AGGREGATED_HEURISTICS_ONLY","counts":analyze_public_records(context["key"],payload["hits"],p)}

async def execute():
    p=load()
    outcomes={}
    async with httpx.AsyncClient(timeout=23,follow_redirects=False,trust_env=False,
                                 headers={"User-Agent":"OXIBAY-Context-Shadow/1.0"}) as client:
        for context in p["contexts"]:
            try:
                outcomes[context["key"]]=await fetch_context(client,context,p)
            except (httpx.HTTPError,ValueError,TypeError):
                outcomes[context["key"]]={"status":"INCONCLUSIVE_PROVIDER_FAILURE",
                    "counts":analyze_public_records(context["key"],[],p)}
    report={"schema_v":1,"experiment_id":p["experiment_id"],"contexts":outcomes,
        "status":"CONTEXT_DIAGNOSTIC_ONLY","human_reviews_completed":0,
        "classifier_false_positive_count_verified":0,
        "classifier_false_negative_count_verified":0,
        "source_text_persisted":False,"source_ids_persisted":False,
        "production_state_write":False,"commercial_gate_influence":"NONE",
        "automated_promotion":False,"independent_validation":False}
    OUT.write_text(json.dumps(report,sort_keys=True,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"status":report["status"],"contexts":outcomes,
          "human_reviews_completed":0,"classifier_false_positive_count_verified":0,
          "classifier_false_negative_count_verified":0},sort_keys=True))

def main():
    p=load()
    if sys.argv[1:]==[]:
        print(json.dumps({"mode":"PLAN_ONLY","context_count":len(p["contexts"]),
            "max_requests":p["max_requests"],"no_production_writes":True}))
    elif sys.argv[1:]==["--execute"]:asyncio.run(execute())
    else:raise SystemExit("Only --execute supported")

if __name__=="__main__":main()
