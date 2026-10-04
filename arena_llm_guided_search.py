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
PLATEAU_PATIENCE=3
MAX_GENERATIONS=8

MUTATION_GENOMES={
    "first_person_pain":"Add one concise first-person operational pain phrase; preserve the original workflow terms.",
    "buyer_intent":"Add one explicit buyer-intent phrase such as looking for help, need someone, need a tool, contractor, or recommendation.",
    "paid_demand":"Add one willingness-to-pay phrase such as budget, hiring, contractor, quote, fixed price, or paid help.",
    "operational_burden":"Add one recurring-burden phrase such as every week, takes hours, repetitive, backlog, rework, or error-prone.",
    "pain_plus_buyer":"Add one first-person pain phrase and one explicit buyer-intent phrase, while preserving the workflow terms.",
    "pain_plus_burden":"Add one first-person pain phrase and one recurring burden phrase, while preserving the workflow terms.",
    "buyer_plus_paid":"Add one buyer-intent phrase and one willingness-to-pay phrase, while preserving the workflow terms.",
    "precision_pain":"Add only the strongest first-person pain phrase; avoid generic automation/software terms and keep the query short.",
}

PROMPT_GENOMES={
    "first_person_pain":{
        "instruction":"Use first-person operational pain language such as I spend hours, we manually, I hate, we struggle, this takes hours. Avoid generic product terms."
    },
    "buyer_intent":{
        "instruction":"Target explicit buyer intent: looking for help, need someone, need a tool, contractor, consultant, recommend a solution. Prefer buyer voice over vendor language."
    },
    "paid_demand":{
        "instruction":"Target willingness-to-pay signals: budget, hiring, paid help, contractor, consultant, quote, fixed price. Keep the concrete workflow problem in every query."
    },
    "operational_burden":{
        "instruction":"Target recurring operational burden: every day, every week, takes hours, repetitive, backlog, rework, error-prone, manual workaround."
    },
    "hybrid":{
        "instruction":"Mix first-person operational pain with explicit buyer intent or willingness-to-pay. Every query must contain both a concrete workflow problem and a buyer/pain signal."
    },
    "skeptical_precision":{
        "instruction":"Optimize for precision rather than volume. Use concise natural buyer language, one strong pain or buying signal per query, and avoid broad automation/software/vendor terms."
    },
}

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

def make_prompt(topic,genome_name="hybrid"):
    genome=PROMPT_GENOMES.get(genome_name) or PROMPT_GENOMES["hybrid"]
    return (
        "Return JSON only: {\"queries\":[...]} with 4 concise search queries. "
        "You are planning search queries, not supplying evidence or URLs. "
        + genome["instruction"] + " "
        "Avoid vendor/SEO phrasing. Do not invent links. "
        "Topic: "+json.dumps(topic)
    )

