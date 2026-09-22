"""Problem-first discovery helpers for NEO/MYCELIX.

Pure stdlib so query attribution and observed-pain extraction can be regression-tested
without importing the web runtime.
"""
from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

PAIN_MARKERS = (
    "manual","manually","repetitive","time consuming","time-consuming","frustrat",
    "waste time","workaround","backlog","copy paste","copy/paste","rekey",
    "need help","looking for","struggle","struggling","pain","problem",
)
BUY_MARKERS = (
    "need help","looking for","seeking","recommend","how can i","want someone",
)
PAID_MARKERS = (
    "budget","will pay","paid","hiring","hire","freelance","freelancer",
    "contractor","fixed price","fixed-price","hourly","quote",
)
STOP = {
    "site","reddit","github","freelance","jobs","news","ycombinator","wikipedia",
    "manual","repetitive","workflow","workaround","looking","need","help","pain",
    "point","small","business","operations","team","teams","customer","customers",
    "problem","problems","software","pricing","subscription","already","automated",
    "solved","worth","query","market",
}


def _tokens(text: str) -> set[str]:
    out=set()
    for raw in re.split(r"[^a-zA-Z0-9]+",(text or "").lower()):
        if len(raw) >= 3 and raw not in STOP:
            out.add(raw)
    return out


def natural_search_seed(query: str, meta: dict | None = None) -> str:
    meta=meta if isinstance(meta,dict) else {}
    for key in ("search_alias_used","term","job_to_be_done"):
        value=" ".join(str(meta.get(key) or "").split()).strip()
        if value:
            return value[:180]
    problem=str(meta.get("problem_key") or "")
    if ":" in problem:
        tail=problem.split(":",1)[1].replace("_"," ").strip()
        if tail and tail not in {"generic technology","general"}:
            return tail[:180]

    q=str(query or "")
    q=re.sub(r"-?site:[^\s)]+"," ",q,flags=re.I)
    q=re.sub(r"\b(?:OR|AND|NOT)\b"," ",q,flags=re.I)
    q=q.replace('"'," ").replace("("," ").replace(")"," ")
    words=[w for w in re.split(r"\s+",q) if w]
    cleaned=[]
    seen=set()
    for word in words:
        key=re.sub(r"[^a-zA-Z0-9_-]","",word).lower()
        if not key or key in STOP or key in seen:
            continue
        seen.add(key)
        cleaned.append(word.strip(" ,;:"))
        if len(cleaned)>=8:
            break
    return " ".join(cleaned)[:180]


def query_relevance(title: str, body: str, query: str, meta: dict | None = None) -> dict:
    seed=natural_search_seed(query,meta)
    target=_tokens(seed)
    text=_tokens((title or "")+" "+(body or ""))
    overlap=sorted(target & text)
    if not target:
        score=0
    else:
        ratio=len(overlap)/max(1,len(target))
        score=min(100,int(round(ratio*100)))
        if len(overlap)>=2:
            score=max(score,55)
        elif len(overlap)==1 and len(target)<=3:
            score=max(score,45)
    return {
        "seed":seed,
        "target_tokens":sorted(target),
        "overlap":overlap,
        "score":score,
        "relevant":bool(score>=45 and overlap),
    }


def _sentence_with_marker(text: str) -> str:
    chunks=[x.strip(" \t\r\n-:;") for x in re.split(r"(?<=[.!?])\s+|\n+",str(text or "")) if x.strip()]
    for chunk in chunks:
        low=chunk.lower()
        if any(m in low for m in PAIN_MARKERS+BUY_MARKERS+PAID_MARKERS):
            return chunk[:280]
    return (chunks[0][:280] if chunks else "")


def _customer_hint(text: str, family: str) -> str:
    low=(text or "").lower()
    patterns=(
        ("small business","small businesses"),
        ("agency","agencies"),
        ("support team","customer support teams"),
        ("customer support","customer support teams"),
        ("sales team","sales teams"),
        ("sales rep","sales teams"),
        ("developer","development teams"),
        ("devops","DevOps teams"),
        ("operations","operations teams"),
        ("ecommerce","ecommerce teams"),
        ("marketing","marketing teams"),
        ("accounting","finance teams"),
        ("hr ","HR teams"),
    )
    for marker,label in patterns:
        if marker in low:
            return label
    family_defaults={
        "developer_tools":"development teams",
        "integration_api":"operations and integration teams",
        "spreadsheet_process":"operations teams",
        "customer_support":"customer support teams",
        "crm_lead_ops":"sales teams",
        "marketing_seo":"marketing teams",
        "ecommerce_tools":"ecommerce teams",
        "ai_tools":"business teams",
        "workflow_automation":"operations teams",
    }
    return family_defaults.get(family,"teams experiencing the observed problem")


def observed_pain_candidates(
    web_research: list[dict],
    query_meta: dict[str,dict] | None = None,
    limit: int = 10,
) -> list[dict]:
    """Extract conservative, source-backed hypothesis candidates from observed results.

    These are only hypotheses. They never become commercial evidence by themselves.
    """
    query_meta=query_meta or {}
    out=[]
    seen=set()
    for group in web_research or []:
        if not isinstance(group,dict):
            continue
        query=" ".join(str(group.get("query") or "").split())
        meta=query_meta.get(query.lower()) or {}
        role=str(meta.get("role") or meta.get("class") or "")
        if role=="disconfirm":
            continue
        family=str(meta.get("family") or "")
        if not family:
            continue
        for item in group.get("results") or []:
            if not isinstance(item,dict):
                continue
            title=str(item.get("title") or "").strip()
            body=str(item.get("snippet") or item.get("text") or "").strip()
            url=str(item.get("url") or "").strip()
            if not title or not url:
                continue
            rel=query_relevance(title,body,query,meta)
            if not rel["relevant"]:
                continue
            low=(title+" "+body).lower()
            pain=[m for m in PAIN_MARKERS if m in low]
            buy=[m for m in BUY_MARKERS if m in low]
            paid=[m for m in PAID_MARKERS if m in low]
            if not pain and not buy:
                continue
            host=(urlparse(url).hostname or "").lower()
            key=host+"|"+title.lower()
            if key in seen:
                continue
            seen.add(key)
            observed=_sentence_with_marker(body) or title[:280]
            customer=_customer_hint(query+" "+title+" "+body,family)
            term=rel["seed"] or title[:120]
            score=min(100,35+rel["score"]//3+min(20,len(pain)*5)+min(15,len(buy)*7)+min(15,len(paid)*7))
            out.append({
                "family":family,
                "customer":customer,
                "job":title[:180],
                "pain":observed,
                "term":term[:160],
                "search_aliases":[x for x in [term[:120],title[:120]] if x],
                "source_url":url,
                "source_domain":host,
                "source_title":title[:220],
                "source_query":query[:500],
                "source_role":role,
                "relevance_score":rel["score"],
                "pain_markers":pain[:8],
                "buy_markers":buy[:8],
                "paid_markers":paid[:8],
                "priority":score,
            })
    out.sort(key=lambda x:(int(x.get("priority") or 0),int(x.get("relevance_score") or 0)),reverse=True)
    return out[:max(1,min(limit,20))]
