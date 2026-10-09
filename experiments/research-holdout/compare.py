# SPDX-License-Identifier: BUSL-1.1
"""One bounded, preregistered research-strategy holdout. No production writes."""
import asyncio
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
import httpx

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from arena_research_algorithm import HN_ENDPOINT, MAX_HITS_PER_QUERY, QUERY_SUFFIXES, clamp_genome, score_hits, clean_text, text_tokens, buyer_voice_present, commercial_family, demand_signal_type, is_vendor_content, is_supply_offer

PROTOCOL=Path(__file__).with_name("protocol.json")
REPORT=Path("/tmp/oxibay-independent-research-holdout.json")

def load_protocol():
    p=json.loads(PROTOCOL.read_text(encoding="utf-8"))
    if p["schema_v"]!=1 or p["hit_limit_per_query"]!=MAX_HITS_PER_QUERY:
        raise ValueError("Protocol drift")
    if len(p["holdout_topics"])!=4 or len({t["full"] for t in p["holdout_topics"]})!=4:
        raise ValueError("Non-unique topics")
    for k,v in {"production_state_write":False,"automatic_promotion":False,"commercial_gate_influence":"NONE","commercial_evidence_influence":"NONE","paid_api_calls":False,"raw_external_text_persisted":False}.items():
        if p["boundary"].get(k)!=v:
            raise ValueError("Isolation guard failed: "+k)
    assert p["baseline_definition"]["query_count"]==p["expected_treatment_genes"]["query_count"]==4
    assert p["baseline_definition"]["source_scope"]==p["expected_treatment_genes"]["source_scope"]=="all"
    assert p["baseline_definition"]["recency_days"]==p["expected_treatment_genes"]["recency_days"]
    return p

def plans(protocol,champion):
    if clamp_genome(champion)!=protocol["expected_treatment_genes"]:
        raise ValueError("Champion drift; refuse comparison")
    result={}
    for label,genes in (("baseline",protocol["baseline_definition"]),("treatment",champion)):
        rows=[]
        suffixes=QUERY_SUFFIXES[genes["suffix_family"]][genes["query_mode"]][:genes["query_count"]]
        for topic in protocol["holdout_topics"]:
            for suffix in suffixes:
                title=topic["full"] if genes["topic_shape"]=="exact" else topic["compact"]
                parts=[title,suffix] if genes["term_order"]=="topic_first" else [suffix,title]
                query=" ".join(parts)
                if genes["query_frame"]!="plain":
                    raise ValueError("Unexpected query frame")
                rows.append({"topic":topic["full"],"query":query})
        result[label]=rows
    if len(result["baseline"])!=16 or len(result["treatment"])!=16:
        raise ValueError("Unequal query budgets")
    return result

def valid_thread_metrics(pairs,hits,genes):
    """Deduplicate by stable HN object ID before scoring; no raw text is written."""
    scored=[]
    seen=set()
    for pair,items in zip(pairs,hits):
        unique=[]
        for hit in items:
            if not isinstance(hit,dict):
                continue
            identity=str(hit.get("objectID") or "")
            if not identity:
                continue
            if identity in seen:
                continue
            seen.add(identity)
            unique.append(hit)
        scored.append({"topic":pair["topic"],"query":pair["query"],"hits":unique})
    base=score_hits(genes,scored)
    # A mutually-exclusive aggregate diagnostic explains *why* hits were rejected.
    # These buckets contain no URLs, text, IDs or private content.
    rejection_reasons={key:0 for key in (
        "irrelevant", "vendor_or_supply", "unknown_family",
        "no_buyer_voice", "no_demand_tags", "valid_signal")}
    topic_threads={}
    for row in scored:
        topic=row["topic"]
        topic_threads.setdefault(topic,set())
        for hit in row["hits"]:
            title=clean_text(hit.get("title") or hit.get("story_title") or "")
            body=clean_text(hit.get("comment_text") or hit.get("story_text") or "")
            # Same aggregate 1600-char normalization as score_hits.
            score_text=clean_text((title+" "+body).strip())
            if len(text_tokens(topic)&text_tokens(score_text))<genes["min_relevance_tokens"]:
                rejection_reasons["irrelevant"]+=1
                continue
            url=str(hit.get("url") or hit.get("story_url") or "")
            if is_vendor_content(title,body,url,"hn-algolia-routed") or is_supply_offer(title,body,url,"hn-algolia-routed"):
                rejection_reasons["vendor_or_supply"]+=1
                continue
            if commercial_family(score_text)=="other":
                rejection_reasons["unknown_family"]+=1
                continue
            if not buyer_voice_present(title,body):
                rejection_reasons["no_buyer_voice"]+=1
                continue
            tags=demand_signal_type(title,body,query_role="buyer",strong_pain_only=False,seller_launch_guard=True,url=url,source="hn-algolia-routed",vendor_content_guard=True,web_buyer_voice_guard=True,supply_offer_guard=True,query_echo_guard=True,query=row["query"])
            if not set(tags)&{"PAIN","BUY_INTENT","PAID_DEMAND"}:
                rejection_reasons["no_demand_tags"]+=1
                continue
            sid=str(hit.get("story_id") or hit.get("objectID") or "")
            if not sid:
                rejection_reasons["no_demand_tags"]+=1
                continue
            rejection_reasons["valid_signal"]+=1
            topic_threads[topic].add(sid)
    # The original score_hits thread number is deduped, but topic membership can repeat;
    # compute union over all four topics for conservative global unique-thread count.
    all_threads=set().union(*topic_threads.values())
    base["unique_signal_threads"]=len(all_threads)
    base["topic_coverage"]=sum(bool(s) for s in topic_threads.values())
    base["per_topic_unique_threads"]={k:len(v) for k,v in topic_threads.items()}
    base["deduped_object_count"]=len(seen)
    if sum(rejection_reasons.values())!=len(seen):
        raise ValueError("Diagnostic accounting mismatch")
    base["rejection_reasons"]=rejection_reasons
    return base

