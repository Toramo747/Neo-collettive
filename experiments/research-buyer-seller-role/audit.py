# SPDX-License-Identifier: BUSL-1.1
"""Shadow-only first-person seller-role collision audit.

Never use role-risk as a production veto. Detect potentially confusing "I offer
automation services and I'm looking for clients" voice on public HN comments
that the pre-existing commercial classifier may treat as buyer demand.
"""
from __future__ import annotations

import asyncio
import json
import re
import sys
from collections import Counter
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import httpx

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))

def import_source(name,path):
    spec=spec_from_file_location(name,ROOT/path)
    mod=module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

screen=import_source("oxibay_seller_screen","experiments/research-fresh-screen/screen.py")
review=import_source("oxibay_seller_review","experiments/research-human-review/review.py")
october=import_source("oxibay_seller_context","experiments/research-october-e2e-context/run.py")
diag=review.v2
prior=diag.prior
P=Path(__file__).with_name("protocol.json")
OUT=Path("/tmp/oxibay-seller-role-collision-anonymous.json")
STAGES=tuple(diag.STAGES)
SOURCE_CATEGORIES=("applicant_offers","employer_job_posts","show_hn_projects","other_or_unknown")

# Conservative actor-oriented wording, applied to HN text ONLY in shadow.
# Not identical to source "who wants to be hired": role can be mixed within
# a discussion and it would be unsafe to automatically discard an entire thread.
SELLER_CUES=(
    re.compile(r"\b(?:i|we)\s+(?:currently\s+)?(?:offer|provide|sell)\s+(?:\w+\s+){0,5}(?:service|consulting|software|tool|app|automation|spreadsheet|support|work)\b",re.I),
    re.compile(r"\b(?:i'm|i am|we're|we are)\s+(?:currently\s+)?available\s+for\s+(?:freelance|contracts?|consulting|hire|work)\b",re.I),
    re.compile(r"\b(?:looking\s+for|seeking)\s+(?:new\s+)?(?:clients|customers|contracts|projects)\b",re.I),
    re.compile(r"\b(?:hire|contact|dm|email)\s+me\b",re.I),
)

def load():
    p=json.loads(P.read_text(encoding="utf-8"))
    frozen=screen.load()
    if p.get("schema_v")!=1 or p["preregistration"]["source"]!="hn_algolia_public_read_only":
        raise ValueError("Experiment schema drift")
    if p["preregistration"]["window"]!={"id":"2026-03","start_epoch":1772323200,"end_epoch":1775001600}:
        raise ValueError("Unapproved sample period")
    if p["preregistration"]["baseline_source"]!="experiments/research-fresh-screen/protocol.json":
        raise ValueError("Baseline source changed")
    if p["preregistration"]["topics"]!=4 or p["preregistration"]["queries"]!=16:
        raise ValueError("Query count changed")
    if p["preregistration"]["hits_per_query"]!=30 or p["preregistration"]["max_public_requests"]!=16:
        raise ValueError("Request ceiling changed")
    if p["preregistration"]["max_review_slots"]!=8:
        raise ValueError("Review budget changed")
    if p["roles"]["acceptance_policy"]!="NEVER_CHANGE_EXISTING_LABELS":
        raise ValueError("Unsafe seller veto")
    if p["minimum_quality"]!={"require_16_of_16_queries":True,
      "require_synthetic_positive_controls":True,
      "require_synthetic_negative_controls":True,
      "require_diagnostic_metric_integrity":True,
      "expect_exact_score_delta":0,"expect_all_existing_labels_preserved":True,
      "automatic_promotion":False,"independent_validations":0}:
        raise ValueError("Safety gate changed")
    must={"paid_api_calls":False,"production_state_write":False,
          "commercial_gate_influence":"NONE","commercial_evidence_influence":"NONE",
          "price_cache_influence":"NONE","student_promotion":False,
          "model_or_policy_weight_change":False,"commercial_threshold_change":False,
          "raw_source_text_persisted":False,"source_urls_persisted":False,
          "source_ids_persisted":False,"query_strings_persisted":False,
          "private_or_hidden_sets_read":False,"human_reviewed_cases":0,
          "automatic_promotion":False}
    for k,v in must.items():
        if p["boundary"].get(k)!=v:
            raise ValueError("Boundary drift: "+k)
    genes=screen.plan(frozen)[0]["search_genes"]
    queries=screen.make_pairs(frozen,genes)
    if len(queries)!=16 or len({q["query"] for q in queries})!=16:
        raise ValueError("Frozen query budget drift")
    return p,genes,queries

