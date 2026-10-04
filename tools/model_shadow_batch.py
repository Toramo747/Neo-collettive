# SPDX-License-Identifier: BUSL-1.1
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import math
import os
import random
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0,str(ROOT))

from ingestion_diagnostics import canonical_source

from model_judges import (
    MODEL_LABELS,
    agreement_metrics,
    challenge_semantic_review,
    choose_automatic_label,
    lexicon_judge,
    structural_judge,
)
from model_shadow import (
    hashed_char_ngrams,
    validate_hidden_origins,
    validate_split_separation,
)

REGISTRY=json.loads((ROOT/"model_shadow_registry.json").read_text(encoding="utf-8"))
NLI_LABEL_MAP={'the writer is looking for a tool': 'buyer_tool_search', 'the writer is selling a product or service': 'vendor_offer', 'the writer describes recurring manual work': 'manual_recurring_work', 'a job posting': 'job_posting', 'a generic discussion unrelated to these needs': 'other'}
PRIVATE_FILES={"train":"train.jsonl","public":"public.jsonl","hidden":"hidden.jsonl"}
PUBLIC_METRIC_KEYS={
    "cases","consensus_labeled","discarded_disagreement","agreement_rate_ppm",
    "vendor_false_positives","buyer_recall_ppm","cluster_count",
    "clusters_with_3plus_requesters","student_bytes","student_public_accuracy_ppm",
    "student_hidden_accuracy_ppm","lexicon_public_accuracy_ppm","lexicon_hidden_accuracy_ppm",
}


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_jsonl(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    out=[]
    with path.open("r",encoding="utf-8") as fh:
        for line in fh:
            line=line.strip()
            if not line:
                continue
            row=json.loads(line)
            if isinstance(row,dict):
                out.append(row)
    return out


def _write_jsonl_private(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open("w",encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row,ensure_ascii=False,separators=(",",":"))+"\n")


def _case_text(row: dict) -> str:
    return " ".join(str(row.get("normalized_text") or "").split())


def _signals(row: dict) -> dict:
    value=row.get("structural_signals")
    return value if isinstance(value,dict) else {}


def validate_archive(private_dir: Path) -> dict:
    splits={name:_read_jsonl(private_dir/file) for name,file in PRIVATE_FILES.items()}
    ids={}
    for name,rows in splits.items():
        ids[name]={str(x.get("id") or "") for x in rows if str(x.get("id") or "")}
        if len(ids[name])!=len([x for x in rows if str(x.get("id") or "")]):
            raise ValueError("duplicate_case_id_within_"+name)
        for row in rows:
            missing=[
                key for key in ("id","normalized_text","source","structural_signals","date")
                if key not in row
            ]
            if missing:
                raise ValueError("archive_case_missing_fields")
            if name=="hidden":
                origin=str(row.get("label_origin") or "")
                if origin != "human":
                    raise ValueError("hidden_label_must_be_human")
    sep=validate_split_separation(ids["train"],ids["public"],ids["hidden"])
    validate_hidden_origins(splits["hidden"])
    return {"splits":{k:len(v) for k,v in splits.items()},**sep}


def _nli_pipeline():
    cfg=REGISTRY["judges"]["nli"]
    from transformers import pipeline
    return pipeline(
        "zero-shot-classification",
        model=cfg["repository"],
        revision=cfg["revision"],
        device=-1,
    )


def nli_judge(pipe, text: str) -> dict:
    labels=list(REGISTRY["judges"]["nli"]["labels"])
    result=pipe(text,labels,multi_label=False,
                hypothesis_template=REGISTRY["judges"]["nli"]["hypothesis_template"])
    natural=str((result.get("labels") or [""])[0])
    score=float((result.get("scores") or [0.0])[0])
    return {
        "judge":"nli",
        "label":NLI_LABEL_MAP.get(natural,"other"),
        "confidence":score,
    }


def _verify_sha256(path: Path, expected: str) -> None:
    h=hashlib.sha256()
    with path.open("rb") as fh:
        while True:
            chunk=fh.read(1024*1024)
            if not chunk:
                break
            h.update(chunk)
    if h.hexdigest()!=expected:
        raise RuntimeError("model_sha256_mismatch")


def _local_llm():
    cfg=REGISTRY["judges"]["local_llm"]
    from huggingface_hub import hf_hub_download
    from llama_cpp import Llama
    path=Path(hf_hub_download(
        repo_id=cfg["repository"],
        filename=cfg["filename"],
        revision=cfg["revision"],
    ))
    _verify_sha256(path,cfg["sha256"])
    return Llama(
        model_path=str(path),
        n_ctx=1024,
        n_threads=max(1,min(4,os.cpu_count() or 2)),
        verbose=False,
    )


def _llm_json_call(llm, prompt: str, *, max_tokens: int=220, temperature: float=0.0) -> dict:
    raw=llm.create_chat_completion(
        messages=[{"role":"user","content":prompt}],
        temperature=temperature,
        max_tokens=max_tokens,
        response_format={"type":"json_object"},
    )
    try:
        data=json.loads(str(raw["choices"][0]["message"]["content"]))
        return data if isinstance(data,dict) else {}
    except Exception:
        return {}


def llm_judge(llm, text: str, signals: dict) -> tuple[dict,dict]:
    prompt=(
        "Classifica il testo senza inventare fatti. Rispondi SOLO JSON con chiavi: "
        "canonical_problem,target_user,current_workaround,quoted_price,writer_role,"
        "failed_attempt,feasibility,proposed_label. "
        "proposed_label deve essere uno tra buyer_tool_search,vendor_offer,"
        "manual_recurring_work,job_posting,other. feasibility: feasible|hard|unknown. "
        "Testo:\n"+text[:1800]+"\nSegnali strutturali:"+json.dumps(signals,separators=(",",":"))[:1000]
    )
    data=_llm_json_call(llm,prompt,max_tokens=220)
    raw_label=data.get("proposed_label")
    label=str(raw_label or "")
    first_valid=label in MODEL_LABELS
    if not first_valid:
        label="other"

    verify_prompt=(
        "Independently classify this text by the writer's intent. Return ONLY JSON with the key "
        "proposed_label. Choose exactly one label from this deliberately reordered list: "
        "other,job_posting,manual_recurring_work,vendor_offer,buyer_tool_search. "
        "Do not infer facts that are not in the text or structural signals. "
        "Text:\n"+text[:1800]+"\nStructural signals:"+json.dumps(signals,separators=(",",":"))[:1000]
    )
    verify=_llm_json_call(llm,verify_prompt,max_tokens=64,temperature=0.0)
    verify_label=str(verify.get("proposed_label") or "")
    confidence=1.0 if first_valid and verify_label in MODEL_LABELS and verify_label==label else 0.0

    extracted={
        "canonical_problem":" ".join(str(data.get("canonical_problem") or "").split())[:300],
        "target_user":" ".join(str(data.get("target_user") or "").split())[:160],
        "current_workaround":" ".join(str(data.get("current_workaround") or "").split())[:300],
        "quoted_price":" ".join(str(data.get("quoted_price") or "").split())[:80],
        "writer_role":" ".join(str(data.get("writer_role") or "").split())[:80],
        "failed_attempt":bool(data.get("failed_attempt")),
        "feasibility":str(data.get("feasibility") or "unknown") if str(data.get("feasibility") or "") in {"feasible","hard","unknown"} else "unknown",
    }
    return {"judge":"local_llm","label":label,"confidence":confidence},extracted


def _source_bucket(row: dict) -> str:
    source=canonical_source(str(row.get("source") or "unknown"))
    sig=_signals(row)
    source_type=canonical_source(str(sig.get("source_type") or ""))
    if source.startswith("reddit"):
        return "reddit"
    if source in {"hn","bing-rss","brave","github","stackexchange"}:
        return source
    if bool(sig.get("pricing_page")) or source_type=="pricing_page":
        return "pricing_page"
    if bool(sig.get("job_board")) or source_type in {"job_board","job_feed"}:
        return "job_board"
    if source_type=="marketplace" or "market" in source:
        return "marketplace"
    if source in {"web","search","generic_web"} or source_type in {"web","search","generic_web"}:
        return "web"
    return "other"


def judge_private_archive(private_dir: Path, *, use_models: bool=True) -> dict:
    train=_read_jsonl(private_dir/PRIVATE_FILES["train"])
    nli=None
    llm=None
    if use_models and train:
        nli=_nli_pipeline()
        llm=_local_llm()
    consensus_cfg=REGISTRY["consensus"]
    labeled=[]
    counters=Counter()
    for row in train:
        text=_case_text(row)
        sig=_signals(row)
        source=str(row.get("source") or "")
        private_url=str(row.get("url") or "")
        title=str(row.get("title") or "")
        judges=[
            lexicon_judge(title,text,private_url,source,str(sig.get("query_role") or "")),
            structural_judge(sig),
        ]
        extracted={}
        if nli is not None:
            judges.append(nli_judge(nli,text))
        if llm is not None:
            lj,extracted=llm_judge(llm,text,sig)
            judges.append(lj)
        outcome=str(row.get("outcome_label") or "")
        decision=choose_automatic_label(
            judges,
            minimum_judges=int(consensus_cfg["minimum_judges"]),
            confidence_threshold=float(consensus_cfg["confidence_threshold"]),
            structural_abstention_pair_threshold=float(consensus_cfg.get("structural_abstention_pair_threshold",0.85)),
            outcome_label=outcome if outcome in MODEL_LABELS else "",
        )
        copy=dict(row)
        copy["judge_labels"]=[
            {"judge":str(x.get("judge") or ""),"label":str(x.get("label") or ""),"confidence":round(float(x.get("confidence") or 0.0),6)}
            for x in judges
        ]
        copy["canonical_fields"]=extracted
        copy["challenge_semantic_review"]=challenge_semantic_review(sig,extracted)
        copy["final_label"]=decision["label"]
        copy["label_origin"]=decision["origin"] if decision["label"] else ""
        copy["label_date"]=_utc()
        copy["consensus_policy_version"]=int(consensus_cfg.get("policy_version",3))
        copy["eligible_for_training"]=bool(decision["eligible_for_training"])
        counters["processed"]+=1
        counters["eligible"]+=int(bool(copy["eligible_for_training"]))
        counters["discarded"]+=int(not bool(copy["eligible_for_training"]))
        labeled.append(copy)
    _write_jsonl_private(private_dir/"train_labeled.jsonl",labeled)
    distribution=Counter(str(x.get("final_label") or "") for x in labeled if str(x.get("final_label") or ""))
    source_distribution=Counter(_source_bucket(x) for x in labeled)
    label_source_distribution=Counter(
        (str(x.get("final_label") or ""),_source_bucket(x))
        for x in labeled if str(x.get("final_label") or "") in MODEL_LABELS
    )
    metrics={
        "processed":counters["processed"],
        "eligible":counters["eligible"],
        "discarded_disagreement":counters["discarded"],
        "judge_agreement_rate_ppm":int(counters["eligible"]*1_000_000/max(1,counters["processed"])),
    }
    for label in MODEL_LABELS:
        metrics["label_count_"+label]=int(distribution[label])
    for bucket in ("reddit","hn","bing-rss","brave","github","stackexchange","pricing_page","job_board","marketplace","web","other"):
        metrics["source_bucket_count_"+bucket]=int(source_distribution[bucket])
        for label in MODEL_LABELS:
            metrics["label_source_count_"+label+"_"+bucket]=int(label_source_distribution[(label,bucket)])
    return metrics


def _encode_f32(arr) -> str:
    return base64.b64encode(arr.astype("<f4",copy=False).tobytes(order="C")).decode("ascii")


def _student_training_selection(private_dir: Path) -> tuple[list[dict],dict]:
    rows=[
        x for x in _read_jsonl(private_dir/"train_labeled.jsonl")
        if bool(x.get("eligible_for_training")) and str(x.get("final_label") or "") in MODEL_LABELS
    ]
    min_per_class=int(REGISTRY["student"].get("min_examples_per_class",4))
    counts=Counter(str(x.get("final_label") or "") for x in rows)
    allowed={label for label,count in counts.items() if count>=min_per_class}
    selected=[x for x in rows if str(x.get("final_label") or "") in allowed]
    metrics={}
    for label in MODEL_LABELS:
        metrics["training_label_count_"+label]=int(counts[label])
        metrics["training_label_used_"+label]=int(counts[label] if label in allowed else 0)
        metrics["training_label_excluded_"+label]=int(counts[label] if label not in allowed else 0)
    metrics["training_classes_used"]=len(allowed)
    metrics["training_cases_selected"]=len(selected)
    metrics["training_min_examples_per_class"]=min_per_class
    return selected,metrics


def train_student(private_dir: Path, output: Path, *, feature_dim: int=32768, epochs: int=18, lr: float=0.18) -> dict:
    import numpy as np
    rows,selection_metrics=_student_training_selection(private_dir)
    if len(rows)<4 or int(selection_metrics["training_classes_used"])<2:
        raise RuntimeError("insufficient_balanced_training_cases")
    labels=list(MODEL_LABELS)
    X=np.stack([hashed_char_ngrams(_case_text(x),feature_dim,3,5) for x in rows]).astype(np.float32)
    y=np.array([labels.index(str(x["final_label"])) for x in rows],dtype=np.int64)
    W=np.zeros((len(labels),feature_dim),dtype=np.float32)
    b=np.zeros(len(labels),dtype=np.float32)
    Y=np.eye(len(labels),dtype=np.float32)[y]
    class_counts=np.bincount(y,minlength=len(labels)).astype(np.float32)
    nonzero=class_counts[class_counts>0]
    max_count=float(nonzero.max()) if len(nonzero) else 1.0
    max_ratio=float(REGISTRY["student"].get("max_class_weight_ratio",10.0))
    class_weights=np.zeros(len(labels),dtype=np.float32)
    for idx,count in enumerate(class_counts):
        if count>0:
            class_weights[idx]=min(max_count/float(count),max_ratio)
    sample_weights=np.array([class_weights[idx] for idx in y],dtype=np.float32)
    sample_weights*=len(rows)/max(float(sample_weights.sum()),1e-12)
    for _ in range(max(1,epochs)):
        logits=X@W.T+b
        logits-=logits.max(axis=1,keepdims=True)
        exp=np.exp(logits)
        probs=exp/np.maximum(exp.sum(axis=1,keepdims=True),1e-12)
        grad=(probs-Y)*sample_weights[:,None]/len(rows)
        W-=lr*(grad.T@X).astype(np.float32)
        b-=lr*grad.sum(axis=0).astype(np.float32)
    manifest_hash=hashlib.sha256(
        json.dumps(
            sorted((str(x.get("id") or ""),str(x.get("final_label") or ""),str(x.get("label_origin") or "")) for x in rows),
            separators=(",",":"),
        ).encode("utf-8")
    ).hexdigest()
    payload={
        "schema_v":1,
        "mode":"shadow",
        "trained":True,
        "version":"student-"+datetime.now(timezone.utc).strftime("%Y%m%d"),
        "feature_dim":feature_dim,
        "ngram_min":3,
        "ngram_max":5,
        "labels":labels,
        "weights_f32_b64":_encode_f32(W),
        "bias_f32_b64":_encode_f32(b),
        "training_manifest_sha256":manifest_hash,
    }
    canonical=json.dumps(payload,sort_keys=True,separators=(",",":")).encode("utf-8")
    payload["artifact_sha256"]=hashlib.sha256(canonical).hexdigest()
    encoded=json.dumps(payload,separators=(",",":"))
    max_bytes=int(REGISTRY["student"]["max_artifact_bytes"])
    if len(encoded.encode("utf-8"))>max_bytes:
        raise RuntimeError("student_artifact_exceeds_limit")
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(encoded+"\n",encoding="utf-8")
    return {
        "training_cases":len(rows),
        "student_bytes":len(encoded.encode("utf-8")),
        "version":payload["version"],
        "training_class_balanced":True,
        "training_max_class_weight_ratio":max_ratio,
        **selection_metrics,
    }


def _predict_student_payload(payload: dict, text: str) -> str:
    from model_shadow import StudentModel
    return str(StudentModel(payload).predict(text).get("label") or "")


def _evaluation_metrics(rows: list[dict], prediction, prefix: str) -> dict:
    totals=Counter()
    hits=Counter()
    vendor_fp=0
    buyer_total=0
    buyer_hit=0
    overall_total=0
    overall_hit=0
    for row in rows:
        truth=str(row.get("final_label") or "")
        if truth not in MODEL_LABELS:
            continue
        pred=str(prediction(row) or "")
        overall_total+=1
        overall_hit+=int(pred==truth)
        totals[truth]+=1
        hits[truth]+=int(pred==truth)
        if truth=="buyer_tool_search":
            buyer_total+=1
            buyer_hit+=int(pred=="buyer_tool_search")
        if truth=="vendor_offer" and pred=="buyer_tool_search":
            vendor_fp+=1
    out={
        prefix+"_accuracy_ppm":int(overall_hit*1_000_000/max(1,overall_total)),
        prefix+"_vendor_false_positives":vendor_fp,
        prefix+"_buyer_recall_ppm":int(buyer_hit*1_000_000/max(1,buyer_total)),
    }
    for label in MODEL_LABELS:
        out[prefix+"_class_"+label+"_accuracy_ppm"]=int(hits[label]*1_000_000/max(1,totals[label]))
        out[prefix+"_class_"+label+"_cases"]=int(totals[label])
    return out


def evaluate_student(private_dir: Path, artifact: Path) -> dict:
    payload=json.loads(artifact.read_text(encoding="utf-8"))
    result={}
    for split in ("public","hidden"):
        rows=_read_jsonl(private_dir/PRIVATE_FILES[split])
        if split=="hidden":
            validate_hidden_origins(rows)
        result.update(_evaluation_metrics(
            rows,
            lambda r:_predict_student_payload(payload,_case_text(r)),
            "student_"+split,
        ))
        result.update(_evaluation_metrics(
            rows,
            lambda r:lexicon_judge(
                str(r.get("title") or ""),_case_text(r),str(r.get("url") or ""),
                str(r.get("source") or ""),str(_signals(r).get("query_role") or "")
            )["label"],
            "lexicon_"+split,
        ))
    result["student_bytes"]=artifact.stat().st_size
    for split in ("public","hidden"):
        checks=[
            bool(_read_jsonl(private_dir/PRIVATE_FILES[split])),
            all(str(r.get("final_label") or "") in MODEL_LABELS for r in _read_jsonl(private_dir/PRIVATE_FILES[split])),
            result["student_"+split+"_accuracy_ppm"]>=result["lexicon_"+split+"_accuracy_ppm"],
            result["student_"+split+"_buyer_recall_ppm"]>=result["lexicon_"+split+"_buyer_recall_ppm"],
            result["student_"+split+"_vendor_false_positives"]<=result["lexicon_"+split+"_vendor_false_positives"],
        ]
        for label in MODEL_LABELS:
            cases=int(result["lexicon_"+split+"_class_"+label+"_cases"] or 0)
            if cases>0:
                checks.append(
                    result["student_"+split+"_class_"+label+"_accuracy_ppm"]
                    >= result["lexicon_"+split+"_class_"+label+"_accuracy_ppm"]
                )
        result["student_not_worse_"+split]=bool(all(checks))
    result["promotion_eligible"]=bool(result["student_not_worse_public"] and result["student_not_worse_hidden"])
    result["promotion_requires_manual_approval"]=True
    return result

def _embedder():
    cfg=REGISTRY["judges"]["embedding"]
    from sentence_transformers import SentenceTransformer
    return SentenceTransformer(cfg["repository"],revision=cfg["revision"],device="cpu")


def cluster_challenges(private_dir: Path, output: Path, *, threshold: float | None=None) -> dict:
    import numpy as np
    rows=[
        x for x in _read_jsonl(private_dir/"train_labeled.jsonl")
        if str(x.get("challenge_semantic_review") or "") not in {"RESOLVED","HARD"}
        and str((x.get("canonical_fields") or {}).get("canonical_problem") or "")
    ]
    if not rows:
        output.parent.mkdir(parents=True,exist_ok=True)
        output.write_text(json.dumps({"schema_v":1,"clusters":[]})+"\n",encoding="utf-8")
        return {"cluster_count":0,"clusters_with_3plus_requesters":0}
    model=_embedder()
    texts=[str((x.get("canonical_fields") or {}).get("canonical_problem") or "") for x in rows]
    emb=model.encode(texts,normalize_embeddings=True,show_progress_bar=False)
    th=float(threshold if threshold is not None else REGISTRY["challenge_clustering"]["default_threshold"])
    assigned=[-1]*len(rows)
    centers=[]
    members=[]
    for i,v in enumerate(emb):
        best=-1
        best_score=-1.0
        for c,center in enumerate(centers):
            score=float(np.dot(v,center))
            if score>best_score:
                best_score=score
                best=c
        if best>=0 and best_score>=th:
            assigned[i]=best
            members[best].append(i)
            center=np.mean(emb[members[best]],axis=0)
            center=center/max(float(np.linalg.norm(center)),1e-12)
            centers[best]=center
        else:
            assigned[i]=len(centers)
            centers.append(v.copy())
            members.append([i])
    import hmac
    dedicated=os.getenv("MODEL_CLUSTER_HMAC_KEY") or ""
    heartbeat=os.getenv("NEO_HEARTBEAT_TOKEN") or ""
    if not dedicated and not heartbeat:
        raise RuntimeError("cluster_hmac_key_missing")
    secret=dedicated.encode("utf-8") if dedicated else hmac.new(
        heartbeat.encode("utf-8"), b"neo:model-shadow:cluster-map:v1", hashlib.sha256
    ).digest()
    safe=[]
    requester_by_cluster=defaultdict(set)
    cap=int(REGISTRY["challenge_clustering"]["requester_reaction_duplicate_cap"])
    for row,cluster in zip(rows,assigned):
        raw_id=str(row.get("id") or "")
        evidence_id=hmac.new(secret,("evidence|"+raw_id).encode("utf-8"),hashlib.sha256).hexdigest()[:16]
        cluster_id=hashlib.sha256(("cluster-v1|"+str(cluster)).encode("utf-8")).hexdigest()[:16]
        signals=_signals(row)
        requester=str(signals.get("requester_key") or row.get("requester_key") or "")
        if requester:
            requester_by_cluster[cluster_id].add(requester)
        reaction_extra=min(cap,max(0,int(signals.get("reaction_count") or 0))+max(0,int(signals.get("duplicate_count") or 0)))
        safe.append({
            "evidence_id":evidence_id,
            "cluster_id":cluster_id,
            "review_state":str(row.get("challenge_semantic_review") or "REVIEW_REQUIRED"),
            "requester_weight":1+reaction_extra,
        })
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps({"schema_v":1,"mapping":safe},separators=(",",":"))+"\n",encoding="utf-8")
    counts=Counter(x["cluster_id"] for x in safe)
    return {
        "cluster_count":len(counts),
        "clusters_with_3plus_requesters":sum(1 for cid in counts if len(requester_by_cluster.get(cid,set()))>=3),
    }