def plan_queries(model,topic,genome_name):
    response=post_json("http://127.0.0.1:11434/api/generate",{
        "model":model,"prompt":make_prompt(topic,genome_name),"stream":False,"format":"json",
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


def make_mutation_prompt(topic,base_query,genome_name):
    instruction=MUTATION_GENOMES[genome_name]
    return (
        "Return JSON only: {\"query\":\"...\"}. "
        "You are mutating an existing search query, not replacing its topic. "
        + instruction + " "
        "Keep the query concise. Do not add URLs. Do not add vendor/SEO language. "
        "Original query: "+json.dumps(base_query)+" Topic: "+json.dumps(topic)
    )

def mutate_query(model,topic,base_query,genome_name):
    response=post_json("http://127.0.0.1:11434/api/generate",{
        "model":model,"prompt":make_mutation_prompt(topic,base_query,genome_name),
        "stream":False,"format":"json",
        "options":{"temperature":0.2,"num_predict":120,"num_ctx":2048},"keep_alive":"0",
    })
    parsed=extract_json(response.get("response") or "")
    if not isinstance(parsed,dict):
        return ""
    q=valid_query(parsed.get("query"))
    if not q:
        return ""
    base_tokens={x for x in re.findall(r"[a-z0-9]+",base_query.lower()) if len(x)>=3}
    new_tokens={x for x in re.findall(r"[a-z0-9]+",q.lower()) if len(x)>=3}
    if base_tokens and len(base_tokens & new_tokens) < max(1,min(2,len(base_tokens))):
        return ""
    return q

def load_champion(data_dir):
    path=Path(data_dir)/"research-algorithm/latest.json"
    report=json.loads(path.read_text(encoding="utf-8"))
    ranked=report.get("ranked") or []
    if not ranked: raise RuntimeError("research arena champion unavailable")
    return clamp_genome(ranked[0].get("genes") or {}), ranked[0].get("genome_id")

async def run(model,data_dir,out_path):
    genes,champion_id=load_champion(data_dir)
    baseline_pairs=build_queries(genes)

    async with httpx.AsyncClient(timeout=20,follow_redirects=True) as client:
        baseline_rows=await asyncio.gather(*[
            fetch_hn_query(client,t,q,genes["recency_days"],genes["source_scope"])
            for t,q in baseline_pairs
        ])
        baseline=score_hits(genes,baseline_rows)

        current_pairs=list(baseline_pairs)
        current_metrics=baseline
        history=[]
        no_improve=0
        best_genome="baseline"

        for generation in range(1,MAX_GENERATIONS+1):
            ranked=[]
            for genome_name in MUTATION_GENOMES:
                mutated_pairs=[]
                mutation_map=[]
                for topic,base_query in current_pairs:
                    mutated=mutate_query(model,topic,base_query,genome_name)
                    chosen=mutated or base_query
                    mutated_pairs.append((topic,chosen))
                    mutation_map.append({"topic":topic,"base":base_query,"mutated":mutated,"used":bool(mutated)})
                rows=await asyncio.gather(*[
                    fetch_hn_query(client,t,q,genes["recency_days"],genes["source_scope"])
                    for t,q in mutated_pairs
                ])
                metrics=score_hits(genes,rows)
                accepted=bool(
                    metrics["fitness"]>current_metrics["fitness"]
                    and metrics["signal_hits"]>=current_metrics["signal_hits"]
                    and metrics["unique_signal_threads"]>=current_metrics["unique_signal_threads"]
                    and metrics["precision"]>=current_metrics["precision"]
                )
                ranked.append({
                    "generation":generation,
                    "genome":genome_name,
                    "fitness":metrics["fitness"],
                    "metrics":metrics,
                    "accepted_over_parent":accepted,
                    "mutations":mutation_map,
                    "pairs":mutated_pairs,
                })
            ranked.sort(key=lambda x:(-float(x.get("fitness") or -1),x["genome"]))
            winner=ranked[0]
            improved=bool(winner.get("accepted_over_parent"))
            history.append({
                "generation":generation,
                "parent_fitness":current_metrics["fitness"],
                "winner_genome":winner["genome"],
                "winner_fitness":winner["fitness"],
                "improved":improved,
                "ranked":[{"genome":x["genome"],"fitness":x["fitness"],"accepted":x["accepted_over_parent"]} for x in ranked],
            })
            if improved:
                current_pairs=list(winner["pairs"])
                current_metrics=dict(winner["metrics"])
                best_genome=winner["genome"]
                no_improve=0
            else:
                no_improve += 1
            if no_improve>=PLATEAU_PATIENCE:
                break

    plateau=bool(no_improve>=PLATEAU_PATIENCE)
    report={
        "schema_v":4,"namespace":NAMESPACE,"arena_id":ARENA_ID,
        "status":"PLATEAU" if plateau else "MAX_GENERATIONS_REACHED",
        "mode":"iterative_baseline_plus_single_llm_mutation",
        "captured_at_utc":now_utc(),"model":model,"provider":"local_ollama",
        "search_provider":"hn_algolia_public_read_only","baseline_champion":champion_id,
        "baseline_metrics":baseline,
        "final_metrics":current_metrics,
        "final_genome":best_genome,
        "generations_run":len(history),
        "plateau_patience":PLATEAU_PATIENCE,
        "max_generations":MAX_GENERATIONS,
        "history":history,
        "candidate_better_than_baseline":bool(current_metrics["fitness"]>baseline["fitness"]),
        "production_promoted":False,
        "boundary":{
            "production_state_write":False,
            "commercial_gate_influence":"NONE",
            "qualified_hits_influence":"NONE",
            "commercial_evidence_influence":"NONE",
            "llm_urls_accepted_as_evidence":False,
            "provider_urls_only":True,
            "baseline_queries_preserved_as_fallback":True,
            "single_mutation_per_query":True,
            "production_variant_promotion":False,
            "promotion":"MANUAL_REVIEW_ONLY"
        }
    }
    p=Path(out_path); p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps(report,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    print(json.dumps({
        "baseline":baseline["fitness"],
        "final":current_metrics["fitness"],
        "final_genome":best_genome,
        "status":report["status"],
        "generations_run":len(history),
        "history":history,
    }))
    return report

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--model",default="qwen2.5:0.5b-instruct")
    p.add_argument("--data-dir",default="data/arena")
    p.add_argument("--out",default="data/arena/llm-guided-search/latest.json")
    a=p.parse_args()
    asyncio.run(run(a.model,a.data_dir,a.out))
if __name__=="__main__": main()
