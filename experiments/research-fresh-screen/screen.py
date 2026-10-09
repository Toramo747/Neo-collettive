# SPDX-License-Identifier: BUSL-1.1
"""Single unseen-window read-only screening of 8 shadow gametes vs matched base."""
import asyncio, hashlib, json, sys
from pathlib import Path
from importlib.util import spec_from_file_location, module_from_spec
import httpx

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
src=ROOT/"experiments/research-autocorrection/engine.py"
spec=spec_from_file_location("autocorrection_engine",src)
engine=module_from_spec(spec);spec.loader.exec_module(engine)
s2=spec_from_file_location("holdout_v2",ROOT/"experiments/research-holdout-v2/run.py")
v2=module_from_spec(s2);s2.loader.exec_module(v2)
from arena_research_algorithm import HN_ENDPOINT, MAX_HITS_PER_QUERY, QUERY_SUFFIXES

P=Path(__file__).with_name("protocol.json")
OUT=Path("/tmp/oxibay-research-gamete-fresh-screen.json")

def load():
    p=json.loads(P.read_text())
    assert p["schema_v"]==1 and p["parent_sha"]=="b654fae076a585ad70760f178c7bc6e46391192f"
    assert p["provider"]=="hn_algolia_public_read_only"
    assert HN_ENDPOINT=="https://hn.algolia.com/api/v1/search_by_date"
    assert p["max_hits_per_query"]==MAX_HITS_PER_QUERY==30
    assert p["max_arms"]==9 and p["max_public_queries"]==144
    assert p["screen_month"] not in p["training_months"]
    assert p["start_epoch"]<p["end_epoch"]
    assert len(p["topics"])==4 and len({t["domain"] for t in p["topics"]})==4
    for k,v in {"automatic_promotion":False,"production_state_write":False,"commercial_gate_influence":"NONE","commercial_evidence_influence":"NONE","raw_external_text_persisted":False,"private_data_access":False,"paid_api_calls":False,"human_verified":False,"independent_validation_rounds":0}.items():
        if p["boundaries"][k]!=v: raise ValueError("Boundary drift: "+k)
    return p

def make_pairs(p, genes):
    suffixes=QUERY_SUFFIXES[genes["suffix_family"]][genes["query_mode"]][:genes["query_count"]]
    # The compact vs exact topic names are preregistered; do not infer or edit after seeing results.
    pairs=[]
    for topic in p["topics"]:
        target=topic["full"] if genes["topic_shape"]=="exact" else topic["compact"]
        for suffix in suffixes:
            words=(target,suffix) if genes["term_order"]=="topic_first" else (suffix,target)
            query=" ".join(words)
            if genes["query_frame"]=="need":query="need "+query
            elif genes["query_frame"]=="looking_for":query="looking for "+query
            pairs.append({"topic":topic["full"],"query":query})
    if len(pairs)!=16:raise ValueError("Query budget changed")
    return pairs

def plan(p):
    policy=engine.load_policy()
    variants=engine.propose(policy,engine.load_training(policy))
    baseline={"query_mode":"mixed","query_count":4,"recency_days":45,"min_relevance_tokens":1,"suffix_family":"core","topic_shape":"compact","query_frame":"plain","term_order":"topic_first","source_scope":"all"}
    if len(variants)!=8:raise ValueError("Gametes count changed")
    arms=[{"id":"matched_baseline","search_genes":baseline,"knobs":None}]+variants
    if len(arms)!=p["max_arms"]:raise ValueError("Arm budget changed")
    return arms

def verdict(a,b,p):
    aa=a["score"]["score"];bb=b["score"]["score"];rule=p["criteria"]
    if not a["integrity"] or not b["integrity"]: return "INCONCLUSIVE_METRIC_DISAGREEMENT"
    if a["ok"]!=16 or b["ok"]!=16:return "INCONCLUSIVE_PROVIDER_FAILURE"
    if aa["relevant_hits"]<rule["min_matched_relevant"]:return "INCONCLUSIVE_WEAK_MATCHED_BASELINE"
    if (bb["unique_signal_threads"]>=aa["unique_signal_threads"]+rule["min_unique_thread_gain"]
        and bb["topic_coverage"]>=rule["min_topic_coverage"]
        and bb["precision"]>=aa["precision"]):
        return "SCREEN_POSITIVE_NOT_VALIDATED"
    return "NO_DEMONSTRATED_GAIN"