def seller_role_flag(title,body):
    text=" ".join(((title or "")+" "+(body or "")).split())
    return any(pattern.search(text) is not None for pattern in SELLER_CUES)

def audit(p,genes,pairs,batches):
    if len(pairs)!=16 or len(batches)!=16 or any(len(x)>30 for x in batches):
        raise ValueError("Too many source objects or changed query budget")
    measurement=diag.diagnostic_metrics(pairs,batches,genes)
    score=measurement["score"]
    stages=measurement["stages"]
    if (sum(stages.values())!=score["deduped_object_count"]
        or stages["valid_signal"]!=score["signal_hits"]
        or score["unique_signal_threads"]>score["signal_hits"]):
        raise ValueError("Legacy scorer diagnostic mismatch")
    seen=set()
    c=Counter()
    contexts={key:{"total":0,"accepted":0,"accepted_seller_role_flagged":0}
              for key in SOURCE_CATEGORIES}
    flagged_in_order=[]
    for pair,hits in zip(pairs,batches):
        for hit in hits:
            if not isinstance(hit,dict):continue
            oid=str(hit.get("objectID") or "")
            if not oid or oid in seen:continue
            seen.add(oid)
            stage=review.stage(pair["topic"],pair["query"],hit,genes)
            c[stage]+=1
            title=prior.clean_text(hit.get("title") or hit.get("story_title") or "")
            body=prior.clean_text(hit.get("comment_text") or hit.get("story_text") or "")
            cue=seller_role_flag(title,body)
            source_ctx=october.context_for(hit)
            if source_ctx not in contexts:raise ValueError("Unrecognized source context")
            entry=contexts[source_ctx]
            entry["total"]+=1
            entry["accepted"]+=int(stage=="valid_signal")
            entry["accepted_seller_role_flagged"]+=int(stage=="valid_signal" and cue)
            c["seller_role_cue_any_stage"]+=int(cue)
            c["accepted_seller_role_collision"]+=int(cue and stage=="valid_signal")
            c["accepted_without_seller_role_cue"]+=int(not cue and stage=="valid_signal")
            if stage=="valid_signal":
                flagged_in_order.append(bool(cue))
    if any(c[s]!=stages[s] for s in STAGES):
        raise ValueError("Buyer-voice audit and scorer disagree")
    if len(seen)!=score["deduped_object_count"]:
        raise ValueError("Deduplication disagree")
    if sum(x["accepted_seller_role_flagged"] for x in contexts.values())!=c["accepted_seller_role_collision"]:
        raise ValueError("Context flagged partition disagree")
    if c["accepted_seller_role_collision"]+c["accepted_without_seller_role_cue"]!=score["signal_hits"]:
        raise ValueError("Role count inflated signals")
    slots=p["preregistration"]["max_review_slots"]
    baseline_first=flagged_in_order[:slots]
    shadow_first=sorted(flagged_in_order,reverse=True)[:slots]
    return {
        "deduplicated_objects":score["deduped_object_count"],
        "relevant_hits":score["relevant_hits"],
        "signal_hits":score["signal_hits"],
        "unique_signal_threads":score["unique_signal_threads"],
        "topic_coverage":score["topic_coverage"],
        "precision":score["precision"],
        "rejection_stages":{key:int(stages[key]) for key in STAGES},
        "seller_role_cues_all_stages":int(c["seller_role_cue_any_stage"]),
        "accepted_seller_role_collision_count":int(c["accepted_seller_role_collision"]),
        "accepted_without_seller_role_cue":int(c["accepted_without_seller_role_cue"]),
        "source_contexts":contexts,
        "review_baseline_top8_flagged":sum(baseline_first),
        "review_shadow_top8_flagged":sum(shadow_first),
        "review_slots_used":len(baseline_first),
        "review_queue_changed_only":True,
        "legacy_accepted_labels_unchanged":True,
        "legacy_scores_unchanged":True,
        "independent_human_truth_available":False,
    }

