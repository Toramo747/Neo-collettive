# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Andrea Gava
"""Reality-calibrated strategy evolution for the isolated NEO Arena."""
from __future__ import annotations
import argparse, json
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Callable
import httpx
from arena_registry_world import mark_controls_zero_weight, register_external_predictions, evaluate_external_predictions

NAMESPACE="mycelix-arena"
EVOLVE_EVERY_SESSIONS=5
OWN_HEALTH_URL="https://neo-collettive.onrender.com/health"

INITIAL_STRATEGIES={
    "Scout":[
        ("scout-breadth","breadth_first",["scan multiple candidate classes","label uncertainty"]),
        ("scout-gap","gap_first",["start from documented gaps","avoid popularity as evidence"]),
        ("scout-evidence","evidence_first",["prefer falsifiable claims","attach a verification path"]),
    ],
    "Analyst":[
        ("analyst-weighted","weighted_evidence",["weight independent evidence","separate facts from hypotheses"]),
        ("analyst-falsify","falsification_weighted",["penalize contrary evidence explicitly","prefer testable criteria"]),
        ("analyst-conservative","conservative",["hold when evidence is sparse","avoid consensus-based confidence"]),
    ],
    "Critic":[
        ("critic-counter","counterexample_first",["seek counterexamples before agreement","record disconfirming tests"]),
        ("critic-duplicate","duplication_check",["search for existing alternatives","challenge novelty"]),
        ("critic-independence","source_independence",["challenge correlated sources","accept only proven shared facts"]),
    ],
    "Builder-planner":[
        ("builder-feasible","feasibility_first",["estimate bounded build effort","identify dependencies"]),
        ("builder-dependency","dependency_first",["block hidden paid dependencies","prefer reproducible environments"]),
        ("builder-smallest","smallest_test_first",["design smallest falsifiable test","never auto-promote to production"]),
    ],
}

def now_utc() -> str: return datetime.now(timezone.utc).isoformat()
def _parse(v: str):
    try: return datetime.fromisoformat(str(v).replace("Z","+00:00"))
    except Exception: return None
def load_json(path: Path, default: Any):
    try: return json.loads(path.read_text(encoding="utf-8"))
    except Exception: return default
def save_json(path: Path, value: Any):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")

def initial_state() -> dict:
    variants=[]
    for agent,rows in INITIAL_STRATEGIES.items():
        for variant_id,name,rules in rows:
            variants.append({"variant_id":variant_id,"agent":agent,"strategy":name,"rules":rules,
                             "generation":0,"parent_id":None,"status":"ACTIVE","score":None,
                             "production_promoted":False,"created_at_utc":now_utc()})
    return {"schema_v":1,"namespace":NAMESPACE,"variants":variants,"predictions":[],"genealogy":[],
            "last_evolved_session_count":0,
            "scoring_rule":"Brier calibration from evaluated predictions only; consensus/AGREE count has zero weight",
            "production_proposal":{"approval_required":True,"approved_by_andrea":False,"automatic_promotion":False,"candidate_variant_id":None},
            "boundary":{"production_promotion":"MANUAL_ONLY","commercial_influence":"NONE","seti_influence":"NONE","external_usage_influence":"NONE"}}

def register_initial_predictions(state: dict, *, created_at: datetime|None=None):
    created_at=created_at or datetime.now(timezone.utc)
    due=created_at+timedelta(days=7)
    specs=[
        ("pred-health","Scout","scout-evidence",0.80,
         "On the evaluation date MYCELIX production health will still report runtime profile mycelix-prod-main.",
         {"kind":"read_only_test","test":"production_health_profile"}),
        ("pred-micelio","Analyst","analyst-falsify",0.90,
         "Every ACTIVE fact in the Arena micelio will still carry at least one proof.",
         {"kind":"read_only_test","test":"active_facts_have_proof"}),
        ("pred-gap","Critic","critic-independence",0.65,
         "The MCP Compatibility Doctor usefulness claim will remain an unproven hypothesis unless independent proof is added.",
         {"kind":"read_only_test","test":"tool_utility_still_hypothesis"}),
        ("pred-promotion","Builder-planner","builder-smallest",0.98,
         "No Arena strategy variant will be marked as promoted to production without Andrea approval.",
         {"kind":"read_only_test","test":"no_auto_promotion"}),
    ]
    existing={str(x.get("prediction_id") or "") for x in state.get("predictions") or [] if isinstance(x,dict)}
    for pid,agent,vid,p,statement,verification in specs:
        if pid in existing: continue
        state.setdefault("predictions",[]).append({
            "prediction_id":pid,"agent":agent,"variant_id":vid,"statement":statement,
            "probability":p,"created_at_utc":created_at.isoformat(),"due_at_utc":due.isoformat(),
            "status":"PENDING","verification":verification,"evaluated_at_utc":None,
            "outcome":None,"calibration_score":None,"sources":[],
            "prediction_scope":"system_control","score_weight":0.0,
        })
    return state

