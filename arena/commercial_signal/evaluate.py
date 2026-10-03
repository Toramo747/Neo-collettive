from __future__ import annotations
import argparse, json
from pathlib import Path
from typing import Any

MAX_FILE_BYTES=65536
MAX_TOTAL_MARKERS=128
ALLOWED_TOP={"schema_version","name","positive_markers","negative_markers","negations","weights","thresholds","vendor_exclusion"}
ALLOWED_POS={"pain","buy","paid"}
ALLOWED_WEIGHTS={"pain","buy","paid","negative"}
ALLOWED_THRESH={"demand_score_min","vendor_fp_rate_max"}
ALLOWED_VENDOR={"enabled","source_types","markers"}

def _marker_list(v:Any,name:str)->list[str]:
    if not isinstance(v,list) or len(v)>32: raise ValueError(name)
    out=[]
    for x in v:
        if not isinstance(x,str) or not (2<=len(x)<=64): raise ValueError(name)
        if any(c not in "abcdefghijklmnopqrstuvwxyz0123456789 _-" for c in x): raise ValueError(name)
        out.append(x)
    if len(set(out))!=len(out): raise ValueError(name)
    return out

def validate_proposal(p:dict)->dict:
    if not isinstance(p,dict): raise ValueError("proposal_not_object")
    if set(p)!=ALLOWED_TOP: raise ValueError("unknown_or_missing_top_fields")
    if p["schema_version"]!=1: raise ValueError("schema_version")
    if not isinstance(p["name"],str) or not (1<=len(p["name"])<=80): raise ValueError("name")
    pos=p["positive_markers"]
    if not isinstance(pos,dict) or set(pos)!=ALLOWED_POS: raise ValueError("positive_markers")
    total=0
    for k in ALLOWED_POS: total+=len(_marker_list(pos[k],"positive_"+k))
    total+=len(_marker_list(p["negative_markers"],"negative_markers"))
    total+=len(_marker_list(p["negations"],"negations"))
    ven=p["vendor_exclusion"]
    if not isinstance(ven,dict) or set(ven)!=ALLOWED_VENDOR: raise ValueError("vendor_exclusion")
    if not isinstance(ven["enabled"],bool): raise ValueError("vendor_enabled")
    st=ven["source_types"]
    if not isinstance(st,list) or len(st)>8 or any(not isinstance(x,str) or not (1<=len(x)<=40) for x in st): raise ValueError("vendor_source_types")
    total+=len(_marker_list(ven["markers"],"vendor_markers"))
    if total>MAX_TOTAL_MARKERS: raise ValueError("too_many_markers")
    w=p["weights"]
    if not isinstance(w,dict) or set(w)!=ALLOWED_WEIGHTS: raise ValueError("weights")
    if any(not isinstance(w[k],int) or not (0<=w[k]<=10) for k in w): raise ValueError("weight_range")
    th=p["thresholds"]
    if not isinstance(th,dict) or set(th)!=ALLOWED_THRESH: raise ValueError("thresholds")
    if not isinstance(th["demand_score_min"],int) or not (1<=th["demand_score_min"]<=30): raise ValueError("demand_score_min")
    if not isinstance(th["vendor_fp_rate_max"],(int,float)) or not (0<=th["vendor_fp_rate_max"]<=1): raise ValueError("vendor_fp_rate_max")
    return p

def load_proposal(path:Path)->dict:
    raw=path.read_bytes()
    if len(raw)>MAX_FILE_BYTES: raise ValueError("proposal_too_large")
    return validate_proposal(json.loads(raw.decode("utf-8")))

def load_dataset(path:Path)->list[dict]:
    rows=[]
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip(): rows.append(json.loads(line))
    return rows

def _hits(text:str,markers:list[str],negations:list[str])->int:
    low=" ".join(text.lower().split())
    blocked={n for n in negations if n in low}
    return sum(1 for m in markers if m in low and not any(m in n for n in blocked))