def authored_controls():
    """Author-written toy examples test behavior; not source labels or external proof."""
    items=[
        ("seller_offer","I offer spreadsheet automation consulting. I'm looking for clients who need help with manual invoice workflows.",True),
        ("seller_clients","I'm looking for clients for my spreadsheet automation work. Manual invoice entry is frustrating.",True),
        ("seller_hire_me","Hire me for invoice automation projects and manual data entry consulting.",True),
        ("seller_freelance","I'm available for freelance spreadsheet automation work and client contracts.",True),
        ("buyer_need","I need a tool to automate our spreadsheet workflow because manual invoicing wastes time.",False),
        ("buyer_question","How do I automate spreadsheet invoice reconciliation without manual work?",False),
        ("buyer_recruiting","We are hiring someone to fix our manual data entry backlog.",False),
        ("buyer_switch","We need an alternative to our expensive invoicing software.",False),
        ("mixed_vendor_buyer","I offer consulting but I need a new inventory tool to manage my own stock.",True),
        ("ambiguous","I want help with an application and I have a spreadsheet.",False),
    ]
    flags=[{"name":name,"expected":label,"observed":seller_role_flag("",text)}
           for name,text,label in items]
    return {"type":"AUTHORED_SYNTHETIC_NOT_INDEPENDENT",
        "total":len(items),"passed":sum(x["expected"]==x["observed"] for x in flags),
        "positive_cases":sum(x["expected"] for x in flags),
        "negative_cases":sum(not x["expected"] for x in flags),
        "pass":all(x["expected"]==x["observed"] for x in flags),
        "human_verified_external_cases":0}

async def run():
    p,genes,pairs=load()
    controls=authored_controls()
    if not controls["pass"]:
        raise ValueError("Synthetic role controls failed")
    results={}
    failed=0
    async with httpx.AsyncClient(timeout=22,follow_redirects=False,trust_env=False,
            headers={"User-Agent":"OXIBAY-BuyerSeller-RoleShadow/1.0"}) as client:
        for pair in pairs:
            try:
                response=await client.get(screen.HN_ENDPOINT,params={
                    "query":pair["query"],"hitsPerPage":p["preregistration"]["hits_per_query"],
                    "numericFilters":f"created_at_i>={p['preregistration']['window']['start_epoch']},created_at_i<{p['preregistration']['window']['end_epoch']}"})
                response.raise_for_status()
                data=response.json()
                if not isinstance(data,dict) or not isinstance(data.get("hits"),list):
                    raise ValueError("Bad provider response")
                results[pair["query"]]=data["hits"][:30]
            except (ValueError,TypeError,httpx.HTTPError):
                failed+=1
                results[pair["query"]]=[]
    summary=audit(p,genes,pairs,[results[pair["query"]] for pair in pairs])
    status=("INCONCLUSIVE_PROVIDER_FAILURE" if failed else
            "INCONCLUSIVE_WEAK_SAMPLE" if summary["relevant_hits"]<8 else
            "SHADOW_ROLE_COLLISION_DIAGNOSTIC_ONLY")
    report={"schema_v":1,"experiment_id":p["experiment_id"],"status":status,
        "public_queries_ok":16-failed,"public_queries_planned":16,
        "synthetic_controls":controls,"metric":summary,
        "new_validated_buyers":0,"human_labelled_cases":0,"independent_replications":0,
        "role_review_flags_are_errors":False,
        "classifier_changed":False,"commercial_gate_influence":"NONE",
        "automatic_promotion":False,"production_state_write":False,
        "raw_source_text_persisted":False,"source_ids_persisted":False,
        "source_urls_persisted":False,"query_strings_persisted":False}
    OUT.write_text(json.dumps(report,sort_keys=True,indent=2)+"\n")
    print(json.dumps({"status":status,"queries_ok":16-failed,
        "relevant_hits":summary["relevant_hits"],
        "unique_signal_threads":summary["unique_signal_threads"],
        "seller_role_collision_review_count":summary["accepted_seller_role_collision_count"],
        "baseline_review_top8_flagged":summary["review_baseline_top8_flagged"],
        "shadow_review_top8_flagged":summary["review_shadow_top8_flagged"],
        "synthetic_control_passed":controls["passed"],
        "synthetic_control_total":controls["total"],
        "independent_human_confirmations":0,"production_state_unchanged":True},sort_keys=True))

def main():
    p,genes,pairs=load()
    c=authored_controls()
    if sys.argv[1:]==[]:
        print(json.dumps({"mode":"PLAN_ONLY","query_budget":len(pairs),
            "authored_control_pass":c["pass"],"authored_control_count":c["total"],
            "production_write":False},sort_keys=True))
    elif sys.argv[1:]==["--execute"]:asyncio.run(run())
    else:raise SystemExit("Unsupported command")

if __name__=="__main__":
    main()