def update_private_drift_history(private_dir: Path, metrics: dict) -> dict:
    path=private_dir/"drift_history.jsonl"
    history=_read_jsonl(path)
    current={
        "date":_utc(),
        "processed":int(metrics.get("processed") or 0),
        "judge_agreement_rate_ppm":int(metrics.get("judge_agreement_rate_ppm") or 0),
        "discarded_disagreement":int(metrics.get("discarded_disagreement") or 0),
        "label_distribution":{
            label:int(metrics.get("label_count_"+label) or 0)
            for label in MODEL_LABELS
        },
    }
    alert=False
    if history:
        prev=history[-1] if isinstance(history[-1],dict) else {}
        prev_total=max(1,sum(int(x or 0) for x in (prev.get("label_distribution") or {}).values()))
        cur_total=max(1,sum(current["label_distribution"].values()))
        agreement_delta=abs(
            current["judge_agreement_rate_ppm"]-int(prev.get("judge_agreement_rate_ppm") or 0)
        )
        if agreement_delta>=200000:
            alert=True
        for label in MODEL_LABELS:
            p=int((prev.get("label_distribution") or {}).get(label) or 0)/prev_total
            c=current["label_distribution"][label]/cur_total
            if abs(c-p)>=0.20:
                alert=True
    history.append(current)
    _write_jsonl_private(path,history[-104:])
    return {"drift_alert":alert,"drift_history_points":len(history[-104:])}


