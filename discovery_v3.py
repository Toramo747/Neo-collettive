"""Problem-first discovery helpers for NEO/MYCELIX.

Pure stdlib so query attribution and observed-pain extraction can be regression-tested
without importing the web runtime.
"""
from __future__ import annotations

import html
import re
from typing import Any
from urllib.parse import urlparse

from runtime_boundary import is_control_plane_text
from evidence_integrity import family_text_matches, is_self_contamination

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


OBSERVED_HYPOTHESIS_SCHEMA_VERSION = 7

# Generic employment vacancies can contain words such as "hiring", "looking for"
# and "compensation", which are not evidence of a buyer problem by themselves.
JOB_POSTING_MARKERS = (
    "job type","full_time","full time","part_time","part time","remote job",
    "job description","responsibilities","requirements","apply now","salary",
    "compensation","category:",
)
OPERATIONAL_PAIN_MARKERS = (
    "manual","manually","repetitive","time consuming","time-consuming",
    "frustrat","waste time","workaround","backlog","copy paste","copy/paste",
    "rekey","struggle","struggling","pain point","bottleneck","error-prone",
    "error prone","take hours","takes hours",
)
OPERATIONAL_TIME_BURDEN_RE = re.compile(
    r"\b(?:takes?|spend(?:s|ing)?|waste(?:s|d|ing)?)\b"
    r"[^.!?\n]{0,60}\b(?:\d+(?:\s*-\s*\d+)?\s+)?hours?\s+(?:per|a)\s+week\b",
    re.I,
)

EVIDENCE_CONTRACT_SCHEMA_VERSION = 1
FREQUENCY_MARKERS = (
    "every day","daily","every week","weekly","each week","per week",
    "every month","monthly","repeatedly","recurring","again and again",
)
IMPACT_MARKERS = (
    "waste time","takes hours","take hours","time consuming","time-consuming",
    "error-prone","error prone","backlog","delay","delays","missed","rework",
)

LAUNCH_TITLE_MARKERS = (
    "show hn:","launch hn:","introducing ","announcing ","we built ","i built ",
)
MAKER_SELF_REPORT_MARKERS = (
    "i built","i made","i created","my project","our project","our product",
    "i've been a developer","i have been a developer","vibe-coded","vibe coded",
    "i've been using it","i have been using it","fixing the problems as they come",
)

RECRUITING_INTERVIEW_MARKERS = (
    "technical interview","job interview","interview loop","interview process",
    "interview question","interview outcome","hiring decision","recruiting process",
    "candidate interview","no hire",
)

FAMILY_PROCESS_MARKERS = {
    "spreadsheet_process":("spreadsheet","spreadsheets","excel","google sheets","csv"),
    "integration_api":("api","apis","webhook","webhooks","sync","synchronization","integration","integrations"),
    "customer_support":("customer email","support email","shared inbox","customer support","support ticket","support tickets"),
    "crm_lead_ops":("lead","leads","crm","sales follow-up","lead routing","lead qualification"),
    "document_processing":("pdf","document","documents","invoice","invoices","form","forms"),
    "data_cleanup":("duplicate data","deduplication","data cleanup","csv"),
    "website_audit":("broken link","accessibility","website qa","website audit"),
    "developer_tools":("devops","deployment","ci/cd","developer","build","release"),
    "cybersecurity_tools":("vulnerability","phishing","security","alert","remediation"),
}

def _family_process_grounded(source_fact: str, family: str) -> bool | None:
    markers=FAMILY_PROCESS_MARKERS.get(str(family or ""))
    if not markers:
        return None
    low=(" "+_clean_source_text(source_fact).lower()+" ")
    return any(marker in low for marker in markers)


def _token_key(raw: str) -> str:
    """Light normalization for retrieval only; never used as evidence identity."""
    token=(raw or "").lower()
    if len(token)>5 and token.endswith("ies"):
        token=token[:-3]+"y"
    elif len(token)>4 and token.endswith("s") and not token.endswith(("ss","us","is")):
        token=token[:-1]
    return token