def _verify_local(test: str, root: Path, state: dict) -> tuple[bool,list[str]]:
    if test=="active_facts_have_proof":
        m=load_json(root/"micelio.json",{})
        active=[x for x in (m.get("beliefs") or []) if isinstance(x,dict) and x.get("status")=="ACTIVE" and x.get("type")=="fact"]
        return bool(active and all(bool(x.get("evidence")) for x in active)),["data/arena/micelio.json"]
    if test=="tool_utility_still_hypothesis":
        m=load_json(root/"micelio.json",{})
        rows=[x for x in (m.get("beliefs") or []) if isinstance(x,dict) and str(x.get("belief_id") or "").endswith("tool-utility")]
        return bool(rows and all(x.get("status")=="HYPOTHESIS" for x in rows)),["data/arena/micelio.json"]
    if test=="no_auto_promotion":
        variants=state.get("variants") or []
        proposal=state.get("production_proposal") or {}
        ok=not any(bool(x.get("production_promoted")) for x in variants if isinstance(x,dict)) and proposal.get("automatic_promotion") is False
        return ok,["data/arena/evolution.json"]
    return False,[]

def _verify_health() -> tuple[bool,list[str]]:
    try:
        r=httpx.get(OWN_HEALTH_URL,headers={"Accept":"application/json"},timeout=20,follow_redirects=False)
        if r.status_code!=200: return False,[OWN_HEALTH_URL]
        d=r.json(); profile=d.get("runtime_profile") or {}
        return str(profile.get("profile_id") or "")=="mycelix-prod-main",[OWN_HEALTH_URL]
    except Exception:
        return False,[OWN_HEALTH_URL]

def evaluate_due(state: dict, root: str|Path="data/arena", *, at: datetime|None=None,
                 overrides: dict[str,Callable[[],tuple[bool,list[str]]]]|None=None) -> dict:
    at=at or datetime.now(timezone.utc); root=Path(root); overrides=overrides or {}
    for pred in state.get("predictions") or []:
        if not isinstance(pred,dict) or pred.get("status")!="PENDING": continue
        due=_parse(str(pred.get("due_at_utc") or ""))
        if not due or at<due: continue
        test=str((pred.get("verification") or {}).get("test") or "")
        if test in overrides:
            outcome,sources=overrides[test]()
        elif test=="production_health_profile":
            outcome,sources=_verify_health()
        else:
            outcome,sources=_verify_local(test,root,state)
        p=max(0.0,min(1.0,float(pred.get("probability") or 0.0)))
        y=1.0 if outcome else 0.0
        pred["outcome"]=bool(outcome)
        pred["calibration_score"]=round(1.0-(p-y)**2,6)
        pred["evaluated_at_utc"]=at.isoformat()
        pred["sources"]=list(sources)
        pred["status"]="EVALUATED"
    refresh_scores(state)
    return state

def refresh_scores(state: dict):
    by_variant={}
    for pred in state.get("predictions") or []:
        if (
            isinstance(pred,dict) and pred.get("status")=="EVALUATED"
            and pred.get("calibration_score") is not None
            and pred.get("prediction_scope")=="external_registry"
            and float(pred.get("score_weight") or 0.0)>0.0
        ):
            by_variant.setdefault(str(pred.get("variant_id") or ""),[]).append(float(pred["calibration_score"]))
    for v in state.get("variants") or []:
        if not isinstance(v,dict): continue
        scores=by_variant.get(str(v.get("variant_id") or ""),[])
        v["score"]=round(sum(scores)/len(scores),6) if scores else None
        v["evaluated_predictions"]=len(scores)
    return state

