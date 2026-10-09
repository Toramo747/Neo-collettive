# SPDX-License-Identifier: BUSL-1.1
"""Conditional topic relevance on predeclared public HN source contexts.

This is NOT end-to-end search retrieval: HN queries select source THREAD CONTEXT,
not the four benchmark TOPICS. It is a diagnostic audit only; no promotion.
"""
from __future__ import annotations

import asyncio
import json
import sys
from importlib.util import spec_from_file_location, module_from_spec
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

def load_script(name, path):
    spec = spec_from_file_location(name, ROOT / path)
    obj = module_from_spec(spec)
    spec.loader.exec_module(obj)
    return obj

replay = load_script("oxibay_topic_replay_236", "experiments/research-context-guard-replay/check.py")
screen = load_script("oxibay_topic_screen_232", "experiments/research-fresh-screen/screen.py")
diag = replay.v2
P = Path(__file__).with_name("protocol.json")
OUT = Path("/tmp/oxibay-context-topic-relevance-anonymous.json")

def load():
    p = json.loads(P.read_text(encoding="utf-8"))
    if p.get("schema_v") != 1 or p.get("source") != "hn_algolia_public_read_only":
        raise ValueError("Unsupported protocol")
    if p["period"] != {"name":"2026-09","start_epoch":1788220800,"end_epoch":1790812800}:
        raise ValueError("Period drift")
    if p["max_public_requests"] != 5 or p["max_records_per_context"] != 60:
        raise ValueError("Unapproved cost increase")
    expected_ctx = ["applicant_offers","employer_job_posts","show_hn_projects"]
    if p["contexts"] != expected_ctx:
        raise ValueError("Unapproved source contexts")
    if p["comparison_type"] != "fixed_source_corpus_with_counterfactual_topic_relevance_not_end_to_end_retrieval":
        raise ValueError("Comparator meaning changed")
    if p["topics_source"] != "experiments/research-fresh-screen/protocol.json":
        raise ValueError("Frozen topic provenance changed")
    frozen = screen.load()
    expected_topics = [{"domain":t["domain"],"compact":t["compact"]} for t in frozen["topics"]]
    if p["topics"] != expected_topics or len(p["topics"]) != 4:
        raise ValueError("Frozen experiment topics modified")
    genes = screen.plan(frozen)[0]["search_genes"]
    if genes != p["frozen_baseline"] or genes["min_relevance_tokens"] != 1:
        raise ValueError("Unapproved genome/gate mutation")
    q, old = replay.load()
    if q["period"] != p["period"]:
        raise ValueError("Previous September study drift")
    must = {
      "production_write":False,"commercial_gate_influence":"NONE",
      "commercial_evidence_influence":"NONE","price_cache_influence":"NONE",
      "private_sets_accessed":False,"paid_api_calls":False,
      "raw_source_text_persisted":False,"source_ids_persisted":False,
      "source_urls_persisted":False,"human_labels":0,
      "independent_confirmations":0,"automatic_promotion":False,
      "source_context_used_to_change_label":False}
    for k,v in must.items():
        if p["boundaries"].get(k) != v:
            raise ValueError("Boundary changed: "+k)
    return p, old

def summarize_context(context, rows, p):
    if len(rows) > p["max_records_per_context"]:
        raise ValueError("Unbounded source content")
    # Dedup once, before both scorer and diagnostic. In-memory source IDs never persist.
    seen=set()
    unique=[]
    for hit in rows:
        if not isinstance(hit, dict):
            continue
        key=str(hit.get("objectID") or "")
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(hit)
    base=replay.compare_rows(context,unique,p["max_records_per_context"])
    stage_overview={}
    total_topic_signals=0
    for t in p["topics"]:
        topic=t["compact"]
        # This is a fixed, synthetic role tag; no search with this query was run.
        query=topic+" problem"
        pairs=[{"topic":topic,"query":query}]
        measurement=diag.diagnostic_metrics(pairs,[unique],p["frozen_baseline"])
        score=measurement["score"]
        stages=measurement["stages"]
        if (score["signal_hits"] != stages["valid_signal"]
            or sum(stages.values()) != len(unique)
            or score["unique_signal_threads"] > score["signal_hits"]
            or score["relevant_hits"] > len(unique)):
            raise ValueError("Frozen score/diagnostic accounting disagrees")
        if score["signal_hits"] > base["passes_content_only"]:
            raise ValueError("Topic-gated signals exceed fixed-corpus content positives")
        stage_overview[t["domain"]]={
            "topic_relevant_rows":score["relevant_hits"],
            "topic_content_positive_rows":score["signal_hits"],
            "topic_unique_discussion_threads":score["unique_signal_threads"],
            "rejection_irrelevant":stages["irrelevant"],
            "rejection_other_stages_total":sum(v for k,v in stages.items()
                                                if k not in ("irrelevant","valid_signal")),
            "stage_integrity":True,
        }
        total_topic_signals += score["signal_hits"]
    return {
        "records_examined":len(unique),
        "content_only_positive_records":base["passes_content_only"],
        "buyer_family_overlaps":base["family_and_buyer"],
        "source_context_review_flags":base["review_flags"],
        "topic_record_positive_evaluations":total_topic_signals,
        "by_domain":stage_overview,
        "legacy_decision_changes":0,
        "context_only_review_queue":True,
    }