def _tokens(text: str) -> set[str]:
    out=set()
    for raw in re.split(r"[^a-zA-Z0-9]+",(text or "").lower()):
        key=_token_key(raw)
        if len(key) >= 3 and key not in STOP:
            out.add(key)
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
    meta=meta if isinstance(meta,dict) else {}
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

    role=str(meta.get("role") or meta.get("class") or "").strip().lower()
    min_score=45
    min_overlap=1
    # Structured commercial/job feeds are noisy. One generic token such as
    # "automation" or "workflow" must not make an unrelated vacancy evidence
    # for the active thesis.
    if role=="paid_market":
        min_score=55
        min_overlap=1 if len(target)<=1 else 2

    return {
        "seed":seed,
        "target_tokens":sorted(target),
        "overlap":overlap,
        "score":score,
        "role":role,
        "min_score":min_score,
        "min_overlap":min_overlap,
        "relevant":bool(score>=min_score and len(overlap)>=min_overlap),
    }


def structured_job_relevance(title: str, body: str, query: str, meta: dict | None = None) -> dict:
    """Require the job title itself to match a paid-market thesis, not only its description."""
    rel=query_relevance(title,body,query,meta)
    target=set(rel.get("target_tokens") or [])
    title_tokens=_tokens(title)

    def same_concept(a: str, b: str) -> bool:
        if a==b:
            return True
        # Conservative morphology for job titles, e.g. report/reporting.
        if min(len(a),len(b))>=5 and (a.startswith(b) or b.startswith(a)):
            return True
        return False

    title_overlap=sorted({
        target_token
        for target_token in target
        if any(same_concept(target_token,title_token) for title_token in title_tokens)
    })
    needed=1 if len(target)<=1 else 2
    rel["title_overlap"]=title_overlap
    rel["title_min_overlap"]=needed
    rel["base_relevant"]=bool(rel.get("relevant"))
    rel["relevant"]=bool(rel.get("relevant") and len(title_overlap)>=needed)
    return rel


def _sentence_with_marker(text: str) -> str:
    chunks=[x.strip(" \t\r\n-:;") for x in re.split(r"(?<=[.!?])\s+|\n+",str(text or "")) if x.strip()]
    for chunk in chunks:
        low=chunk.lower()
        if any(m in low for m in PAIN_MARKERS+BUY_MARKERS+PAID_MARKERS):
            return chunk[:280]
    return (chunks[0][:280] if chunks else "")


def _clean_source_text(value: str) -> str:
    text=html.unescape(str(value or ""))
    text=re.sub(r"<[^>]+>"," ",text)
    text=re.sub(r"\s+"," ",text)
    return text.strip()


def _sentence_chunks(value: str) -> list[str]:
    cleaned=_clean_source_text(value)
    return [
        x.strip(" \t\r\n-:;")
        for x in re.split(r"(?<=[.!?])\s+|\n+",cleaned)
        if x.strip()
    ]


def _first_operational_pain_sentence(value: str) -> str:
    """Return a compact source-backed pain window with the pain marker preserved.

    Search snippets can collapse many bullets into one long sentence. Returning the
    first 280 characters of that blob could drop the actual pain marker while keeping
    unrelated product copy. Center the excerpt on the observed burden instead.
    """
    for chunk in _sentence_chunks(value):
        low=chunk.lower()
        hits=[
            (low.find(marker),marker)
            for marker in OPERATIONAL_PAIN_MARKERS
            if marker in low
        ]
        time_match=OPERATIONAL_TIME_BURDEN_RE.search(low)
        if time_match:
            hits.append((time_match.start(),"time_burden"))
        hits=[x for x in hits if x[0]>=0]
        if not hits:
            continue
        pos,_=min(hits,key=lambda x:x[0])
        start=max(0,pos-110)
        end=min(len(chunk),pos+170)
        window=chunk[start:end].strip(" \t\r\n-:;,")
        return window[:280]
    return ""


