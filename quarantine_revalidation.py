"""Bounded legacy-quarantine revalidation for MYCELIX commercial evidence.

Only legacy_unverified_tagger_v1 rows are eligible. Promotion always requires a
fresh successful fetch followed by the current evidence-integrity checks.
"""
from __future__ import annotations

import time
from typing import Any, Awaitable, Callable
from urllib.parse import urlparse

from discovery_v3 import query_relevance
from evidence_integrity import (
    EVIDENCE_SCHEMA_VERSION,
    TAGGER_VERSION,
    canonical_domain,
    canonical_problem_key,
    canonical_url,
    commercial_family,
    contains_term,
    demand_signal_type,
    family_relevance_terms,
    find_term_positions,
    gate_eligible_problem_key,
    generic_web_pain_allowed,
    is_launch_title,
    is_vendor_content,
    is_self_contamination,
    structured_paid_source,
)

LEGACY_QUARANTINE_REASON = "legacy_unverified_tagger_v1"
TERMINAL_REVALIDATION = {"failed", "unreachable", "promoted"}
EXCLUDED_QUARANTINE_REASONS = {"disconfirm", "seller_launch", "family_mismatch"}
POSITIVE_SIGNALS = {"PAIN", "BUY_INTENT", "PAID_DEMAND"}
NOISE_DOMAINS = (
    "wikipedia.org", "dict.cc", "leo.org", "linguee.de", "pons.com",
    "langenscheidt.com", "dwds.de",
)
GITHUB_NOISE = (
    "family trust", "trust vault", "trademark", "patent-pending", "patent pending",
    "ownership", "token sale", "airdrop", "wallet address", "revenue command dashboard",
    "master roadmap", "roadmap maître", "roadmap master",
)
GITHUB_DEMAND = (
    "need help", "looking for", "seeking", "hiring", "budget", "paid", "manual",
    "repetitive", "problem", "pain", "customer", "client", "freelance", "contractor",
)
BUYER_STRONG_TERMS = (
    "budget", "will pay", "paid job", "fixed-price", "fixed price", "hourly",
    "per hour", "hiring", "hire someone", "hire a", "freelance", "freelancer",
    "contractor", "seeking contractor", "quote requested", "request a quote",
)
WEAK_TERMS = (
    "customer", "client", "manual", "workflow", "crm", "spreadsheet",
    "automation", "problem", "pain", "workaround",
)


def _excluded(row: dict[str, Any]) -> bool:
    reason=str(row.get("quarantine_reason") or "")
    if reason != LEGACY_QUARANTINE_REASON:
        return True
    if reason in EXCLUDED_QUARANTINE_REASONS:
        return True
    if str(row.get("revalidated") or "") in TERMINAL_REVALIDATION:
        return True
    if "DISCONFIRM" in set(row.get("signal_types") or []):
        return True
    if str(row.get("signal_reverted") or "") == "seller_launch":
        return True
    if str(row.get("attribution_reverted") or "") == "family_mismatch":
        return True
    return False


def _family_context(title: str, body: str, family: str) -> tuple[str, int, int]:
    title_low=(title or "").lower()
    body_low=(body or "").lower()
    terms=family_relevance_terms(family)
    title_hits=sum(1 for term in terms if contains_term(title_low,term))
    body_hits=sum(1 for term in terms if contains_term(body_low,term))
    combined=title_low+" "+body_low
    windows=[]
    for term in terms:
        for start,end in find_term_positions(combined,term,8):
            windows.append(combined[max(0,start-220):min(len(combined),end+220)])
            if len(windows)>=8:
                break
        if len(windows)>=8:
            break
    return " ".join(windows),title_hits,body_hits


