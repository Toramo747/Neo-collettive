# SPDX-License-Identifier: BUSL-1.1
"""Disjoint topic panels with a matched compact-topic baseline. Shadow only."""
import asyncio
import hashlib
import json
import sys
from datetime import datetime, timezone
from importlib.util import spec_from_file_location, module_from_spec
from pathlib import Path

import httpx

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
s=spec_from_file_location("oxibay_v2",ROOT/"experiments/research-holdout-v2/run.py")
v2=module_from_spec(s)
s.loader.exec_module(v2)
from arena_research_algorithm import HN_ENDPOINT, QUERY_SUFFIXES, MAX_HITS_PER_QUERY

PROTOCOL=Path(__file__).with_name("protocol.json")
REPORT=Path("/tmp/oxibay-replication-v3-report.json")

def load():
    p=json.loads(PROTOCOL.read_text(encoding="utf-8"))
    v2p=v2.load_protocol()
    assert p["schema_v"]==1 and p["preregistered_before_execution"] is True
    assert p["source"]=="hn_algolia_public_read_only"
    assert HN_ENDPOINT=="https://hn.algolia.com/api/v1/search_by_date"
    assert p["recency_days"]==45 and p["hits_per_query"]==MAX_HITS_PER_QUERY==30
    assert p["upstream_v2"]["commit"]=="f50936d916cf7b3c751e2f6376445b8f6faa6659"
    for k,val in {"production_state_write":False,"automatic_promotion":False,
        "commercial_gate_influence":"NONE","commercial_evidence_influence":"NONE",
        "paid_api_calls":False,"private_datasets_access":False,
        "raw_external_text_persisted":False}.items():
        if p["boundary"].get(k)!=val: raise ValueError("Policy drift: "+k)
    assert p["decision_rule"]["commercial_promotion"] is False
    assert p["decision_rule"]["required_independent_rounds"]==3
    assert all(v==v2p["expected_treatment_genes"][k] for k,v in p["shared_genes"].items())
    assert len(p["panels"])==2 and len(p["arms"])==3
    prior={t["full"] for t in v2p["holdout_topics"]}
    first=json.loads((ROOT/"experiments/research-holdout/protocol.json").read_text())
    prior.update(t["full"] for t in first["holdout_topics"])
    evo=json.loads((ROOT/"data/arena/research-algorithm/latest.json").read_text())
    prior.update(evo["benchmark"]["topics"])
    domains=set()
    for panel in p["panels"]:
        assert len(panel["topics"])==4
        for t in panel["topics"]:
            if t["full"] in prior or t["domain"] in domains or t["domain"] in p["excluded_domains"]:
                raise ValueError("Panel topic overlap")
            prior.add(t["full"]);domains.add(t["domain"])
    assert len(domains)==8
    return p

def plans(p):
    out={}
    suffixes=QUERY_SUFFIXES["core"]["mixed"][:4]
    for panel in p["panels"]:
        group={}
        for arm,delta in p["arms"].items():
            genes={**p["shared_genes"],**delta}
            rows=[]
            for topic in panel["topics"]:
                subject=topic["full"] if genes["topic_shape"]=="exact" else topic["compact"]
                for suffix in suffixes:
                    terms=(subject,suffix) if genes["term_order"]=="topic_first" else (suffix,subject)
                    rows.append({"topic":topic["full"],"query":" ".join(terms)})
            assert len(rows)==16
            group[arm]={"genes":genes,"rows":rows}
        out[panel["panel"]]=group
    return out