def build_evidence_contract(
    title: str,
    body: str,
    query: str,
    family: str,
    role: str,
    customer: str,
    job: str,
) -> dict:
    """Create a source-backed evidence contract and run a deterministic skeptic.

    The contract separates what the source literally states from NEO's inference.
    It guards hypothesis creation only; it does not relax or replace the commercial gate.
    """
    clean_title=_clean_source_text(title)
    clean_body=_clean_source_text(body)
    text=(" "+clean_title+" "+clean_body+" ").lower()
    source_fact=_first_operational_pain_sentence(clean_body)
    buyer_signals=sorted({
        marker for marker in BUY_MARKERS+PAID_MARKERS
        if marker in text
    })
    frequency=[marker for marker in FREQUENCY_MARKERS if marker in text][:4]
    impact=[marker for marker in IMPACT_MARKERS if marker in text][:4]

    if _is_recruiting_or_interview_context(clean_title,clean_body):
        context_type="recruiting_interview"
    elif _is_generic_job_listing(clean_title,clean_body):
        context_type="job_listing"
    elif _is_launch_title(clean_title):
        context_type="product_launch"
    else:
        context_type="operational"

    job_tokens=_tokens(job)
    source_process_tokens=_tokens(clean_title+" "+source_fact)
    process_overlap=sorted(job_tokens & source_process_tokens)
    family_process_grounded=_family_process_grounded(source_fact,family)
    fact_low=source_fact.lower()
    strong_pain=any(
        marker in fact_low
        for marker in OPERATIONAL_PAIN_MARKERS
        if marker not in {"manual","manually"}
    ) or bool(OPERATIONAL_TIME_BURDEN_RE.search(fact_low))
    launch_customer_pain=bool(
        strong_pain
        or (buyer_signals and (frequency or impact))
    )

    reasons=[]
    if not source_fact:
        reasons.append("no_explicit_operational_pain")
    if not str(customer or "").strip():
        reasons.append("actor_missing")
    if not str(job or "").strip():
        reasons.append("process_missing")
    if source_fact and family_process_grounded is False:
        reasons.append("process_not_grounded_in_source_fact")
    elif source_fact and family_process_grounded is None and job_tokens and not process_overlap:
        reasons.append("process_not_grounded_in_source_fact")
    if context_type=="product_launch" and _is_maker_self_report(clean_body) and not buyer_signals:
        reasons.append("maker_self_report_without_buyer_signal")
    if context_type=="product_launch" and source_fact and not launch_customer_pain:
        reasons.append("product_feature_without_customer_pain")

    passed=not reasons
    confidence=(
        0.9 if source_fact and buyer_signals and (frequency or impact)
        else 0.82 if source_fact and buyer_signals
        else 0.72 if source_fact
        else 0.2
    )
    inference=(
        f"{customer} may pay to solve {job} because the source reports an operational pain."
        if customer and job and source_fact else ""
    )
    return {
        "schema_v":EVIDENCE_CONTRACT_SCHEMA_VERSION,
        "actor":str(customer or "")[:160],
        "process":str(job or "")[:180],
        "pain":source_fact,
        "frequency":frequency,
        "cost_or_impact":impact,
        "buyer_signal":buyer_signals[:8],
        "source_fact":source_fact,
        "inference":inference[:300],
        "confidence":round(confidence,2),
        "context_type":context_type,
        "source_query":str(query or "")[:500],
        "skeptic":{
            "passed":passed,
            "reasons":reasons,
            "checks":{
                "source_fact_present":bool(source_fact),
                "fact_inference_separated":bool(source_fact and inference and source_fact!=inference),
                "operational_pain_supported":bool(source_fact),
                "process_grounded_in_source_fact":bool(
                    family_process_grounded
                    if family_process_grounded is not None
                    else (not job_tokens or process_overlap)
                ),
                "launch_customer_pain_supported":bool(context_type!="product_launch" or launch_customer_pain),
            },
        },
    }


def _is_launch_title(title: str) -> bool:
    low=_clean_source_text(title).lower()
    return any(low.startswith(x) for x in LAUNCH_TITLE_MARKERS)


def _is_maker_self_report(body: str) -> bool:
    low=_clean_source_text(body).lower()
    return any(x in low for x in MAKER_SELF_REPORT_MARKERS)


def _is_recruiting_or_interview_context(title: str, body: str) -> bool:
    title_low=_clean_source_text(title).lower()
    text=(" "+title_low+" "+_clean_source_text(body).lower()+" ")
    if "interview" in title_low:
        return True
    return any(marker in text for marker in RECRUITING_INTERVIEW_MARKERS)


