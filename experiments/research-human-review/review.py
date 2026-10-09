# SPDX-License-Identifier: BUSL-1.1
"""Local-only dual-blind HN classifier error audit; default mode has zero network."""
import argparse
import asyncio
import csv
import hashlib
import io
import json
import os
import secrets
import sys
from collections import Counter
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import httpx

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
def import_path(name,path):
    spec=spec_from_file_location(name,ROOT/path)
    module=module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

screen=import_path("oxibay_screen","experiments/research-fresh-screen/screen.py")
v2=import_path("oxibay_diag","experiments/research-holdout-v2/run.py")
from arena_research_algorithm import HN_ENDPOINT,MAX_HITS_PER_QUERY

PROTOCOL=Path(__file__).with_name("protocol.json")
PACKET="blind_cases.jsonl"
KEY="private_predictions.json"
ONE="reviewer_1.csv"
TWO="reviewer_2.csv"
REPORT="private_aggregate_only.json"

def policy():
    p=json.loads(PROTOCOL.read_text(encoding="utf-8"))
    assert p["schema_v"]==1
    assert p["study_class"]=="RETROSPECTIVE_DEVELOPMENT_ERROR_ANALYSIS_NOT_CONFIRMATORY"
    assert p["source_month"]=="2026-08"
    assert p["hn_source"]==HN_ENDPOINT and p["max_hits_per_query"]==MAX_HITS_PER_QUERY==30
    assert p["max_query_count"]==16 and p["max_cases"]==30 and p["max_per_stage"]==5
    assert p["stages"]==list(v2.STAGES)
    required={"source_data_local_only":True,"labels_local_only":True,
              "raw_data_to_github":False,"source_ids_to_github":False,
              "read_only_public_source":True,"paid_api_calls":False,
              "commercial_gate_influence":"NONE","production_state_write":False,
              "auto_model_training":False,"auto_promotion":False,
              "independent_validation_rounds":0}
    for k,v in required.items():
        if p["boundary"].get(k)!=v:raise ValueError("Policy boundary: "+k)
    return p

def enforce_windows_private_acl(path):
    """On Windows, chmod 0700 is not an ACL; explicitly remove inherited access."""
    if os.name != "nt":
        return
    import re
    import subprocess
    who=subprocess.run(["whoami","/user","/fo","csv","/nh"],
                       check=True,capture_output=True,text=True)
    rows=list(csv.reader(io.StringIO(who.stdout)))
    if len(rows)!=1 or len(rows[0])<2:
        raise ValueError("Windows user SID could not be resolved")
    sid=rows[0][1].strip()
    if not re.fullmatch(r"S-\\d+(?:-\\d+)+",sid):
        raise ValueError("Invalid Windows user SID")
    # Access is granted only to current user and LOCAL SYSTEM.
    # On failure, collection stops before writing any raw source text.
    subprocess.run(["icacls",str(path),"/inheritance:r","/grant:r",
                    f"*{sid}:(OI)(CI)F","*S-1-5-18:(OI)(CI)F"],
                   check=True,capture_output=True,text=True)


def private_path(raw,create=False):
    if not raw:raise ValueError("Explicit --private-dir is required")
    path=Path(raw).expanduser()
    if not path.is_absolute():raise ValueError("Review directory must be absolute")
    path=path.resolve()
    root=ROOT.resolve()
    if path==root or root in path.parents:raise ValueError("Refuse writing inside repository")
    if create:
        if path.exists():raise ValueError("Use a fresh private directory, never overwrite")
        path.mkdir(parents=True,mode=0o700)
        os.chmod(path,0o700)
        enforce_windows_private_acl(path)
    elif not path.is_dir():raise ValueError("Missing private directory")
    return path

def save_file(path,data):
    flags=os.O_WRONLY|os.O_CREAT|os.O_EXCL
    if hasattr(os,"O_NOFOLLOW"):flags|=os.O_NOFOLLOW
    fd=os.open(path,flags,0o600)
    with os.fdopen(fd,"w",encoding="utf-8",newline="") as f:f.write(data)
    os.chmod(path,0o600)

