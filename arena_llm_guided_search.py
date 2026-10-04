# SPDX-License-Identifier: BUSL-1.1
"""Shadow Arena: local-LLM-guided commercial query planning."""
from __future__ import annotations
import argparse, asyncio, json, re, urllib.request
from datetime import datetime, timezone
from pathlib import Path
import httpx

from arena_research_algorithm import (
    HN_ENDPOINT, MAX_HITS_PER_QUERY, build_queries, clamp_genome,
    fetch_hn_query, score_hits
)

NAMESPACE="mycelix-arena"
ARENA_ID="llm-guided-commercial-search"
TOPICS=("manual data entry","invoice reconciliation","security compliance evidence","spreadsheet workflow")
MAX_QUERIES_PER_TOPIC=4

def now_utc(): return datetime.now(timezone.utc).isoformat()

def post_json(url,payload,timeout=75):
    body=json.dumps(payload).encode("utf-8")
    req=urllib.request.Request(url,data=body,headers={"Content-Type":"application/json"},method="POST")
    with urllib.request.urlopen(req,timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))

def extract_json(text):
    value=str(text or "").strip()
    try: return json.loads(value)
    except Exception:
        start=value.find("{"); end=value.rfind("}")
        if start>=0 and end>start:
            try: return json.loads(value[start:end+1])
            except Exception: pass
    return None

def valid_query(value):
    q=" ".join(str(value or "").split())[:240]
    if not q or "http://" in q.lower() or "https://" in q.lower():
        return ""
    return q

def make_prompt(topic):
    return (
        "Return JSON only: {\"queries\":[...]} with 4 concise search queries. "
        "You are planning search queries, not supplying evidence or URLs. "
        "Optimize for first-person buyer pain, explicit need, hiring/budget intent, "
        "and operational burden. Avoid vendor/SEO phrasing. Do not invent links. "
        "Topic: "+json.dumps(topic)
    )

def plan_queries(model,topic):
    response=post_json("http://127.0.0.1:11434/api/generate",{
        "model":model,"prompt":make_prompt(topic),"stream":False,"format":"json",
        "options":{"temperature":0.25,"num_predict":220,"num_ctx":2048},"keep_alive":"0",
    })
    parsed=extract_json(response.get("response") or "")
    raw=parsed.get("queries") if isinstance(parsed,dict) else []
    out=[]
    for value in raw if isinstance(raw,list) else []:
        q=valid_query(value)
        if q and q.lower() not in {x.lower() for x in out}:
            out.append(q)
        if len(out)>=MAX_QUERIES_PER_TOPIC: break
    return out

def load_champion(data_dir):
    path=Path(data_dir)/"research-algorithm/latest.json"
    report=json.loads(path.read_text(encoding="utf-8"))
    ranked=report.get("ranked") or []
    if not ranked: raise RuntimeError("research arena champion unavailable")
    return clamp_genome(ranked[0].get("genes") or {}), ranked[0].get("genome_id")

async def run(model,data_dir,out_path):
    genes,champion_id=load_champion(data_dir)
    baseline_pairs=build_queries(genes)
    plans={topic:plan_queries(model,topic) for topic in TOPICS}
    llm_pairs=[(topic,q) for topic in TOPICS for q in plans.get(topic,[])]
    if len(llm_pairs)<len(TOPICS):
        raise RuntimeError("insufficient valid local-LLM queries")

    async with httpx.AsyncClient(timeout=20,follow_redirects=True) as client:
        baseline_rows=await asyncio.gather(*[
            fetch_hn_query(client,t,q,genes["recency_days"],genes["source_scope"])
            for t,q in baseline_pairs
        ])
        llm_rows=await asyncio.gather(*[
            fetch_hn_query(client,t,q,genes["recency_days"],genes["source_scope"])
            for t,q in llm_pairs
        ])

    baseline=score_hits(genes,baseline_rows)
    guided=score_hits(genes,llm_rows)
    improved=bool(
        guided["fitness"]>baseline["fitness"]
        and guided["signal_hits"]>=baseline["signal_hits"]
        and guided["unique_signal_threads"]>=baseline["unique_signal_threads"]
    )
    report={
        "schema_v":1,"namespace":NAMESPACE,"arena_id":ARENA_ID,"status":"COMPLETED",
        "captured_at_utc":now_utc(),"model":model,"provider":"local_ollama",
        "search_provider":"hn_algolia_public_read_only","baseline_champion":champion_id,
        "baseline_metrics":baseline,"llm_guided_metrics":guided,
        "query_counts":{"baseline":len(baseline_pairs),"llm_guided":len(llm_pairs)},
        "llm_query_plan":plans,
        "candidate_better_than_baseline":improved,
        "production_promoted":False,
        "boundary":{
            "production_state_write":False,
            "commercial_gate_influence":"NONE",
            "qualified_hits_influence":"NONE",
            "commercial_evidence_influence":"NONE",
            "llm_urls_accepted_as_evidence":False,
            "provider_urls_only":True,
            "production_variant_promotion":False,
            "promotion":"MANUAL_REVIEW_ONLY"
        }
    }
    p=Path(out_path); p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps(report,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    print(json.dumps({"baseline":baseline["fitness"],"guided":guided["fitness"],"candidate":improved}))
    return report

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--model",default="qwen2.5:0.5b-instruct")
    p.add_argument("--data-dir",default="data/arena")
    p.add_argument("--out",default="data/arena/llm-guided-search/latest.json")
    a=p.parse_args()
    asyncio.run(run(a.model,a.data_dir,a.out))
if __name__=="__main__": main()