def _is_generic_job_listing(title: str, body: str) -> bool:
    """Detect ordinary employment vacancies that can mimic commercial demand."""
    text=(" "+_clean_source_text(title)+" "+_clean_source_text(body)+" ").lower()
    marker_hits=sum(1 for marker in JOB_POSTING_MARKERS if marker in text)
    role_title=bool(re.search(
        r"\b(?:senior|junior|lead|staff|principal)?\s*"
        r"(?:data scientist|software engineer|ai engineer|ml engineer|developer|"
        r"devops engineer|product manager|designer|analyst|consultant)\b",
        text,
    ))
    return marker_hits>=2 or (role_title and marker_hits>=1)


def _has_explicit_operational_pain(title: str, body: str) -> bool:
    text=(" "+_clean_source_text(title)+" "+_clean_source_text(body)+" ").lower()
    return (
        any(marker in text for marker in OPERATIONAL_PAIN_MARKERS)
        or bool(OPERATIONAL_TIME_BURDEN_RE.search(text))
    )


def _concise_seed(seed: str, family: str) -> str:
    value=_clean_source_text(seed)
    low=value.lower()
    if not value or _is_launch_title(value) or len(value.split())>9:
        defaults={
            "ai_tools":"AI-assisted business workflow",
            "developer_tools":"developer workflow",
            "integration_api":"system integration",
            "spreadsheet_process":"spreadsheet process",
            "customer_support":"customer support workflow",
            "crm_lead_ops":"lead follow-up workflow",
            "marketing_seo":"marketing workflow",
            "ecommerce_tools":"ecommerce operations",
            "workflow_automation":"business workflow",
            "document_processing":"document processing",
            "data_cleanup":"data cleanup",
            "website_audit":"website quality",
            "cybersecurity_tools":"security operations",
        }
        return defaults.get(family,family.replace("_"," ") or "business process")
    # Search operators or query tails are not a human problem label.
    value=re.sub(r"\b(?:need help|manual workaround|freelance hiring budget|fixed price hourly job|software pricing subscription)\b"," ",value,flags=re.I)
    value=re.sub(r"\s+"," ",value).strip(" -:;,")
    return value[:120] or family.replace("_"," ")


def _human_job_hint(title: str, body: str, seed: str, family: str) -> tuple[str,str,list[str]]:
    text=(" "+_clean_source_text(title)+" "+_clean_source_text(body)+" ").lower()
    rules=(
        (("customer email","support email","shared inbox","email support"),"triage and respond to customer emails","customer email support"),
        (("lead qualification","crm follow","inbound lead","lead routing"),"qualify and follow up on inbound leads","lead qualification and CRM follow-up"),
        (("pdf extraction","document extraction","invoice data","document processing"),"extract structured data from business documents","document data extraction"),
        (("spreadsheet","excel","csv cleanup","google sheets"),"clean and automate recurring spreadsheet work","spreadsheet process automation"),
        (("devops","deployment","ci/cd","continuous integration"),"reduce manual deployment and DevOps maintenance work","DevOps workflow"),
        (("broken link","website audit","accessibility audit","website qa"),"find and fix recurring website quality issues","website quality audit"),
        (("duplicate data","deduplication","data cleanup"),"clean and deduplicate operational data","data cleanup"),
        (("agent memory","memory for ai agents","mcp memory","persistent memory","context memory"),"maintain reliable memory and context for AI agents","AI agent memory"),
        (("vulnerability","phishing","security assessment","alert fatigue"),"triage recurring security findings and remediation work","security operations"),
        (("manual transfer","api integration","webhook","data sync","synchronization"),"keep data synchronized across business systems","system integration"),
    )
    for markers,job,term in rules:
        if any(m in text for m in markers):
            return job,term,[term,job]

    concise=_concise_seed(seed,family)
    pain_low=_clean_source_text(body).lower()
    if any(x in pain_low for x in ("fixing","maintain","maintenance","production","breaks","failures","reliability")):
        job=f"operate {concise} reliably"
    elif any(x in pain_low for x in ("manual","manually","repetitive","copy paste","copy/paste","time consuming","time-consuming")):
        job=f"reduce repetitive manual work around {concise}"
    elif any(x in pain_low for x in ("backlog","frustrat","struggle","problem","need help")):
        job=f"reduce recurring problems around {concise}"
    else:
        job=f"improve the recurring workflow around {concise}"
    return job[:180],concise[:120],[concise[:120],job[:120]]


