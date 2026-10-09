# SPDX-License-Identifier: BUSL-1.1
"""September source-context audit: public data in RAM, aggregate-only output."""
from __future__ import annotations

import asyncio
import json
import sys
from collections import Counter
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sp = spec_from_file_location("oxibay_context_v1", ROOT / "experiments/research-context-shadow/audit.py")
previous = module_from_spec(sp)
sp.loader.exec_module(previous)
from arena_research_algorithm import HN_ENDPOINT, clean_text  # noqa: E402

PROTOCOL = Path(__file__).with_name("protocol.json")
OUTPUT = Path("/tmp/oxibay-context-september-shadow-aggregates.json")
AGGREGATE_FIELDS = (
    "examined", "buyer_voice_heuristic", "commercial_family_heuristic",
    "vendor_or_supply_heuristic", "buyer_family_overlap",
    "buyer_family_non_vendor_overlap", "source_context_review_flags",
    "unflagged_objects"
)


def load():
    p = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    if p.get("schema_v") != 1 or p.get("source") != "hn_algolia_public_read_only":
        raise ValueError("Protocol drift")
    if p["period"] != {"name":"2026-09","start_epoch":1788220800,"end_epoch":1790812800}:
        raise ValueError("Temporal split changed")
    if [(c["key"],c["mode"]) for c in p["contexts"]] != [
        ("applicant_offers","story_comments"),
        ("employer_job_posts","story_comments"),
        ("show_hn_projects","tagged_stories")]:
        raise ValueError("Context definitions changed")
    if (p["contexts"][0]["exact_title"] != "Ask HN: Who wants to be hired? (September 2026)"
        or p["contexts"][1]["exact_title"] != "Ask HN: Who is hiring? (September 2026)"
        or p["contexts"][2]["tag"] != "show_hn"):
        raise ValueError("Source selection drift")
    if p["query_budget"] != {
        "max_total_provider_requests":5,"story_lookup_max_hits":20,
        "per_context_hits":60}:
        raise ValueError("Budget drift")
    if p["shadow_parameter"] != {
        "name":"source_context",
        "values":["applicant_offers","employer_job_posts","show_hn_projects"],
        "policy":"REVIEW_ONLY_NEVER_AUTO_REJECT",
        "affects_production_scoring":False}:
        raise ValueError("Shadow gene drift")
    required = {
        "production_write":False,"commercial_gate_influence":"NONE",
        "commercial_evidence_influence":"NONE","pricing_changes":False,
        "paid_api_calls":False,"raw_hn_text_persisted":False,
        "hn_identifiers_persisted":False,"hn_urls_persisted":False,
        "private_sets_used":False,"automatic_promotion":False,
        "human_labelled_cases":0}
    for k,v in required.items():
        if p["boundary"].get(k) != v:
            raise ValueError("Isolation violation: " + k)
    return p


def route(context, *, family:bool, buyer:bool, vendor_or_supply:bool)->str:
    """Review-priority annotation ONLY, never a classification decision."""
    if context not in ("applicant_offers","employer_job_posts","show_hn_projects"):
        raise ValueError("Unrecognized context")
    if not (family and buyer):
        return "NO_HEURISTIC_OVERLAP"
    if context == "applicant_offers":
        return "REVIEW_JOB_SEEKER_OFFER_CONTEXT"
    if context == "employer_job_posts":
        return "REVIEW_JOB_POSTING_NOT_SOFTWARE_DEMAND"
    # Product showcases can contain genuine problems; never suppress wholesale.
    return "REVIEW_MIXED_SHOWCASE_CONTEXT"


def aggregate(context, rows, p):
    metrics = Counter()
    seen = set()
    maximum = p["query_budget"]["per_context_hits"]
    if len(rows) > maximum:
        raise ValueError("Unexpected page length")
    for row in rows:
        if not isinstance(row, dict):
            continue
        oid = str(row.get("objectID") or "")
        if not oid or oid in seen:
            continue
        seen.add(oid)
        title = clean_text(row.get("title") or row.get("story_title") or "")
        body = clean_text(row.get("comment_text") or row.get("story_text") or "")
        joined = clean_text((title + " " + body).strip())
        url = str(row.get("url") or row.get("story_url") or "")
        family = previous.v2.prior.commercial_family(joined) != "other"
        buyer = previous.v2.prior.buyer_voice_present(title,body)
        vendor = bool(previous.v2.prior.is_vendor_content(title,body,url,"hn-algolia-routed")
                      or previous.v2.prior.is_supply_offer(title,body,url,"hn-algolia-routed"))
        category = route(context,family=family,buyer=buyer,vendor_or_supply=vendor)
        metrics["examined"] += 1
        metrics["commercial_family_heuristic"] += int(family)
        metrics["buyer_voice_heuristic"] += int(buyer)
        metrics["vendor_or_supply_heuristic"] += int(vendor)
        metrics["buyer_family_overlap"] += int(family and buyer)
        metrics["buyer_family_non_vendor_overlap"] += int(family and buyer and not vendor)
        metrics["source_context_review_flags"] += int(category != "NO_HEURISTIC_OVERLAP")
        metrics["unflagged_objects"] += int(category == "NO_HEURISTIC_OVERLAP")
    # Deliberately do not compute a new accepted/rejected label or commercial fitness.
    return {k:int(metrics.get(k,0)) for k in AGGREGATE_FIELDS}