def stage(topic,query,hit,genes):
    prior=v2.prior
    title=prior.clean_text(hit.get("title") or hit.get("story_title") or "")
    body=prior.clean_text(hit.get("comment_text") or hit.get("story_text") or "")
    text=prior.clean_text((title+" "+body).strip())
    url=str(hit.get("url") or hit.get("story_url") or "")
    if len(prior.text_tokens(topic)&prior.text_tokens(text))<genes["min_relevance_tokens"]:
        return "irrelevant"
    if prior.is_vendor_content(title,body,url,"hn-algolia-routed") or prior.is_supply_offer(title,body,url,"hn-algolia-routed"):
        return "vendor_or_supply"
    if prior.commercial_family(text)=="other":return "unknown_family"
    if not prior.buyer_voice_present(title,body):return "no_buyer_voice"
    tags=prior.demand_signal_type(title,body,query_role="buyer",
        strong_pain_only=False,seller_launch_guard=True,url=url,
        source="hn-algolia-routed",vendor_content_guard=True,
        web_buyer_voice_guard=True,supply_offer_guard=True,
        query_echo_guard=True,query=query)
    if not set(tags)&{"PAIN","BUY_INTENT","PAID_DEMAND"}:
        return "no_demand_tags"
    if not str(hit.get("story_id") or hit.get("objectID") or ""):
        return "no_demand_tags"
    return "valid_signal"

def select(records,p,salt):
    grouped={k:[] for k in p["stages"]}
    for record in records:grouped[record["stage"]].append(record)
    picked=[]; threads=set()
    for tag in p["stages"]:
        options=sorted(grouped[tag],
            key=lambda x:hashlib.sha256((salt+":"+x["object_id"]).encode()).hexdigest())
        for item in options:
            if sum(c["stage"]==tag for c in picked)>=p["max_per_stage"]:break
            if item["thread_id"] in threads:continue
            threads.add(item["thread_id"]);picked.append(item)
    if len(picked)>p["max_cases"]:raise ValueError("Sample budget exceeded")
    return picked

def visible(case):
    return {k:case[k] for k in ("case_id","topic","title","body","hn_url")}

def labels_template(ids):
    b=io.StringIO();w=csv.writer(b,lineterminator="\n")
    w.writerow(["case_id","label","purchase_evidence","reason"])
    for case_id in ids:w.writerow([case_id,"","",""])
    return b.getvalue()

def write_packet(directory,cases,p):
    private=private_path(directory,create=True)
    mapping={c["case_id"]:{"stage":c["stage"]} for c in cases}
    save_file(private/PACKET,"".join(json.dumps(visible(c),sort_keys=True)+"\n" for c in cases))
    save_file(private/KEY,json.dumps({"schema_v":1,"cases":mapping,
        "study_class":p["study_class"],"human_verified":False},sort_keys=True,indent=2)+"\n")
    for name in (ONE,TWO):save_file(private/name,labels_template(list(mapping)))
    return {"status":"PRIVATE_REVIEW_PACKET_CREATED","sample_size":len(cases),
            "human_verified":False,"validated_independent_rounds":0}

async def collect(directory):
    p=policy()
    s=screen.load()
    baseline=screen.plan(s)[0]
    if baseline["id"]!="matched_baseline":raise ValueError("Baseline drift")
    q=screen.make_pairs(s,baseline["search_genes"])
    if (len(q)!=p["max_query_count"] or s["start_epoch"]!=p["start_epoch"]
        or s["end_epoch"]!=p["end_epoch"]):raise ValueError("Source/window drift")
    # Check output destination before accessing public network.
    target=Path(directory or "").expanduser()
    if not target.is_absolute() or target.exists() or ROOT.resolve() in target.resolve().parents:
        raise ValueError("Choose an unused, absolute private directory outside repository")
    payloads={}
    async with httpx.AsyncClient(timeout=18,follow_redirects=False,trust_env=False,
                                 headers={"User-Agent":"OXIBAY-Local-Blind-Review/1.0"}) as client:
        for pair in q:
            result=await client.get(HN_ENDPOINT,params={"query":pair["query"],
                "hitsPerPage":30,"numericFilters":
                f"created_at_i>={p['start_epoch']},created_at_i<{p['end_epoch']}"})
            result.raise_for_status()
            data=result.json()
            if not isinstance(data,dict) or not isinstance(data.get("hits"),list):
                raise ValueError("Unexpected HN response")
            payloads[pair["query"]]=data["hits"][:30]
    expected=v2.diagnostic_metrics(q,[payloads[r["query"]] for r in q],baseline["search_genes"])
    counts=Counter();visited=set();rows=[]
    for pair in q:
        for h in payloads[pair["query"]]:
            if not isinstance(h,dict):continue
            obj=str(h.get("objectID") or "")
            if not obj or obj in visited:continue
            visited.add(obj)
            label=stage(pair["topic"],pair["query"],h,baseline["search_genes"])
            counts[label]+=1
            if not obj.isascii() or not obj.isdigit():continue
            rows.append({"object_id":obj,"thread_id":str(h.get("story_id") or obj),
                "topic":pair["topic"],"stage":label,
                "title":v2.prior.clean_text(h.get("title") or h.get("story_title") or ""),
                "body":v2.prior.clean_text(h.get("comment_text") or h.get("story_text") or ""),
                "hn_url":"https://news.ycombinator.com/item?id="+obj})
    if dict(counts)!={k:v for k,v in expected["stages"].items() if v}:
        raise ValueError("Stage divergence; review packet blocked")
    if expected["score"]["signal_hits"]!=expected["stages"]["valid_signal"]:
        raise ValueError("Scorer divergence; review packet blocked")
    salt=secrets.token_hex(32)
    selected=select(rows,p,salt)
    for item in selected:
        item["case_id"]=hashlib.sha256((salt+"|"+item["object_id"]).encode()).hexdigest()[:20]
    result=write_packet(directory,selected,p)
    print(json.dumps({**result,"sample_stage_counts":dict(Counter(x["stage"] for x in selected)),
        "source_stage_counts":dict(counts)},sort_keys=True))