def evaluate_fetched_legacy_row(
    row: dict[str, Any],
    fetched: dict[str, Any],
    *,
    now_epoch: float | None = None,
    self_contamination_guard: bool = True,
    seller_launch_guard: bool = True,
    vendor_content_guard: bool = True,
    web_buyer_voice_guard: bool = True,
    family_match_guard: bool = True,
    strong_pain_only: bool = True,
) -> dict[str, Any]:
    """Retag a freshly fetched legacy row with the same core guards as new ingress."""
    now=float(now_epoch if now_epoch is not None else time.time())
    url=canonical_url(str(fetched.get("url") or row.get("url") or ""))
    title=str(fetched.get("title") or row.get("title") or "").strip()
    body=str(fetched.get("body") or fetched.get("snippet") or fetched.get("text") or "").strip()
    source=str(row.get("source") or fetched.get("source") or "revalidation")
    query=str(row.get("query") or "")
    query_role=str(row.get("query_role") or "")
    query_class=str(row.get("query_class") or query_role or "unknown")
    stored_family=str(row.get("family") or "").strip()
    text=(title+" "+body).strip()
    raw_host=(urlparse(url).hostname or "").lower()
    host=canonical_domain(raw_host)

    def failed(reason: str, updates: dict[str, Any] | None = None) -> dict[str, Any]:
        return {
            "ok": False,
            "reason": reason,
            "updates": dict(updates or {}),
            "query_class": query_class,
        }

    if not url or not title or not body:
        return failed("missing_required_field")
    if self_contamination_guard and is_self_contamination(url,source,text):
        return failed("self_contamination_rejected")
    if not host or any(host==n or host.endswith("."+n) for n in NOISE_DOMAINS):
        return failed("noise_domain")

    title_low=title.lower()
    body_low=body.lower()
    if host=="github.com":
        if any(x in title_low or x in body_low for x in GITHUB_NOISE):
            return failed("github_noise")
        if not any(contains_term(title_low+" "+body_low,x) for x in GITHUB_DEMAND):
            return failed("github_no_buyer_problem_context")

    if seller_launch_guard and is_launch_title(title):
        launch_signals=demand_signal_type(
            title,body,query_role,
            strong_pain_only=strong_pain_only,
            seller_launch_guard=True,
            url=url,source=source,
            vendor_content_guard=vendor_content_guard,
            web_buyer_voice_guard=web_buyer_voice_guard,
        )
        return failed("seller_launch",{
            "signal_types":[x for x in launch_signals if x!="PAIN"],
            "gate_eligible":False,
            "quarantine_reason":"seller_launch",
            "context_type":"product_launch",
            "signal_reverted":"seller_launch",
        })

    if vendor_content_guard and is_vendor_content(title,body,url,source):
        vendor_signals=demand_signal_type(
            title,body,query_role,
            strong_pain_only=strong_pain_only,
            seller_launch_guard=seller_launch_guard,
            url=url,source=source,
            vendor_content_guard=True,
            web_buyer_voice_guard=web_buyer_voice_guard,
        )
        return failed("vendor_content",{
            "signal_types":[x for x in vendor_signals if x!="PAIN"],
            "gate_eligible":False,
            "quarantine_reason":"vendor_content",
            "context_type":"vendor_content",
            "signal_reverted":"vendor_content",
        })
    if web_buyer_voice_guard and not generic_web_pain_allowed(title,body,url,source):
        return failed("web_buyer_voice_missing",{
            "gate_eligible":False,
            "quarantine_reason":"web_buyer_voice_missing",
            "signal_reverted":"web_buyer_voice_missing",
        })

    observed_family=commercial_family(text)
    if observed_family=="other":
        return failed("no_family")
    if family_match_guard and stored_family and observed_family!=stored_family:
        return failed("family_mismatch",{
            "gate_eligible":False,
            "quarantine_reason":"family_mismatch",
            "attribution_reverted":"family_mismatch",
        })

    problem_key=canonical_problem_key(
        stored_family or observed_family,
        str(row.get("problem_key") or ((stored_family or observed_family)+":general")),
    )
    problem_family=problem_key.split(":",1)[0].strip().lower() if problem_key else ""
    if family_match_guard and problem_family and problem_family!=observed_family:
        return failed("family_mismatch",{
            "gate_eligible":False,
            "quarantine_reason":"family_mismatch",
            "attribution_reverted":"family_mismatch",
        })

    context,title_hits,body_hits=_family_context(title,body,observed_family)
    if title_hits<1 and body_hits<2:
        return failed("weak_family_relevance")
    if len(context)<40:
        return failed("context_too_short")

    meta={
        "family":stored_family or observed_family,
        "role":query_role,
        "class":query_class,
        "problem_key":problem_key,
        "problem_id":str(row.get("problem_id") or ""),
        "thesis_id":str(row.get("thesis_id") or ""),
        "search_alias_used":str(row.get("search_alias_used") or ""),
    }
    relevance=query_relevance(title,body,query,meta)
    if query and not relevance.get("relevant"):
        return failed("query_irrelevant")

    signal_types=demand_signal_type(
        title,context,query_role,
        strong_pain_only=strong_pain_only,
        seller_launch_guard=seller_launch_guard,
        url=url,source=source,
        vendor_content_guard=vendor_content_guard,
        web_buyer_voice_guard=web_buyer_voice_guard,
    )
    if structured_paid_source(source,query_role):
        signal_types=sorted(set(signal_types)|{"PAID_DEMAND","BUY_INTENT"})
    positive=bool(POSITIVE_SIGNALS & set(signal_types))
    if not positive:
        return failed("no_demand_signal",{"signal_types":signal_types})

    if not gate_eligible_problem_key(problem_key):
        return failed("generic_or_nonconcrete_problem",{"signal_types":signal_types})

    strong=[
        term for term in BUYER_STRONG_TERMS
        if "PAID_DEMAND" in signal_types and contains_term(context,term)
    ]
    if structured_paid_source(source,query_role) and "PAID_DEMAND" in signal_types and not strong:
        strong=["structured_job_market"]
    weak=[term for term in WEAK_TERMS if contains_term(context,term)]

    return {
        "ok": True,
        "reason": "promoted",
        "query_class": query_class,
        "updates": {
            "schema_v":EVIDENCE_SCHEMA_VERSION,
            "tagger_v":TAGGER_VERSION,
            "migration_v":EVIDENCE_SCHEMA_VERSION,
            "gate_eligible":True,
            "quarantine_reason":None,
            "revalidated":"promoted",
            "revalidation_reason":"passed_current_tagger",
            "revalidated_at_epoch":now,
            "family":observed_family,
            "problem_key":problem_key,
            "domain":host,
            "title":title[:300],
            "snippet":body[:300],
            "url":url[:1200],
            "strong_markers":strong[:8],
            "weak_markers":weak[:8],
            "signal_types":signal_types,
            "last_seen_epoch":now,
        },
    }