async def response_hits(client, endpoint, params):
    response = await client.get(endpoint,params=params)
    response.raise_for_status()
    obj = response.json()
    if not isinstance(obj,dict) or not isinstance(obj.get("hits"),list):
        raise ValueError("Malformed public HN payload")
    return obj["hits"]


async def collect_context(client,context,p):
    start=p["period"]["start_epoch"]
    end=p["period"]["end_epoch"]
    nums=f"created_at_i>={start},created_at_i<{end}"
    n=p["query_budget"]["per_context_hits"]
    key=context["key"]
    if context["mode"]=="tagged_stories":
        rows=await response_hits(client,HN_ENDPOINT,{
            "tags":"show_hn","hitsPerPage":n,"numericFilters":nums})
        if not rows:
            return {"status":"INCONCLUSIVE_EMPTY_SOURCE","counts":aggregate(key,[],p)}
        return {"status":"AGGREGATED_HEURISTICS_ONLY","counts":aggregate(key,rows,p)}
    # Exact story match selected before API call; fail closed on 0 or 2+ matches.
    lookup=await response_hits(client,"https://hn.algolia.com/api/v1/search",{
        "query":context["exact_title"],"tags":"story",
        "hitsPerPage":p["query_budget"]["story_lookup_max_hits"],
        "numericFilters":nums})
    matches=[row for row in lookup if isinstance(row,dict)
             and str(row.get("title") or "").strip().casefold()==context["exact_title"].casefold()]
    if len(matches)!=1:
        return {"status":"INCONCLUSIVE_STORY_MISSING_OR_AMBIGUOUS","counts":aggregate(key,[],p)}
    sid=str(matches[0].get("objectID") or "")
    if not sid.isascii() or not sid.isdigit():
        return {"status":"INCONCLUSIVE_STORY_ID_INVALID","counts":aggregate(key,[],p)}
    comments=await response_hits(client,HN_ENDPOINT,{
        "tags":f"comment,story_{sid}",
        "hitsPerPage":n,"numericFilters":nums})
    if not comments:
        return {"status":"INCONCLUSIVE_EMPTY_SOURCE","counts":aggregate(key,[],p)}
    return {"status":"AGGREGATED_HEURISTICS_ONLY","counts":aggregate(key,comments,p)}


async def execute():
    p=load()
    outcomes={}
    async with httpx.AsyncClient(timeout=25, follow_redirects=False, trust_env=False,
                                 headers={"User-Agent":"OXIBAY-Research-September-Context/1.0"}) as client:
        for ctx in p["contexts"]:
            try:
                outcomes[ctx["key"]]=await collect_context(client,ctx,p)
            except (httpx.HTTPError,ValueError,TypeError):
                outcomes[ctx["key"]]={
                    "status":"INCONCLUSIVE_PROVIDER_ERROR",
                    "counts":aggregate(ctx["key"],[],p)}
    success=all(row["status"]=="AGGREGATED_HEURISTICS_ONLY" for row in outcomes.values())
    report={"schema_v":1,"experiment_id":p["experiment_id"],
        "status":"SHADOW_CONTEXT_EXPOSURE_MEASURED" if success else "INCONCLUSIVE_PARTIAL_CONTEXT_EXPOSURE",
        "context_summaries":outcomes,
        "proposed_parameter":"source_context",
        "policy":"REVIEW_ONLY_NEVER_AUTO_REJECT",
        "classifier_predictions_modified":False,
        "verified_false_positives":0,"verified_false_negatives":0,
        "human_labels":0,"representative_error_rate":False,
        "promotions":0,"production_write":False,"commercial_gate_influence":"NONE",
        "source_text_persisted":False,"source_ids_persisted":False,"raw_urls_persisted":False}
    OUTPUT.write_text(json.dumps(report,sort_keys=True,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"status":report["status"],
        "context_summaries":outcomes,
        "human_labels":0,"promotions":0,
        "verified_false_positives":0,
        "verified_false_negatives":0},sort_keys=True))


def main():
    p=load()
    if sys.argv[1:]==[]:
        print(json.dumps({"mode":"PLAN_ONLY","contexts":len(p["contexts"]),
            "maximum_provider_requests":p["query_budget"]["max_total_provider_requests"],
            "public_read_only":True,"automatic_promotion":False}))
    elif sys.argv[1:]==["--execute"]:
        asyncio.run(execute())
    else:
        raise SystemExit("Only --execute is accepted")


if __name__=="__main__":
    main()