def create_review_sample(private_dir: Path, count: int=5) -> dict:
    rows=_read_jsonl(private_dir/"train_labeled.jsonl")
    priority=[]
    regular=[]
    for row in rows:
        votes={x.get("judge"):x for x in row.get("judge_labels",[])}
        nli=votes.get("nli",{})
        llm=votes.get("local_llm",{})
        lex=votes.get("lexicon",{})
        against_lexicon=(nli.get("label") in MODEL_LABELS
            and nli.get("label")==llm.get("label")
            and nli.get("label")!=lex.get("label")
            and float(nli.get("confidence") or 0)>=0.90
            and float(llm.get("confidence") or 0)>=0.90)
        if against_lexicon:
            priority.append(row)
        elif row.get("final_label"):
            regular.append(row)
    rng=random.SystemRandom()
    rng.shuffle(priority)
    rng.shuffle(regular)
    sample=(priority+regular)[:max(0,count)]
    review=[]
    for row in sample:
        review.append({
            "id":row.get("id"),
            "normalized_text":row.get("normalized_text"),
            "source":row.get("source"),
            "structural_signals":row.get("structural_signals"),
            "judge_labels":row.get("judge_labels"),
            "final_label":row.get("final_label"),
            "label_origin":row.get("label_origin"),
            "date":_utc(),
            "reviewed_by":"",
            "review_result":"",
        })
    _write_jsonl_private(private_dir/"weekly_review_queue.jsonl",review)
    from html import escape
    rows=[]
    for item in review:
        judges=escape(json.dumps(item.get("judge_labels") or [],ensure_ascii=False))
        rows.append(
            "<article><h2>"+escape(str(item.get("id") or ""))+"</h2>"
            "<p><b>Testo:</b> "+escape(str(item.get("normalized_text") or ""))+"</p>"
            "<p><b>Sorgente:</b> "+escape(str(item.get("source") or ""))+"</p>"
            "<p><b>Etichetta:</b> "+escape(str(item.get("final_label") or ""))+"</p>"
            "<details><summary>Giudici</summary><pre>"+judges+"</pre></details>"
            "<p>Revisione Andrea: ____________________</p></article>"
        )
    html_doc=(
        "<!doctype html><html><head><meta charset='utf-8'><title>NEO weekly label review</title></head>"
        "<body><h1>Weekly shadow-label review</h1>"
        "<p>Privato. Priorità ai modelli concordi contro il lessico; compilazione manuale di Andrea.</p>"
        +"".join(rows)+"</body></html>"
    )
    (private_dir/"weekly_review.html").write_text(html_doc,encoding="utf-8")
    return {"review_sample_cases":len(review)}


