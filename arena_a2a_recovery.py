# SPDX-License-Identifier: BUSL-1.1
"""Isolated evolutionary arena for MYCELIX A2A startup/discovery recovery."""
from __future__ import annotations
import argparse, hashlib, json, random
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

NAMESPACE="mycelix-arena"
ARENA_ID="mycelix-a2a-recovery"
POPULATION_SIZE=8
ELITE_COUNT=2
MODES=("sequential","concurrent")
TIMEOUTS=(3,5,8,12,20)
GRACES=(0,1,2,5,10)
SEMANTICS=("policy_enabled","accepted_registry")
ORDERINGS=("global_first","community_first","allagents_first")
SMOKE_AT=10.0

BOUNDARY={
  "namespace":NAMESPACE,
  "arena_id":ARENA_ID,
  "production_state_write":False,
  "external_registry_write":False,
  "secret_persistence":False,
  "commercial_gate_influence":"NONE",
  "qualified_hits_influence":"NONE",
  "production_variant_promotion":False,
  "promotion":"MANUAL_REVIEW_ONLY",
}

SCENARIOS=(
 {"name":"all_fast","policy":True,"delays":{"global":0.4,"community":0.5,"allagents":0.6},"ok":{"global":False,"community":True,"allagents":True}},
 {"name":"global_404_slow_community","policy":True,"delays":{"global":0.3,"community":7.0,"allagents":1.0},"ok":{"global":False,"community":True,"allagents":True}},
 {"name":"community_timeout_allagents_ok","policy":True,"delays":{"global":0.4,"community":25.0,"allagents":1.2},"ok":{"global":False,"community":False,"allagents":True}},
 {"name":"all_registries_slow","policy":True,"delays":{"global":18.0,"community":18.0,"allagents":18.0},"ok":{"global":False,"community":False,"allagents":False}},
 {"name":"policy_disabled","policy":False,"delays":{"global":0.1,"community":0.1,"allagents":0.1},"ok":{"global":True,"community":True,"allagents":True}},
)

def now_utc(): return datetime.now(timezone.utc).isoformat()
def stable_seed(v): return int(hashlib.sha256(v.encode()).hexdigest()[:16],16)
def load_json(p,default):
    try: return json.loads(Path(p).read_text(encoding="utf-8"))
    except Exception: return default