def read_labels(path,known,p):
    with path.open(encoding="utf-8",newline="") as f:
        rows=list(csv.DictReader(f))
    if len(rows)!=len(known):raise ValueError("Missing/extra reviewer rows")
    out={}
    for row in rows:
        key=row.get("case_id") or ""
        if key not in known or key in out:raise ValueError("Unrecognized/duplicate case ID")
        label=(row.get("label") or "").strip().lower()
        if label and label not in p["allowed_labels"]:raise ValueError("Unknown label")
        out[key]=label
    return out

def aggregate(directory):
    p=policy();root=private_path(directory)
    if (root/REPORT).exists():raise ValueError("Refuse to overwrite existing summary")
    key=json.loads((root/KEY).read_text(encoding="utf-8"))
    if key.get("study_class")!=p["study_class"]:raise ValueError("Untrusted packet")
    cases=key.get("cases",{})
    if not isinstance(cases,dict) or len(cases)>30:raise ValueError("Invalid packet")
    r1=read_labels(root/ONE,cases,p);r2=read_labels(root/TWO,cases,p)
    pending=uncertain=disagree=0;agree=Counter()
    for case_id,case in cases.items():
        a,b=r1[case_id],r2[case_id]
        if not a or not b:pending+=1
        elif "uncertain" in (a,b):uncertain+=1
        elif a!=b:disagree+=1
        else:agree[(case["stage"],a)]+=1
    if pending:status="INCOMPLETE_REVIEW"
    elif uncertain or disagree:status="NEEDS_ADJUDICATION"
    elif len(cases)<p["min_descriptive_cases"]:status="INSUFFICIENT_CASES"
    else:status="SELF_REPORTED_TWO_REVIEWER_DESCRIPTIVE_COMPLETE"
    report={"schema_v":1,"status":status,"sample_count":len(cases),
        "agreed_count":sum(agree.values()),"pending":pending,"uncertain":uncertain,
        "disagreements":disagree,
        "agreed_false_negatives":sum(n for (s,l),n in agree.items() if s!="valid_signal" and l=="real_demand"),
        "agreed_false_positives":agree[("valid_signal","no_demand")],
        "stage_counts_agreed":{s:{"real_demand":agree[(s,"real_demand")],
                                 "no_demand":agree[(s,"no_demand")]} for s in p["stages"]},
        "representative_error_rates":False,"independent_reviewer_identity_verified":False,
        "human_review_completed_in_ci":False,"commercial_proof":False,
        "auto_promotion":False,"validated_independent_rounds":0,
        "source_text_in_report":False,"development_only":True}
    save_file(root/REPORT,json.dumps(report,sort_keys=True,indent=2)+"\n")
    print(json.dumps(report,sort_keys=True))

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("action",choices=("plan","collect","aggregate"),nargs="?",default="plan")
    parser.add_argument("--private-dir")
    args=parser.parse_args()
    if args.action=="plan":
        p=policy()
        print(json.dumps({"mode":"PLAN_ONLY","max_queries":p["max_query_count"],
           "max_private_cases":p["max_cases"],"human_verified":False,
           "production_state_write":False},sort_keys=True))
    elif args.action=="collect":asyncio.run(collect(args.private_dir))
    else:aggregate(args.private_dir)

if __name__=="__main__":main()