async def get_public_rows(client,ctx,p,previous):
    numeric=f"created_at_i>={p['period']['start_epoch']},created_at_i<{p['period']['end_epoch']}"
    n=p["max_records_per_context"]
    if ctx["mode"]=="tagged_stories":
        return await previous.response_hits(client,previous.HN_ENDPOINT,{
            "tags":"show_hn","hitsPerPage":n,"numericFilters":numeric})
    stories=await previous.response_hits(client,"https://hn.algolia.com/api/v1/search",{
        "query":ctx["exact_title"],"tags":"story",
        "hitsPerPage":previous.load()["query_budget"]["story_lookup_max_hits"],
        "numericFilters":numeric})
    exact=[x for x in stories if isinstance(x,dict)
           and str(x.get("title") or "").strip().casefold()==ctx["exact_title"].casefold()]
    if len(exact)!=1:
        return None
    story_id=str(exact[0].get("objectID") or "")
    if not story_id.isascii() or not story_id.isdigit():
        return None
    return await previous.response_hits(client,previous.HN_ENDPOINT,{
        "tags":f"comment,story_{story_id}",
        "hitsPerPage":n,"numericFilters":numeric})

async def execute():
    p, old = load()
    source = replay.previous
    outcomes={}
    async with httpx.AsyncClient(timeout=25, follow_redirects=False,
            trust_env=False, headers={"User-Agent":"OXIBAY-FrozenTopic-Relevance-Shadow/1"}) as client:
        for ctx in old["contexts"]:
            try:
                hits=await get_public_rows(client,ctx,p,source)
                if hits is None:
                    outcomes[ctx["key"]]={"status":"INCONCLUSIVE_SOURCE_NOT_UNIQUELY_FOUND"}
                elif not hits:
                    outcomes[ctx["key"]]={"status":"INCONCLUSIVE_EMPTY_SOURCE"}
                else:
                    outcomes[ctx["key"]]={"status":"AGGREGATED_FROZEN_TOPIC_DIAGNOSTIC",
                                          "metrics":summarize_context(ctx["key"],hits,p)}
            except (httpx.HTTPError,ValueError,TypeError):
                outcomes[ctx["key"]]={"status":"INCONCLUSIVE_PROVIDER_OR_INTEGRITY_FAILURE"}
    complete=all(x["status"]=="AGGREGATED_FROZEN_TOPIC_DIAGNOSTIC" for x in outcomes.values())
    if complete:
        totals={
            "examined":sum(x["metrics"]["records_examined"] for x in outcomes.values()),
            "content_only_positive":sum(x["metrics"]["content_only_positive_records"] for x in outcomes.values()),
            "topic_record_positive_evaluations":sum(x["metrics"]["topic_record_positive_evaluations"] for x in outcomes.values())
        }
    else:
        totals=None
    report={
        "schema_v":1,"experiment_id":p["experiment_id"],
        "status":"FROZEN_TOPIC_CONDITIONAL_DIAGNOSTIC" if complete else "INCONCLUSIVE_PARTIAL_SOURCES",
        "source_contexts":outcomes,"totals_if_complete":totals,
        "topic_queries_actually_executed":False,
        "end_to_end_search_evaluated":False,
        "verified_buyer_cases":0,
        "independent_replications":0,"independently_human_reviewed":False,
        "source_text_persisted":False,"source_ids_persisted":False,
        "automatic_promotion":False,"production_write":False,
        "commercial_gate_influence":"NONE",
    }
    OUT.write_text(json.dumps(report,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    print(json.dumps({"status":report["status"],"totals_if_complete":totals,
        "source_contexts":outcomes,"verified_buyer_cases":0,"independent_replications":0},sort_keys=True))

def main():
    p,_=load()
    if sys.argv[1:]==[]:
        print(json.dumps({"mode":"PLAN_ONLY","source_contexts":len(p["contexts"]),
            "frozen_topics":len(p["topics"]),"max_source_requests":p["max_public_requests"],
            "scoring_context_only":True,"production_write":False}))
    elif sys.argv[1:]==["--execute"]:
        asyncio.run(execute())
    else:
        raise SystemExit("Unsupported command")

if __name__=="__main__":
    main()
