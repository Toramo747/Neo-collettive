"""Bounded, high-recall public HN file-access screening. No commercial writes.

Repeat the 4 fixed public-week queries with a higher per-query retrieval limit.
Provider nbHits and exhaustive flags distinguish complete retrieval from a cap.
The output is anonymous aggregate only and NEVER verified customer demand.
"""
from __future__ import annotations

import asyncio
from collections import Counter
import hashlib
import hmac
from importlib.util import module_from_spec, spec_from_file_location
import json
import os
from pathlib import Path
import sys

import httpx

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
_spec=spec_from_file_location("ipd_full_sample_prior",Path(__file__).with_name("file_access_audit.py"))
prior=module_from_spec(_spec)
_spec.loader.exec_module(prior)
hn=prior.hn
MAX_QUERIES=4
MAX_HITS=500
OUTPUT=Path("/tmp/oxibay-ipd-file-access-completeness-aggregates.json")

def review(batches: list[dict], *, key: bytes) -> dict:
    windows=prior.protocol()
    if len(windows)!=MAX_QUERIES or len(batches)!=MAX_QUERIES:
        raise ValueError("Changed frozen query count")
    base={
        "schema_v":1, "mode":"high_recall_hn_file_access_shadow",
        "original_first_run_threads":8, "subsequent_first_30_run_threads":9,
        "exact_original_cases_replayed":False,
        "max_public_queries":MAX_QUERIES, "max_hits_per_query":MAX_HITS,
        "commercial_gate_influence":"NONE", "production_state_write":False,
        "human_labels":0, "verified_independent_buyers":0,
        "buyer_identity_inferred_from_comments":False,
        "raw_external_content_persisted":False, "source_ids_persisted":False,
        "query_strings_persisted":False, "automatic_promotion":False,
    }
    if any(not isinstance(b,dict) or b.get("ok") is not True for b in batches):
        return {**base,"status":"INCONCLUSIVE_PROVIDER_FAILURE"}
    coverage=[]
    full={}
    top30=set()
    rejected=Counter()
    for window,batch in zip(windows,batches):
        hits=batch.get("hits")
        total=batch.get("nbHits")
        exact=batch.get("exhaustiveNbHits")
        if (not isinstance(hits,list) or len(hits)>MAX_HITS
                or not isinstance(total,int) or isinstance(total,bool) or total<0
                or total<len(hits)):
            raise ValueError("Untrusted provider payload")
        covered=bool(total==len(hits) and exact is True)
        coverage.append({
            "week":window["week"], "returned":len(hits),"reported_matches":total,
            "exhaustive_provider_count":exact is True,
            "complete":covered,
        })
        for i,hit in enumerate(hits):
            if not isinstance(hit,dict):
                rejected["non_object"]+=1
                continue
            when=hit.get("created_at_i")
            if not isinstance(when,int) or isinstance(when,bool) or not (window["start"]<=when<window["end"]):
                rejected["outside_time_filter"]+=1
                continue
            rows=hn.convert([hit],key=key,topic=prior.QUERY)
            if not rows:
                rejected["existing_screen_rejected"]+=1
                continue
            row=rows[0]
            token=row["request_id"]
            if i<30:top30.add(token)
            title,body=hn.text_of(hit)
            text=title+" "+body
            group=full.setdefault(token,{
                "times":[], "comments":0,
                "weak_overlap":False, "seller_risk":False,
                "no_file_context":False, "explicit":False,
                "themes":set(),
            })
            group["times"].append(when)
            group["comments"]+=1
            overlap=prior.query_relevance(title,body,prior.QUERY,{"search_alias_used":prior.QUERY}).get("overlap") or []
            group["weak_overlap"] |= len(overlap)<2
            group["seller_risk"] |= bool(prior.SELLER_RISK.search(text))
            group["no_file_context"] |= not bool(prior.FILE_CONTEXT.search(text))
            group["explicit"] |= row["explicit_solution_request"]
            group["themes"].update(kind for kind,regex in prior.TOPIC_TYPES.items() if regex.search(text))
    summary=Counter()
    weekly=[0]*4
    for row in full.values():
        summary["candidate_threads"]+=1
        summary["candidate_comments"]+=row["comments"]
        summary["multi_comment_threads"]+=row["comments"]>1
        summary["weak_topic_overlap_threads"]+=row["weak_overlap"]
        summary["seller_flag_threads"]+=row["seller_risk"]
        summary["missing_file_noun_threads"]+=row["no_file_context"]
        summary["explicit_request_machine_threads"]+=row["explicit"]
        summary["needs_context_review"]+=(row["weak_overlap"] or row["seller_risk"] or row["no_file_context"] or not row["themes"])
        for category in row["themes"]:summary["theme_"+category]+=1
        summary["theme_unspecified"]+=not bool(row["themes"])
        first=min(row["times"])
        # The oldest comment's publication week owns each thread for counting.
        for w in windows:
            if w["start"]<=first<w["end"]:
                weekly[w["week"]]+=1
                break
    complete=all(c["complete"] for c in coverage)
    return {
        **base,
        "status":"EXPLORATORY_RETRIEVAL_COMPLETE" if complete else "INCONCLUSIVE_SOURCE_CAPPED_OR_APPROXIMATE",
        "all_source_windows_complete":complete,
        "provider_coverage":coverage,
        "all_unique_candidate_threads":summary["candidate_threads"],
        "first_30_per_week_candidate_threads":len(top30),
        "additional_candidates_vs_first_30":max(0,summary["candidate_threads"]-len(top30)),
        "week_thread_counts_oldest_comment":weekly,
        "counts":{key:int(summary[key]) for key in (
            "candidate_comments","multi_comment_threads","weak_topic_overlap_threads",
            "seller_flag_threads","missing_file_noun_threads",
            "explicit_request_machine_threads","needs_context_review",
            "theme_access_control","theme_sharing_sync","theme_retrieval","theme_unspecified")},
        "screen_rejected_count":int(rejected["existing_screen_rejected"]),
        "out_of_window_count":int(rejected["outside_time_filter"]),
        "estimated_market_growth":None,
        "validated_customer_demand":False,
    }