def _safe_metrics(payload: dict) -> dict:
    out={}
    for key,value in payload.items():
        if key in PUBLIC_METRIC_KEYS or key in {
            "processed","eligible","discarded_disagreement","training_cases","version",
            "promotion_eligible","promotion_requires_manual_approval",
            "student_not_worse_public","student_not_worse_hidden","review_sample_cases",
            "judge_agreement_rate_ppm","drift_alert","drift_history_points","student_available",
        } or key.startswith(("student_public_class_","student_hidden_class_","lexicon_public_class_","lexicon_hidden_class_","label_count_","source_bucket_count_","label_source_count_","training_label_count_","training_label_used_","training_label_excluded_")) or key in {"training_class_balanced","training_classes_used","training_cases_selected","training_min_examples_per_class","training_max_class_weight_ratio"} or key.endswith(("_vendor_false_positives","_buyer_recall_ppm")):
            if isinstance(value,(int,float,bool)) or value is None:
                out[key]=value
            elif key=="version":
                out[key]=str(value)[:40]
    out["generated_at_utc"]=_utc()
    out["mode"]="shadow"
    return out


def main() -> int:
    p=argparse.ArgumentParser()
    p.add_argument("--private-dir",default=os.getenv("MODEL_LABEL_PRIVATE_DIR","private-labels"))
    p.add_argument("--output-dir",default="runtime/model-shadow")
    p.add_argument("--skip-heavy-judges",action="store_true")
    p.add_argument("--review-sample",action="store_true")
    args=p.parse_args()
    private_dir=Path(args.private_dir)
    output_dir=Path(args.output_dir)
    metrics={}
    archive=validate_archive(private_dir)
    metrics["cases"]=sum(int(x) for x in archive["splits"].values())
    judged=judge_private_archive(private_dir,use_models=not args.skip_heavy_judges)
    metrics.update(judged)
    metrics.update(update_private_drift_history(private_dir,metrics))
    selected_rows,selection_metrics=_student_training_selection(private_dir)
    metrics.update(selection_metrics)
    if len(selected_rows)<4 or int(selection_metrics.get("training_classes_used") or 0)<2:
        metrics["student_available"]=False
        metrics["training_cases"]=len(selected_rows)
        metrics["promotion_eligible"]=False
        metrics["promotion_requires_manual_approval"]=True
        if args.review_sample:
            metrics.update(create_review_sample(private_dir,5))
        safe=_safe_metrics(metrics)
        output_dir.mkdir(parents=True,exist_ok=True)
        (output_dir/"metrics.json").write_text(json.dumps(safe,sort_keys=True,separators=(",",":"))+"\n")
        print(json.dumps(safe,sort_keys=True,separators=(",",":")))
        return 0
    student_path=output_dir/"student.json"
    metrics.update(train_student(private_dir,student_path))
    metrics.update(evaluate_student(private_dir,student_path))
    cluster_path=output_dir/"challenge-cluster-map.json"
    metrics.update(cluster_challenges(private_dir,cluster_path))
    if args.review_sample:
        metrics.update(create_review_sample(private_dir,5))
    safe=_safe_metrics(metrics)
    output_dir.mkdir(parents=True,exist_ok=True)
    (output_dir/"metrics.json").write_text(json.dumps(safe,sort_keys=True,separators=(",",":"))+"\n",encoding="utf-8")
    print(json.dumps(safe,sort_keys=True,separators=(",",":")))
    return 0


if __name__=="__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        import traceback
        allowed = {"ImportError", "ModuleNotFoundError", "ValueError", "RuntimeError", "OSError", "TypeError", "KeyError"}
        kind = type(exc).__name__
        frames = [frame.lineno for frame in traceback.extract_tb(exc.__traceback__)
                  if Path(frame.filename).resolve() == Path(__file__).resolve()]
        print(json.dumps({"ok": False, "reason": "PRIVATE_BATCH_FAILED",
                          "error_type": kind if kind in allowed else "MODEL_ERROR",
                          "batch_lines": frames}))
        raise SystemExit(1)