def verdict(matched,evolved,p):
    if matched["ok"]!=16 or evolved["ok"]!=16:
        return "INCONCLUSIVE_PROVIDER_FAILURE"
    a=matched["score"]["score"];b=evolved["score"]["score"]
    r=p["decision_rule"]
    if a["relevant_hits"]<r["matched_min_relevant_hits"]:
        return "INCONCLUSIVE_WEAK_MATCHED_BASELINE"
    if b["unique_signal_threads"]>=a["unique_signal_threads"]+r["required_gain_threads"] and b["topic_coverage"]>=r["minimum_signal_topics"] and b["precision"]>=a["precision"]*r["precision_ratio_min"]:
        return "CANDIDATE_NOT_VALIDATED"
    return "NO_GAIN_VS_MATCHED_BASELINE"

async def run():
    p=load();groups=plans(p)
    queries=sorted({x["query"] for panel in groups.values() for arm in panel.values() for x in arm["rows"]})
    if len(queries)<48 or len(queries)>96: raise ValueError("Query count mismatch")
    timestamp=int(datetime.now(timezone.utc).timestamp())
    cutoff=timestamp-45*86400
    payloads={}
    async with httpx.AsyncClient(timeout=20,follow_redirects=False,trust_env=False,
                                 headers={"User-Agent":"OXIBAY-Matched-Holdout/1.0"}) as client:
        for query in queries:
            try:
                response=await client.get(HN_ENDPOINT,params={"query":query,
                    "hitsPerPage":30,"numericFilters":f"created_at_i>{cutoff},created_at_i<{timestamp}"})
                response.raise_for_status();data=response.json()
                if not isinstance(data,dict) or not isinstance(data.get("hits"),list):
                    raise ValueError("Malformed response")
                payloads[query]={"ok":True,"hits":data["hits"]}
            except (httpx.HTTPError,ValueError,TypeError):
                payloads[query]={"ok":False,"hits":[]}
    controls=v2.synthetic_controls()
    results={}
    for panel,arms in groups.items():
        out={}
        for name,arm in arms.items():
            rows=arm["rows"]
            out[name]={"ok":sum(int(payloads[r["query"]]["ok"]) for r in rows),
                       "score":v2.diagnostic_metrics(rows,
                        [payloads[r["query"]]["hits"] for r in rows],arm["genes"])}
        out["verdict"]="INVALID_SYNTHETIC_CONTROL" if not controls["pass"] else verdict(out["compact_matched"],out["evolved"],p)
        results[panel]=out
    report={"schema_v":1,"experiment_id":p["experiment_id"],"captured_at_utc":datetime.now(timezone.utc).isoformat(),
        "protocol_sha256":hashlib.sha256(PROTOCOL.read_bytes()).hexdigest(),
        "cutoff_epoch":cutoff,"upper_epoch":timestamp,"provider_unique_queries":len(queries),
        "synthetic_controls":controls,"panels":results,"verdict_scope":"MATCHED_BASELINE_ONLY",
        "validated_independent_rounds":0,"human_verified":False,"raw_external_text_persisted":False,
        "commercial_gate_influence":"NONE","production_state_write":False,"automatic_promotion":False}
    REPORT.write_text(json.dumps(report,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    summary={}
    for name,out in results.items():
        def stats(arm):
            m=out[arm]["score"]["score"]
            return {"query_ok":out[arm]["ok"],"relevant":m["relevant_hits"],
                "threads":m["unique_signal_threads"],"topics":m["topic_coverage"],"precision":m["precision"]}
        summary[name]={"exact":stats("exact_original"),"matched":stats("compact_matched"),
                       "evolved":stats("evolved"),"verdict":out["verdict"]}
    print(json.dumps({"controls_pass":controls["pass"],"panels":summary,
                     "validated_independent_rounds":0,"report":str(REPORT)},sort_keys=True))

if __name__=="__main__":
    p=load();groups=plans(p)
    if sys.argv[1:]==[]:
        print(json.dumps({"mode":"PLAN_ONLY","panels":len(groups),"arms":list(p["arms"]),
                          "queries_per_arm_panel":16,"production_state_write":False}))
    elif sys.argv[1:]==["--execute"]:
        asyncio.run(run())
    else: raise SystemExit("Unknown flags")
