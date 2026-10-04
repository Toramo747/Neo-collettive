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

PAIN_PLUS_BUYER_FRAMES = (
    '("we manually" OR "I spend hours" OR "we are struggling" OR "looking for help")',
    '("need help" OR "need a tool" OR "any recommendations" OR "what do you use")',
    '("we manually" OR "this takes hours" OR "looking for a tool" OR "need help")',
    '("looking for help" OR "need a tool" OR "request for proposal" OR "any recommendations")',
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
    """Prefer observed buyer language; fall back to the Arena-proven pain+buyer pattern."""
    phrases=observed_buyer_phrases(evidence_rows,family,4)
    terms=[_clean(x,100) for x in (sector_terms or []) if _clean(x,100)]
    anchor=terms[0] if terms else str(family or "").replace("_"," ")
    if phrases:
        return _clean(f"{anchor} {phrases[0]}",220)
    frame=PAIN_PLUS_BUYER_FRAMES[0 if query_class=="explore" else 3]
    community='(site:reddit.com OR site:stackoverflow.com OR site:news.ycombinator.com)'
    return _clean(f"{anchor} {frame} {community}",260)


def scout_queries(evidence_rows: Iterable[dict] | None, limit: int = 7) -> list[str]:
    """Build scout queries from observed buyer phrases, then narrow buyer-context fallbacks."""
    phrases=observed_buyer_phrases(evidence_rows,"",max(limit*2,8))
    if phrases:
        return phrases[:max(1,limit)]
    community='(site:reddit.com OR site:stackoverflow.com OR site:news.ycombinator.com)'
    fallbacks=[
        f'manual data entry {PAIN_PLUS_BUYER_FRAMES[0]} {community}',
        f'API integration {PAIN_PLUS_BUYER_FRAMES[1]} {community}',
        f'spreadsheet automation {PAIN_PLUS_BUYER_FRAMES[2]} {community}',
        f'reporting dashboard {PAIN_PLUS_BUYER_FRAMES[3]} {community}',
        f'customer support {PAIN_PLUS_BUYER_FRAMES[0]} {community}',
        f'document processing {PAIN_PLUS_BUYER_FRAMES[1]} {community}',
        f'CRM lead qualification {PAIN_PLUS_BUYER_FRAMES[2]} {community}',
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
    "solution_search","automation_howto","tool_recommendation","paid_automation",
)

DESIRE_SOURCE_ROUTES = (
    ("hn",),
    ("stackexchange",),
    ("hn",),
    ("web",),
)


def desire_experiment_entries(base_entries: list[dict] | None, limit: int = 2) -> list[dict]:
    """Build exactly bounded desire probes from already-selected family slots."""
    limit=max(0,min(int(limit or 0),4))
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
    while len(candidates)<limit:
        candidates.append(candidates[-1])
    out=[]
    for idx,(family,row) in enumerate(candidates[:limit]):
        anchor=family.replace("_"," ")
        intent_class=DESIRE_EXPERIMENT_INTENT_CLASSES[idx % len(DESIRE_EXPERIMENT_INTENT_CLASSES)]
        source_route=list(DESIRE_SOURCE_ROUTES[idx % len(DESIRE_SOURCE_ROUTES)])
        if intent_class=="solution_search":
            query=f'"{anchor}" ("is there a tool" OR "I am looking for a tool" OR "we need a tool")'
        elif intent_class=="automation_howto":
            query=f'"{anchor}" ("how do I automate" OR "how can we automate" OR "we have to do this manually")'
        elif intent_class=="tool_recommendation":
            query=f'"{anchor}" ("what do you use" OR "any recommendations" OR "what tool should I use")'
        else:
            query=f'"{anchor}" ("we spend hours" OR "need to hire" OR "budget for automation") (site:reddit.com OR site:news.ycombinator.com)'
        out.append({
            "query":_clean(query,260),
            "class":"desire",
            "role":"buyer",
            "query_intent":"desire",
            "intent_class":intent_class,
            "family":family,
            "sector":row.get("sector"),
            "search_alias_used":anchor,
            "source_route":source_route,
        })
    return out