def maybe_evolve(state: dict, session_count: int, *, at: datetime|None=None) -> dict:
    at=at or datetime.now(timezone.utc)
    if session_count<=0 or session_count%EVOLVE_EVERY_SESSIONS!=0: return state
    if int(state.get("last_evolved_session_count") or 0)>=session_count: return state
    variants=state.get("variants") or []
    for agent in INITIAL_STRATEGIES:
        active=[v for v in variants if isinstance(v,dict) and v.get("agent")==agent and v.get("status")=="ACTIVE" and v.get("score") is not None]
        if len(active)<2: continue
        best=max(active,key=lambda x:float(x["score"])); worst=min(active,key=lambda x:float(x["score"]))
        if best["variant_id"]==worst["variant_id"]: continue
        worst["status"]="RETIRED"
        new_id=str(best["variant_id"])+"-g"+str(int(best.get("generation") or 0)+1)+"-s"+str(session_count)
        mutation={
            "variant_id":new_id,"agent":agent,"strategy":str(best.get("strategy") or "")+"_mutation",
            "rules":list(best.get("rules") or [])+[f"mutation after {session_count} sessions: tighten falsifiability"],
            "generation":int(best.get("generation") or 0)+1,"parent_id":best.get("variant_id"),
            "status":"ACTIVE","score":None,"evaluated_predictions":0,"production_promoted":False,
            "created_at_utc":at.isoformat(),
        }
        variants.append(mutation)
        state.setdefault("genealogy",[]).append({
            "agent":agent,"session_count":session_count,"retired_variant_id":worst.get("variant_id"),
            "parent_variant_id":best.get("variant_id"),"child_variant_id":new_id,"created_at_utc":at.isoformat(),
            "reason":"reality_score_replacement","production_promotion":False,
        })
    state["last_evolved_session_count"]=session_count
    return state

def sync(root: str|Path="data/arena") -> dict:
    root=Path(root); state=load_json(root/"evolution.json",initial_state())
    if state.get("namespace")!=NAMESPACE: state=initial_state()
    register_initial_predictions(state,created_at=datetime(2026,9,27,4,36,46,tzinfo=timezone.utc))
    mark_controls_zero_weight(state)
    evaluate_due(state,root)
    idx=load_json(root/"index.json",{})
    session_count=len(idx.get("sessions") or []) if isinstance(idx,dict) else 0
    register_external_predictions(state,"data/registry-health",cycle_id=str(session_count))
    evaluate_external_predictions(state,"data/registry-health")
    refresh_scores(state)
    maybe_evolve(state,session_count)
    # Hard guard: Arena may propose, never promote.
    for v in state.get("variants") or []:
        if isinstance(v,dict): v["production_promoted"]=False
    state["production_proposal"]={
        "approval_required":True,"approved_by_andrea":False,"automatic_promotion":False,
        "candidate_variant_id":max(
            [v for v in state.get("variants") or [] if isinstance(v,dict) and v.get("score") is not None],
            key=lambda x:float(x["score"]),default={}
        ).get("variant_id"),
    }
    save_json(root/"evolution.json",state)
    return state

def main():
    p=argparse.ArgumentParser(); p.add_argument("--data-dir",default="data/arena"); args=p.parse_args()
    s=sync(args.data_dir)
    pending=sum(1 for x in s.get("predictions") or [] if x.get("status")=="PENDING")
    evaluated=sum(1 for x in s.get("predictions") or [] if x.get("status")=="EVALUATED")
    external=[x for x in (s.get("predictions") or []) if isinstance(x,dict) and x.get("prediction_scope")=="external_registry"]
    controls=[x for x in (s.get("predictions") or []) if isinstance(x,dict) and x.get("prediction_scope")=="system_control"]
    print(json.dumps({"ok":True,"namespace":NAMESPACE,"variants":len(s.get("variants") or []),
                      "predictions_pending":pending,"predictions_evaluated":evaluated,
                      "external_predictions":len(external),"control_predictions":len(controls),
                      "external_prediction_status":s.get("external_prediction_status"),
                      "automatic_promotion":False},ensure_ascii=False))
if __name__=="__main__": main()