def _customer_from_source(source_text: str, family: str, query_text: str = "") -> str:
    # Source wording is evidence; query wording is only a fallback and must not
    # overwrite a concrete actor named by the source.
    source=_clean_source_text(source_text)
    hinted=_customer_hint(source,family)
    if hinted!="teams experiencing the observed problem":
        return hinted
    return _customer_hint(query_text,family)


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
    reject_self_contamination: bool = False,
    require_family_in_pain: bool = False,
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
            if reject_self_contamination and is_self_contamination(
                url,
                str(item.get("source") or ""),
                title+" "+body,
            ):
                continue
            rel=query_relevance(title,body,query,meta)
            if not rel["relevant"]:
                continue
            clean_title=_clean_source_text(title)
            clean_body=_clean_source_text(body)
            if is_control_plane_text(clean_title+" "+clean_body):
                continue
            low=(clean_title+" "+clean_body).lower()
            pain=[m for m in PAIN_MARKERS if m in low]
            buy=[m for m in BUY_MARKERS if m in low]
            paid=[m for m in PAID_MARKERS if m in low]
            if not pain and not buy:
                continue
            # Employment vacancies frequently contain "hiring", "looking for" and
            # "compensation". Those phrases describe recruitment, not a source-backed
            # operational problem. Keep a vacancy only when it explicitly states the
            # workflow pain that is driving the hiring.
            if _is_generic_job_listing(clean_title,clean_body) and not _has_explicit_operational_pain(clean_title,clean_body):
                continue
            # Recruiting/interview analysis can contain buyer-like words ("looking for",
            # "hire", "problem") without describing an operational workflow pain.
            if _is_recruiting_or_interview_context(clean_title,clean_body) and not _has_explicit_operational_pain(clean_title,clean_body):
                continue
            # Product-launch posts describing the maker's own build pain are useful
            # technical anecdotes, but not a source-backed customer problem.
            if _is_launch_title(clean_title) and _is_maker_self_report(clean_body) and not buy and not paid:
                continue
            host=(urlparse(url).hostname or "").lower()
            key=host+"|"+title.lower()
            if key in seen:
                continue
            seen.add(key)
            source_fact=_first_operational_pain_sentence(clean_body)
            if not source_fact:
                continue
            if require_family_in_pain and not family_text_matches(family,source_fact):
                continue
            # Ground actor and process in the local pain context, not unrelated words
            # elsewhere in a long search snippet or in the query that found it.
            customer=_customer_from_source(source_fact+" "+clean_title,family,"")
            seed=rel["seed"] or clean_title[:120]
            job,term,aliases=_human_job_hint(clean_title,source_fact,seed,family)
            contract=build_evidence_contract(
                clean_title,clean_body,query,family,role,customer,job
            )
            if not bool((contract.get("skeptic") or {}).get("passed")):
                continue
            observed=str(contract.get("source_fact") or "")[:280]
            score=min(100,35+rel["score"]//3+min(20,len(pain)*5)+min(15,len(buy)*7)+min(15,len(paid)*7))
            if _is_launch_title(clean_title):
                score=max(0,score-12)
            out.append({
                "hypothesis_schema_v":OBSERVED_HYPOTHESIS_SCHEMA_VERSION,
                "family":family,
                "customer":customer,
                "job":job[:180],
                "pain":observed,
                "term":term[:160],
                "search_aliases":[x for x in aliases if x][:4],
                "source_url":url,
                "source_domain":host,
                "source_title":title[:220],
                "source_query":query[:500],
                "source_role":role,
                "relevance_score":rel["score"],
                "pain_markers":pain[:8],
                "buy_markers":buy[:8],
                "paid_markers":paid[:8],
                "evidence_contract":contract,
                "priority":score,
            })
    out.sort(key=lambda x:(int(x.get("priority") or 0),int(x.get("relevance_score") or 0)),reverse=True)
    return out[:max(1,min(limit,20))]