async def run():
    p=load_protocol()
    champion_report=json.loads((ROOT/"data/arena/research-algorithm/latest.json").read_text(encoding="utf-8"))
    champion=champion_report["ranked"][0]["genes"]
    q=plans(p,champion)
    cutoff=int(datetime.now(timezone.utc).timestamp())-45*86400
    both={s for lane in q.values() for s in (row["query"] for row in lane)}
    payloads={}
    async with httpx.AsyncClient(timeout=20,follow_redirects=False,trust_env=False,headers={"User-Agent":"OXIBAY-Research-Holdout/1.0"}) as client:
        for query in sorted(both):
            try:
                resp=await client.get(HN_ENDPOINT,params={"query":query,"hitsPerPage":MAX_HITS_PER_QUERY,"numericFilters":f"created_at_i>{cutoff}"})
                resp.raise_for_status()
                j=resp.json()
                if not isinstance(j,dict) or not isinstance(j.get("hits"),list):
                    raise ValueError("Invalid hit response")
                payloads[query]={"ok":True,"hits":j["hits"]}
            except Exception as exc:
                payloads[query]={"ok":False,"hits":[],"error":type(exc).__name__}
    results={}
    for label,genes in (("baseline",p["baseline_definition"]),("treatment",champion)):
        pairs=q[label]
        ok=sum(payloads[r["query"]]["ok"] for r in pairs)
        metric=valid_thread_metrics(pairs,[payloads[r["query"]]["hits"] for r in pairs],genes)
        results[label]={"query_count":len(pairs),"success_count":ok,"metrics":metric}
    a=results["baseline"]["metrics"];b=results["treatment"]["metrics"]
    full=all(x["success_count"]==x["query_count"] for x in results.values())
    rule=p["decision_rule"]
    improvement=bool(full and b["unique_signal_threads"]>=a["unique_signal_threads"]+rule["candidate_min_unique_thread_gain"] and b["precision"]>=a["precision"]*rule["candidate_min_precision_ratio_vs_baseline"] and b["topic_coverage"]>=rule["candidate_min_topic_coverage"])
    verdict="CANDIDATE_FOR_INDEPENDENT_REPLICATION" if improvement else ("INCONCLUSIVE_PROVIDER_FAILURE" if not full else "NO_DEMONSTRATED_GAIN")
    report={"schema_v":1,"experiment_id":p["experiment_id"],"protocol_sha256":hashlib.sha256(PROTOCOL.read_bytes()).hexdigest(),"code_reference":"experiments/research-holdout/compare.py","captured_at_utc":datetime.now(timezone.utc).isoformat(),"cutoff_epoch":cutoff,"source":"hn_algolia_public_read_only","new_topics":True,"provider_queries":len(both),"results":results,"verdict":verdict,"validated_independent_rounds":0,"required_independent_rounds":rule["required_independent_rounds_before_validation"],"automatic_promotion":False,"commercial_gate_influence":"NONE","raw_external_text_persisted":False}
    REPORT.write_text(json.dumps(report,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    print(json.dumps({"verdict":verdict,"baseline":results["baseline"],"treatment":results["treatment"],"report_path":str(REPORT)},sort_keys=True))

if __name__=="__main__":
    asyncio.run(run())