def predict(row:dict,p:dict)->bool:
    text=str(row.get("evidence_text") or "")
    low=" ".join(text.lower().split())
    ven=p["vendor_exclusion"]
    if ven["enabled"]:
        if str(row.get("source_type") or "") in set(ven["source_types"]): return False
        if any(m in low for m in ven["markers"]): return False
    pos=p["positive_markers"]; neg=p["negations"]; w=p["weights"]
    score=0
    family_hits={}
    for fam in ("pain","buy","paid"):
        h=_hits(text,pos[fam],neg); family_hits[fam]=h; score+=h*w[fam]
    score-=_hits(text,p["negative_markers"],[])*w["negative"]
    if family_hits["paid"]<1: return False
    if family_hits["buy"]<1 and family_hits["pain"]<1: return False
    return score>=p["thresholds"]["demand_score_min"]

def metrics(rows:list[dict],p:dict)->dict:
    tp=fn=fp_vendor=vendor_total=pred_total=0
    for r in rows:
        pred=predict(r,p)
        label=r["proposed_label"]
        pred_total+=int(pred)
        if label=="REAL_DEMAND": tp+=int(pred); fn+=int(not pred)
        if label=="VENDOR_OR_SELLER":
            vendor_total+=1; fp_vendor+=int(pred)
    precision_den=sum(1 for r in rows if predict(r,p))
    precision=(tp/precision_den) if precision_den else 0.0
    recall=tp/(tp+fn) if tp+fn else 0.0
    vendor_fp=fp_vendor/vendor_total if vendor_total else 0.0
    disqualified=vendor_fp>float(p["thresholds"]["vendor_fp_rate_max"])
    return {"precision_real_demand":round(precision,4),"recall_real_demand":round(recall,4),
            "vendor_false_positive_rate":round(vendor_fp,4),"vendor_false_positives":fp_vendor,
            "vendor_total":vendor_total,"predicted_demand":pred_total,"disqualified":disqualified}

def main()->int:
    ap=argparse.ArgumentParser()
    ap.add_argument("--dataset",default="")
    ap.add_argument("--proposals-dir",default="arena/commercial_signal/proposals")
    ap.add_argument("--out",default="")
    args=ap.parse_args()
    dataset_paths=[Path(args.dataset)] if args.dataset else [
        Path("arena/commercial_signal/train_synthetic.jsonl"),
        Path("arena/commercial_signal/train_real_review.jsonl"),
    ]
    datasets={}
    for dataset_path in dataset_paths:
        rows=load_dataset(dataset_path)
        results={}
        for path in sorted(Path(args.proposals_dir).glob("*.json")):
            p=load_proposal(path); results[path.stem]=metrics(rows,p)
        eligible=[(name,m) for name,m in results.items() if not m["disqualified"]]
        best_recall=max((m["recall_real_demand"] for _,m in eligible),default=None)
        top_recall=sorted(name for name,m in eligible if m["recall_real_demand"]==best_recall) if best_recall is not None else []
        label_counts={}
        family_counts={}
        missing_counts={}
        for row in rows:
            label=str(row.get("proposed_label") or "")
            family=str(row.get("family") or "unspecified")
            label_counts[label]=label_counts.get(label,0)+1
            family_counts[family]=family_counts.get(family,0)+1
            for reason in row.get("gate_missing") or []:
                missing_counts[str(reason)]=missing_counts.get(str(reason),0)+1
        datasets[dataset_path.name]={
            "dataset_size":len(rows),"label_counts":label_counts,"family_counts":family_counts,
            "gate_missing_counts":missing_counts,"results":results,"top_by_arena_rule":top_recall,
            "best_recall_real_demand":best_recall,
        }
    out={"datasets":datasets,
         "note":"Arena-only evaluation; synthetic validates infrastructure only; real labels remain proposed; no production adoption."}
    text=json.dumps(out,sort_keys=True,indent=2)
    if args.out: Path(args.out).write_text(text+"\n",encoding="utf-8")
    print(text)
    return 0
if __name__=="__main__": raise SystemExit(main())