def save_json(p,v):
    p=Path(p); p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps(v,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")

def clamp(g):
    out={
      "publish_state_early":bool(g.get("publish_state_early",False)),
      "registry_mode":str(g.get("registry_mode") or "sequential"),
      "per_registry_timeout":int(g.get("per_registry_timeout") or 8),
      "startup_grace_seconds":int(g.get("startup_grace_seconds") or 2),
      "registry_semantics":str(g.get("registry_semantics") or "policy_enabled"),
      "ordering":str(g.get("ordering") or "global_first"),
    }
    if out["registry_mode"] not in MODES: out["registry_mode"]="sequential"
    if out["per_registry_timeout"] not in TIMEOUTS: out["per_registry_timeout"]=8
    if out["startup_grace_seconds"] not in GRACES: out["startup_grace_seconds"]=2
    if out["registry_semantics"] not in SEMANTICS: out["registry_semantics"]="policy_enabled"
    if out["ordering"] not in ORDERINGS: out["ordering"]="global_first"
    return out

def seeds():
    raw=[
      {"publish_state_early":False,"registry_mode":"sequential","per_registry_timeout":20,"startup_grace_seconds":0,"registry_semantics":"policy_enabled","ordering":"global_first"},
      {"publish_state_early":True,"registry_mode":"sequential","per_registry_timeout":20,"startup_grace_seconds":0,"registry_semantics":"policy_enabled","ordering":"global_first"},
      {"publish_state_early":True,"registry_mode":"concurrent","per_registry_timeout":8,"startup_grace_seconds":0,"registry_semantics":"policy_enabled","ordering":"community_first"},
      {"publish_state_early":False,"registry_mode":"concurrent","per_registry_timeout":5,"startup_grace_seconds":1,"registry_semantics":"accepted_registry","ordering":"community_first"},
      {"publish_state_early":False,"registry_mode":"sequential","per_registry_timeout":5,"startup_grace_seconds":2,"registry_semantics":"accepted_registry","ordering":"allagents_first"},
      {"publish_state_early":True,"registry_mode":"concurrent","per_registry_timeout":3,"startup_grace_seconds":0,"registry_semantics":"policy_enabled","ordering":"allagents_first"},
      {"publish_state_early":False,"registry_mode":"concurrent","per_registry_timeout":12,"startup_grace_seconds":5,"registry_semantics":"policy_enabled","ordering":"global_first"},
      {"publish_state_early":True,"registry_mode":"sequential","per_registry_timeout":8,"startup_grace_seconds":1,"registry_semantics":"accepted_registry","ordering":"community_first"},
    ]
    return [{"genome_id":f"g0-{i+1}","generation":0,"origin":"seed","genes":clamp(x)} for i,x in enumerate(raw)]

def names(ordering):
    if ordering=="community_first": return ["community","allagents","global"]
    if ordering=="allagents_first": return ["allagents","community","global"]
    return ["global","community","allagents"]

def simulate(g,s):
    g=clamp(g); policy=bool(s["policy"]); timeout=float(g["per_registry_timeout"])
    if not policy:
        return {"smoke_enabled":False,"final_enabled":False,"finish_seconds":0.0,"accepted":0,"false_positive":False}
    initial = policy if g["publish_state_early"] and g["registry_semantics"]=="policy_enabled" else False
    accepted=0; durations=[]
    if g["registry_mode"]=="concurrent":
        for n in names(g["ordering"]):
            d=float(s["delays"][n]); durations.append(min(d,timeout))
            if d<=timeout and s["ok"][n]: accepted+=1
        finish=max(durations or [0.0])
    else:
        finish=0.0
        for n in names(g["ordering"]):
            d=float(s["delays"][n]); finish+=min(d,timeout)
            if d<=timeout and s["ok"][n]: accepted+=1
    finish+=float(g["startup_grace_seconds"])
    final = policy if g["registry_semantics"]=="policy_enabled" else accepted>0
    smoke = initial if SMOKE_AT < finish else final
    return {"smoke_enabled":bool(smoke),"final_enabled":bool(final),"finish_seconds":round(finish,3),"accepted":accepted,"false_positive":False}

def evaluate(g):
    rows=[{"scenario":s["name"],**simulate(g,s)} for s in SCENARIOS]
    enabled=[r for r,s in zip(rows,SCENARIOS) if s["policy"]]
    disabled=next(r for r,s in zip(rows,SCENARIOS) if not s["policy"])
    smoke=sum(1 for r in enabled if r["smoke_enabled"])
    final=sum(1 for r in enabled if r["final_enabled"])
    avg=sum(r["finish_seconds"] for r in enabled)/len(enabled)
    false_positive=bool(disabled["smoke_enabled"] or disabled["final_enabled"])
    score=smoke*15 + final*7.5 + max(0.0,10.0-min(avg,20.0)/2.0)
    if not false_positive: score+=20
    else: score-=100
    if g.get("publish_state_early") and g.get("registry_semantics")=="policy_enabled": score+=5
    return {"fitness":round(score,4),"smoke_pass":smoke,"smoke_total":len(enabled),"final_pass":final,"final_total":len(enabled),"avg_finish_seconds":round(avg,3),"false_positive":false_positive,"scenarios":rows}

def gkey(g):
    g=clamp(g)
    return tuple(g[k] for k in ("publish_state_early","registry_mode","per_registry_timeout","startup_grace_seconds","registry_semantics","ordering"))

def mutate(g,rng):
    x=clamp(g); f=rng.choice(list(x))
    if f=="publish_state_early": x[f]=not x[f]
    elif f=="registry_mode": x[f]=rng.choice([v for v in MODES if v!=x[f]])
    elif f=="per_registry_timeout": x[f]=rng.choice([v for v in TIMEOUTS if v!=x[f]])
    elif f=="startup_grace_seconds": x[f]=rng.choice([v for v in GRACES if v!=x[f]])
    elif f=="registry_semantics": x[f]=rng.choice([v for v in SEMANTICS if v!=x[f]])
    elif f=="ordering": x[f]=rng.choice([v for v in ORDERINGS if v!=x[f]])
    return clamp(x)

def evolve(state):
    gen=int(state.get("generation",0))
    pop=state.get("population") or seeds()
    ranked=[{**r,"genes":clamp(r["genes"]),"metrics":evaluate(r["genes"])} for r in pop]
    ranked.sort(key=lambda r:(-r["metrics"]["fitness"],r["genome_id"]))
    champion=ranked[0]
    rng=random.Random(stable_seed(f"{gen}:{champion['genome_id']}:{champion['metrics']['fitness']}"))
    nxt=[]
    for i,e in enumerate(ranked[:ELITE_COUNT],1):
        nxt.append({"genome_id":f"g{gen+1}-elite-{i}","generation":gen+1,"origin":"elite","genes":e["genes"]})
    seen={gkey(x["genes"]) for x in nxt}
    while len(nxt)<POPULATION_SIZE:
        child=mutate(rng.choice(ranked[:4])["genes"],rng)
        if gkey(child) in seen: continue
        seen.add(gkey(child))
        nxt.append({"genome_id":f"g{gen+1}-{len(nxt)+1}","generation":gen+1,"origin":"mutation","genes":child})
    return {"generation":gen+1,"population":nxt,"last_ranked":ranked,"promotion_candidate":{"genome_id":champion["genome_id"],"genes":champion["genes"],"fitness":champion["metrics"]["fitness"],"manual_review_required":True,"production_promoted":False}}

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--data-dir",default="data/arena"); a=ap.parse_args()
    state_path=Path(a.data_dir)/"a2a-recovery/state.json"
    report_path=Path(a.data_dir)/"a2a-recovery/latest.json"
    state=load_json(state_path,{"generation":0,"population":seeds()})
    new=evolve(state)
    report={"schema_v":1,"namespace":NAMESPACE,"arena_id":ARENA_ID,"captured_at_utc":now_utc(),"status":"EVOLVED","evaluated_generation":int(state.get("generation",0)),"next_generation":new["generation"],"ranked":new["last_ranked"],"promotion_candidate":new["promotion_candidate"],"boundary":BOUNDARY,"benchmark":{"smoke_at_seconds":SMOKE_AT,"deterministic":True,"scenarios":[s["name"] for s in SCENARIOS]}}
    save_json(state_path,new); save_json(report_path,report)
    print(json.dumps({"status":report["status"],"champion":report["promotion_candidate"]},indent=2))

if __name__=="__main__": main()
