"""Buyer-language query construction for MYCELIX.

Pure helpers only: no network, no gate/tagger mutations.
"""
from __future__ import annotations

import re
from typing import Iterable

BUYER_SIGNAL_TERMS = (
    "need help","looking for","hiring","hire","contractor","freelance","freelancer",
    "fixed price","fixed-price","hourly","budget","manual","repetitive","workaround",
    "time consuming","time-consuming","struggle","problem","pain",
)


def _clean(value: str, limit: int = 180) -> str:
    return " ".join(str(value or "").replace("\n"," ").split())[:limit].strip()


def _phrase_candidates(text: str) -> list[str]:
    text=_clean(text,600)
    if not text:
        return []
    parts=re.split(r"(?<=[.!?])\s+|\s+[|•—–]\s+",text)
    out=[]
    for part in parts:
        phrase=_clean(part,180)
        low=phrase.lower()
        words=phrase.split()
        if 5 <= len(words) <= 24 and any(term in low for term in BUYER_SIGNAL_TERMS):
            out.append(phrase)
    return out


def observed_buyer_phrases(rows: Iterable[dict] | None, family: str = "", limit: int = 8) -> list[str]:
    """Use only current, non-quarantined evidence with buyer/pain tags."""
    wanted=str(family or "").strip()
    scored=[]
    seen=set()
    for row in rows or []:
        if not isinstance(row,dict):
            continue
        if int(row.get("tagger_v") or 0) < 3:
            continue
        if row.get("quarantine_reason"):
            continue
        if wanted and str(row.get("family") or "") != wanted:
            continue
        tags=set(row.get("signal_types") or [])
        if not tags.intersection({"PAIN","BUY_INTENT","PAID_DEMAND"}):
            continue
        for text in (row.get("title"),row.get("snippet")):
            for phrase in _phrase_candidates(str(text or "")):
                key=phrase.lower()
                if key in seen:
                    continue
                seen.add(key)
                score=(
                    3*("PAID_DEMAND" in tags)
                    + 2*("BUY_INTENT" in tags)
                    + 1*("PAIN" in tags)
                    + min(2,int(row.get("seen_count") or 1))
                )
                scored.append((score,phrase))
    scored.sort(key=lambda item:(-item[0],item[1].lower()))
    return [phrase for _,phrase in scored[:max(0,limit)]]


def discovery_query(
    family: str,
    sector_terms: list[str] | tuple[str,...],
    query_class: str,
    evidence_rows: Iterable[dict] | None,
) -> str:
    """Prefer observed buyer language; use a deterministic family-specific fallback."""
    phrases=observed_buyer_phrases(evidence_rows,family,4)
    terms=[_clean(x,100) for x in (sector_terms or []) if _clean(x,100)]
    anchor=terms[0] if terms else str(family or "").replace("_"," ")
    if phrases:
        return _clean(f"{anchor} {phrases[0]}",220)
    if query_class=="explore":
        suffix='("I need" OR "we are struggling" OR "looking for help") (site:reddit.com OR site:stackoverflow.com OR site:news.ycombinator.com)'
    else:
        suffix='("looking for help" OR hiring OR contractor OR RFP) (site:reddit.com OR site:stackoverflow.com OR site:news.ycombinator.com)'
    return _clean(f"{anchor} {suffix}",260)


def scout_queries(evidence_rows: Iterable[dict] | None, limit: int = 7) -> list[str]:
    """Build scout queries from observed buyer phrases, then narrow buyer-context fallbacks."""
    phrases=observed_buyer_phrases(evidence_rows,"",max(limit*2,8))
    if phrases:
        return phrases[:max(1,limit)]
    community='(site:reddit.com OR site:stackoverflow.com OR site:news.ycombinator.com)'
    fallbacks=[
        f'manual data entry ("I need" OR "we are struggling" OR "looking for help") {community}',
        f'API integration ("I need" OR "looking for help" OR contractor) {community}',
        f'spreadsheet automation ("our team spends" OR "we manually" OR "how do I") {community}',
        f'reporting dashboard ("I need" OR "we are struggling" OR RFP) {community}',
        f'customer support ("our team spends" OR "we manually" OR "looking for help") {community}',
        f'document processing ("I need" OR "we manually" OR contractor) {community}',
        f'CRM lead qualification ("we manually" OR hiring OR contractor) {community}',
    ]
    return fallbacks[:max(1,limit)]


def breakout_queries(marker: str, evidence_rows: Iterable[dict] | None, family: str = "", limit: int = 2) -> list[str]:
    """Structured-source-friendly breakout queries; no site:reddit.com templates."""
    phrases=observed_buyer_phrases(evidence_rows,family,max(limit,2))
    out=[]
    for phrase in phrases:
        if phrase.lower() not in {x.lower() for x in out}:
            out.append(phrase)
        if len(out)>=limit:
            return out
    marker=_clean(marker,120)
    community='(site:reddit.com OR site:stackoverflow.com OR site:news.ycombinator.com)'
    fallbacks=[
        f'{marker} ("I need" OR "we are struggling" OR "looking for help") {community}',
        f'{marker} (hiring OR contractor OR RFP OR "request for proposal") {community}',
    ]
    for query in fallbacks:
        query=_clean(query,220)
        if query and query.lower() not in {x.lower() for x in out}:
            out.append(query)
        if len(out)>=limit:
            break
    return out


DESIRE_EXPERIMENT_INTENT_CLASSES = (
    "solution_search","paid_automation",
)


def desire_experiment_entries(base_entries: list[dict] | None, limit: int = 2) -> list[dict]:
    """Build exactly bounded desire probes from already-selected family slots."""
    limit=max(0,min(int(limit or 0),2))
    if not limit:
        return []
    candidates=[]
    seen=set()
    for row in reversed(list(base_entries or [])):
        if not isinstance(row,dict):
            continue
        family=str(row.get("family") or "").strip()
        if not family or family in seen:
            continue
        seen.add(family)
        candidates.append((family,row))
        if len(candidates)>=limit:
            break
    if not candidates:
        return []
    candidates=list(reversed(candidates))
    out=[]
    for idx,(family,row) in enumerate(candidates[:limit]):
        anchor=family.replace("_"," ")
        intent_class=DESIRE_EXPERIMENT_INTENT_CLASSES[idx % len(DESIRE_EXPERIMENT_INTENT_CLASSES)]
        if intent_class=="solution_search":
            query=f'"{anchor}" ("is there a tool" OR "looking for software" OR "any recommendations")'
        else:
            query=f'"{anchor}" ("hire someone to automate" OR ("budget" AND automate))'
        out.append({
            "query":_clean(query,260),
            "class":"desire",
            "role":"buyer",
            "query_intent":"desire",
            "intent_class":intent_class,
            "family":family,
            "sector":row.get("sector"),
            "search_alias_used":anchor,
        })
    return out