async def run():
    p=load();arms=plan(p)
    pairs={a["id"]:make_pairs(p,a["search_genes"]) for a in arms}
    queries=sorted({row["query"] for q in pairs.values() for row in q})
    if len(queries)>p["max_public_queries"]:raise ValueError("Budget exceeded")
    results={}
    async with httpx.AsyncClient(timeout=18,follow_redirects=False,trust_env=False,headers={"User-Agent":"OXIBAY-Free-Gamete-Screen/1.0"}) as client:
        for query in queries:
            try:
                response=await client.get(HN_ENDPOINT,params={"query":query,"hitsPerPage":30,"numericFilters":f"created_at_i>={p['start_epoch']},created_at_i<{p['end_epoch']}"})
                response.raise_for_status();data=response.json()
                if not isinstance(data,dict) or not isinstance(data.get("hits"),list):raise ValueError("Invalid provider response")
                results[query]={"ok":True,"hits":data["hits"]}
            except (ValueError,TypeError,httpx.HTTPError):
                results[query]={"ok":False,"hits":[]}
    scores={}
    for arm in arms:
        q=pairs[arm["id"]]
        measurement=v2.diagnostic_metrics(q,[results[x["query"]]["hits"] for x in q],arm["search_genes"])
        stages=measurement["stages"];m=measurement["score"]
        intact=(m["signal_hits"]==stages["valid_signal"] and m["unique_signal_threads"]<=m["signal_hits"] and sum(stages.values())==m["deduped_object_count"])
        scores[arm["id"]]={"ok":sum(int(results[x["query"]]["ok"]) for x in q),"score":measurement,"integrity":intact}
    output=[]
    baseline=scores["matched_baseline"]
    for arm in arms:
        score=scores[arm["id"]];m=score["score"]["score"]
        output.append({"id":arm["id"],"target_rejection":arm["knobs"]["rejection_feedback"] if arm["knobs"] else None,
          "successful_queries":score["ok"],"relevant_hits":m["relevant_hits"],
          "unique_signal_threads":m["unique_signal_threads"],"signal_hits":m["signal_hits"],
          "precision":m["precision"],"topic_coverage":m["topic_coverage"],"metric_integrity":score["integrity"],
          "screen_verdict":"CONTROL" if arm["id"]=="matched_baseline" else verdict(baseline,score,p),
          "promotion_eligible":False,"validated_independent_rounds":0})
    controls=v2.synthetic_controls()
    if not controls["pass"]:raise ValueError("Synthetic evaluator control failed")
    report={"schema_v":1,"experiment_id":p["experiment_id"],"protocol_sha256":hashlib.sha256(P.read_bytes()).hexdigest(),
       "provider_unique_queries":len(queries),"development_screen_only":True,"human_verified":False,
       "source_provider_independent":False,"results":output,"synthetic_controls_pass":True,
       "validated_independent_rounds":0,"automatic_promotion":False,"production_state_write":False,
       "raw_external_text_persisted":False,"commercial_gate_influence":"NONE"}
    OUT.write_text(json.dumps(report,sort_keys=True,indent=2)+"\n")
    print(json.dumps({"status":"SHADOW_SCREEN_COMPLETE","queries":len(queries),"results":[{k:x[k] for k in ("id","successful_queries","unique_signal_threads","precision","screen_verdict","metric_integrity")} for x in output],"validation":0},sort_keys=True))

def main():
    p=load(); arms=plan(p)
    if sys.argv[1:]==[]:
        print(json.dumps({"mode":"PLAN_ONLY","arms":len(arms),"pairs_per_arm":16,"max_public_queries":p["max_public_queries"]}))
    elif sys.argv[1:]==["--execute"]: asyncio.run(run())
    else:raise SystemExit("unsupported option")

if __name__=="__main__":main()