async def execute():
    batches=[]
    async with httpx.AsyncClient(timeout=24,follow_redirects=False,trust_env=False,
            headers={"User-Agent":"OXIBAY-IPD-HN-Coverage-Shadow/1.0"}) as client:
        for window in prior.protocol():
            try:
                response=await client.get(hn.ENDPOINT,params={
                    "query":prior.QUERY,"hitsPerPage":MAX_HITS,
                    "numericFilters":f"created_at_i>={window['start']},created_at_i<{window['end']}",
                })
                response.raise_for_status()
                doc=response.json()
                if not isinstance(doc,dict) or not isinstance(doc.get("hits"),list):
                    raise ValueError("Bad HN response")
                batches.append({
                    "ok":True,"hits":doc["hits"],
                    "nbHits":doc.get("nbHits"),
                    "exhaustiveNbHits":doc.get("exhaustiveNbHits"),
                })
            except (httpx.HTTPError,ValueError,TypeError):
                batches.append({"ok":False})
    result=review(batches,key=os.urandom(32))
    OUTPUT.write_text(json.dumps(result,sort_keys=True,indent=2)+"\n")
    print(json.dumps(result,sort_keys=True))


if __name__=="__main__":
    if sys.argv[1:]==["--execute"]:
        asyncio.run(execute())
    elif not sys.argv[1:]:
        print(json.dumps({"mode":"PLAN_ONLY","max_queries":MAX_QUERIES,
                          "max_hits_per_query":MAX_HITS,"commercial_gate_influence":"NONE"}))
    else:
        raise SystemExit("Unsupported mode")