async def revalidate_quarantined_rows(
    rows: list[dict[str, Any]] | None,
    fetcher: Callable[[str, dict[str, Any]], Awaitable[dict[str, Any]]],
    *,
    limit: int = 3,
    max_fetch_attempts: int = 3,
    now_epoch: float | None = None,
    self_contamination_guard: bool = True,
    seller_launch_guard: bool = True,
    vendor_content_guard: bool = True,
    web_buyer_voice_guard: bool = True,
    family_match_guard: bool = True,
    strong_pain_only: bool = True,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Bounded, fault-isolated revalidation of legacy quarantine rows."""
    now=float(now_epoch if now_epoch is not None else time.time())
    out=[dict(row) for row in (rows or []) if isinstance(row,dict)]
    stats={"attempted":0,"promoted":0,"failed":0,"unreachable":0}
    budget=max(0,int(limit or 0))
    if budget<=0:
        return out,stats

    selected=[]
    for idx,row in enumerate(out):
        if len(selected)>=budget:
            break
        if _excluded(row):
            continue
        attempts=max(0,int(row.get("revalidation_attempts") or 0))
        if attempts>=max_fetch_attempts:
            row["revalidated"]="unreachable"
            row["revalidation_reason"]="fetch_attempt_limit"
            continue
        if not str(row.get("url") or "").strip():
            row["revalidated"]="failed"
            row["revalidation_reason"]="missing_url"
            stats["failed"]+=1
            continue
        selected.append(idx)

    for idx in selected:
        row=out[idx]
        stats["attempted"]+=1
        attempts=max(0,int(row.get("revalidation_attempts") or 0))+1
        row["revalidation_attempts"]=attempts
        row["revalidation_last_attempt_epoch"]=now
        try:
            fetched=await fetcher(str(row.get("url") or ""),dict(row))
            if not isinstance(fetched,dict) or not fetched.get("ok"):
                error=str((fetched or {}).get("error") or "fetch_failed") if isinstance(fetched,dict) else "fetch_failed"
                row["revalidation_last_error"]=error[:300]
                if attempts>=max_fetch_attempts:
                    row["revalidated"]="unreachable"
                    row["revalidation_reason"]="fetch_attempt_limit"
                    stats["unreachable"]+=1
                continue

            verdict=evaluate_fetched_legacy_row(
                row,
                fetched,
                now_epoch=now,
                self_contamination_guard=self_contamination_guard,
                seller_launch_guard=seller_launch_guard,
                vendor_content_guard=vendor_content_guard,
                web_buyer_voice_guard=web_buyer_voice_guard,
                family_match_guard=family_match_guard,
                strong_pain_only=strong_pain_only,
            )
            updates=verdict.get("updates") if isinstance(verdict.get("updates"),dict) else {}
            row.update(updates)
            row.pop("revalidation_last_error",None)
            if verdict.get("ok"):
                row["revalidated"]="promoted"
                stats["promoted"]+=1
            else:
                row["gate_eligible"]=False
                row["revalidated"]="failed"
                row["revalidation_reason"]=str(verdict.get("reason") or "failed")
                row["revalidated_at_epoch"]=now
                stats["failed"]+=1
        except Exception as exc:
            row["revalidation_last_error"]=(type(exc).__name__+": "+str(exc))[:300]
            if attempts>=max_fetch_attempts:
                row["revalidated"]="unreachable"
                row["revalidation_reason"]="fetch_attempt_limit"
                stats["unreachable"]+=1

    return out,stats
