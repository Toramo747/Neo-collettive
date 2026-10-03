# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Andrea Gava
"""MYCELIX Collective Mind Arena.

Discovers task-verified external A2A agents and assigns bounded research/analysis
micro-tasks in parallel. External agents are untrusted collaborators: they never
receive secrets, cannot execute tools on behalf of MYCELIX, cannot mutate
production, and their output is accepted only as structured proposals for later
verification.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

NAMESPACE="mycelix-arena"
ARENA_ID="collective-mind"
A2A_REGISTRY="https://a2aregistry.org"
MAX_AGENTS=6
MAX_CANDIDATE_POOL=30
MAX_EVIDENCE_URLS=4
MAX_FIELD_CHARS=700
ROUND_TIMEOUT=15.0
DEFAULT_MISSION=(
    "Find falsifiable improvements to MYCELIX commercial-signal discovery, "
    "research quality, and external-agent collaboration without weakening any production gate."
)

BOUNDARY={
    "namespace":NAMESPACE,
    "arena_id":ARENA_ID,
    "production_state_write":False,
    "commercial_gate_influence":"NONE",
    "qualified_hits_influence":"NONE",
    "commercial_evidence_influence":"NONE",
    "search_provider_budget_influence":"NONE",
    "secret_access":False,
    "external_tool_execution":False,
    "external_side_effects":False,
    "production_promotion":False,
    "external_agent_contact":True,
    "external_agent_scope":"task_verified_a2a_registry_only",
    "external_output_trust":"UNTRUSTED_STRUCTURED_PROPOSALS_ONLY",
}

SYSTEM_CONTEXT=(
    "MYCELIX currently discovers commercial signals from public sources. "
    "The production gate is fixed and must not be weakened: the same concrete problem needs "
    "at least 3 independent domains within 21 days, at least 2 fresh observations within 7 days, "
    "at least 1 strong source, and PAID_DEMAND plus BUY_INTENT or PAIN. "
    "Existing guards reject vendor content, supply offers, query echo, weak observed-family matches, "
    "missing buyer voice, and self-contamination. Current research strategy uses workaround-oriented "
    "queries with 4 formulations and a 42-day discovery window. "
    "Your job is to improve discovery, validation, orchestration, or computational efficiency while "
    "preserving those boundaries."
)

PACKET_MARKERS={
    "signal_discovery":("research","search","market","business","evidence","sales","signal"),
    "query_design":("search","query","research","analysis","data","retrieval"),
    "adversarial_review":("audit","verify","verification","source","check","review","security","measurement"),
    "market_validation":("market","business","commerce","sales","pricing","evidence","measurement"),
    "agent_orchestration":("agent","multi-agent","orchestration","workflow","coordination","routing"),
    "systems_efficiency":("engineering","optimization","systems","compute","data","performance","infrastructure"),
}

WORK_PACKETS=(
    ("signal_discovery","Find better public signals of concrete buyer pain and existing workarounds."),
    ("query_design","Design a bounded search-query strategy that improves recall without weakening relevance guards."),
    ("adversarial_review","Attack likely false positives and identify failure modes in commercial-signal discovery."),
    ("market_validation","Find ways to distinguish real willingness-to-pay from vendor/supply noise."),
    ("agent_orchestration","Improve how multiple external agents can be divided, compared, and cross-checked efficiently."),
    ("systems_efficiency","Suggest compute-efficient orchestration, caching, batching, or parallelism improvements."),
)


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def clean_text(value: Any, limit: int = MAX_FIELD_CHARS) -> str:
    text=" ".join(str(value or "").split())
    return text[:limit]


def safe_https_url(value: Any) -> str | None:
    text=clean_text(value,500)
    try:
        parsed=urlparse(text)
    except Exception:
        return None
    if parsed.scheme!="https" or not parsed.hostname:
        return None
    host=parsed.hostname.lower()
    if host in {"localhost","127.0.0.1","0.0.0.0"} or host.endswith(".local"):
        return None
    return text


def recursive_objects(value: Any, depth: int = 0) -> list[dict[str,Any]]:
    if depth>5:
        return []
    out=[]
    if isinstance(value,dict):
        out.append(value)
        for v in list(value.values())[:30]:
            out.extend(recursive_objects(v,depth+1))
    elif isinstance(value,list):
        for v in value[:30]:
            out.extend(recursive_objects(v,depth+1))
    elif isinstance(value,str):
        raw=value.strip()
        if len(raw)>5000:
            raw=raw[:5000]
        try:
            parsed=json.loads(raw)
            out.extend(recursive_objects(parsed,depth+1))
        except Exception:
            m=re.search(r"\{.*\}",raw,re.S)
            if m and len(m.group(0))<=5000:
                try:
                    out.extend(recursive_objects(json.loads(m.group(0)),depth+1))
                except Exception:
                    pass
    return out


def recursive_text(value: Any, depth: int = 0) -> list[str]:
    if depth>5:
        return []
    out=[]
    if isinstance(value,str):
        out.append(value)
    elif isinstance(value,dict):
        for v in list(value.values())[:40]:
            out.extend(recursive_text(v,depth+1))
    elif isinstance(value,list):
        for v in value[:40]:
            out.extend(recursive_text(v,depth+1))
    return out


def _labeled_fields(text: str, labels: tuple[str,...]) -> dict[str,str]:
    clean="\n".join(str(text or "").replace("\r","\n").splitlines())
    found={}
    lowered=clean.lower()
    positions=[]
    for label in labels:
        for marker in (label+":", label+"=", "**"+label+"**:", "**"+label+"** ="):
            idx=lowered.find(marker.lower())
            if idx>=0:
                positions.append((idx,label,len(marker)))
                break
    positions.sort()
    for i,(idx,label,mlen) in enumerate(positions):
        start=idx+mlen
        end=positions[i+1][0] if i+1<len(positions) else len(clean)
        value=clean[start:end].strip(" \n\t-*#")
        if value:
            found[label]=clean_text(value)
    return found


def _urls_from_text(text: str) -> list[str]:
    out=[]
    for raw in re.findall(r"https://[^\s\]\[\)\(<>\"']+",str(text or "")):
        url=safe_https_url(raw.rstrip(".,;:"))
        if url and url not in out:
            out.append(url)
        if len(out)>=MAX_EVIDENCE_URLS:
            break
    return out


UUID_ONLY_RE=re.compile(r"^[0-9a-f]{8}-[0-9a-f-]{27,}$",re.I)


def substantive_text(value: Any, minimum: int = 24) -> bool:
    text=clean_text(value,MAX_FIELD_CHARS)
    low=text.lower().strip(" .-_")
    if len(text)<minimum:
        return False
    if low in {"...", "n/a", "none", "unknown", "no answer", "not available"}:
        return False
    if UUID_ONLY_RE.fullmatch(text):
        return False
    tokens=re.findall(r"[a-z0-9]+",low)
    return len(set(tokens))>=4


def normalize_semantic(value: Any) -> str:
    text=clean_text(value,MAX_FIELD_CHARS).lower()
    text=re.sub(r"[0-9a-f]{8}-[0-9a-f-]{27,}","<id>",text)
    text=re.sub(r"\s+"," ",text)
    return text.strip()


def proposal_substantive(row: dict[str,Any] | None) -> bool:
    if not isinstance(row,dict):
        return False
    parts=[row.get("proposal"),row.get("method"),row.get("falsifier")]
    if not all(substantive_text(x) for x in parts):
        return False
    norm=[normalize_semantic(x) for x in parts]
    if len(set(norm))<3:
        return False
    bad=(
        "send me an agent-card url",
        "state the capability needed",
        "no supported mycelix-specific improvement proposal",
        "no substantiated adversarial-review proposal",
        "does not cover mycelix",
        "cannot substantiate an improvement",
        "no search strategy or production-gate changes proposed",
        "\"intent\":\"recommend-product\"",
        "recommendation\":{",
    )
    if any(marker in norm[0] for marker in bad):
        return False
    return True


def critique_substantive(row: dict[str,Any] | None, proposal_count: int) -> bool:
    if not isinstance(row,dict):
        return False
    try:
        idx=int(row.get("best_index"))
    except Exception:
        return False
    return 0<=idx<proposal_count and substantive_text(row.get("weakness")) and substantive_text(row.get("test"))


def parse_proposal(payload: Any) -> dict[str,Any] | None:
    for obj in recursive_objects(payload):
        proposal=clean_text(obj.get("proposal") or obj.get("hypothesis") or obj.get("answer") or "")
        method=clean_text(obj.get("method") or obj.get("test") or obj.get("approach") or "")
        falsifier=clean_text(obj.get("falsifier") or obj.get("failure_condition") or obj.get("disproof") or "")
        if not proposal or not method or not falsifier:
            continue
        urls=[]
        for raw in obj.get("evidence_urls") or obj.get("sources") or []:
            url=safe_https_url(raw)
            if url and url not in urls:
                urls.append(url)
            if len(urls)>=MAX_EVIDENCE_URLS:
                break
        try:
            confidence=max(0.0,min(1.0,float(obj.get("confidence") or 0.0)))
        except Exception:
            confidence=0.0
        try:
            gain=max(0.0,min(100.0,float(obj.get("estimated_gain_pct") or obj.get("gain_pct") or 0.0)))
        except Exception:
            gain=0.0
        return {
            "proposal":proposal,
            "method":method,
            "falsifier":falsifier,
            "evidence_urls":urls,
            "confidence":round(confidence,3),
            "estimated_gain_pct":round(gain,2),
        }
    for raw in recursive_text(payload):
        fields=_labeled_fields(raw,("proposal","method","falsifier","confidence","estimated_gain_pct"))
        proposal=clean_text(fields.get("proposal") or "")
        method=clean_text(fields.get("method") or "")
        falsifier=clean_text(fields.get("falsifier") or "")
        if not proposal or not method or not falsifier:
            continue
        try:
            confidence=max(0.0,min(1.0,float(re.findall(r"[0-9.]+",fields.get("confidence") or "0")[0])))
        except Exception:
            confidence=0.0
        try:
            gain=max(0.0,min(100.0,float(re.findall(r"[0-9.]+",fields.get("estimated_gain_pct") or "0")[0])))
        except Exception:
            gain=0.0
        return {
            "proposal":proposal,
            "method":method,
            "falsifier":falsifier,
            "evidence_urls":_urls_from_text(raw),
            "confidence":round(confidence,3),
            "estimated_gain_pct":round(gain,2),
        }
    return None


def parse_critique(payload: Any) -> dict[str,Any] | None:
    for obj in recursive_objects(payload):
        try:
            best_index=int(obj.get("best_index") if obj.get("best_index") is not None else obj.get("choice"))
        except Exception:
            continue
        weakness=clean_text(obj.get("weakness") or obj.get("risk") or "")
        test=clean_text(obj.get("test") or obj.get("verification") or obj.get("check") or "")
        if best_index<0 or not weakness or not test:
            continue
        return {"best_index":best_index,"weakness":weakness,"test":test}
    for raw in recursive_text(payload):
        fields=_labeled_fields(raw,("best_index","weakness","test"))
        try:
            best_index=int(re.findall(r"\d+",fields.get("best_index") or "")[0])
        except Exception:
            continue
        weakness=clean_text(fields.get("weakness") or "")
        test=clean_text(fields.get("test") or "")
        if best_index>=0 and weakness and test:
            return {"best_index":best_index,"weakness":weakness,"test":test}
    return None


def parse_handshake(payload: Any) -> bool:
    for obj in recursive_objects(payload):
        if obj.get("ready") is True or obj.get("ok") is True or obj.get("can_collaborate") is True:
            return True
        fmt=clean_text(obj.get("format") or obj.get("response_format") or "").lower()
        if fmt in {"json","structured","labels","labeled"}:
            return True
    for raw in recursive_text(payload):
        low=raw.lower()
        if "collab_ok" in low or "ready: true" in low or '"ready": true' in low:
            return True
    return False


def handshake_prompt() -> str:
    return (
        "MYCELIX capability handshake. Analysis only. "
        "Reply with JSON {\"ready\":true,\"format\":\"json\"} if you can answer bounded research tasks "
        "with structured text. Do not execute anything."
    )


def packet_score(agent: dict[str,Any], packet_code: str, ready_ids: set[str] | None = None) -> int:
    text=" ".join([
        str(agent.get("name") or ""),
        str(agent.get("description") or ""),
        json.dumps(agent.get("skills") or [],ensure_ascii=False),
    ]).lower()
    score=candidate_score(agent)
    for marker in PACKET_MARKERS.get(packet_code,()):
        if marker in text:
            score+=5
    aid=str(agent.get("id") or agent.get("agent_id") or "")
    if ready_ids and aid in ready_ids:
        score+=8
    return score


def assign_agents_to_packets(
    agents: list[dict[str,Any]],
    ready_ids: set[str] | None = None,
    limit: int = MAX_AGENTS,
) -> list[tuple[dict[str,Any],tuple[str,str]]]:
    pool=list(agents)
    assignments=[]
    for packet in WORK_PACKETS:
        if not pool or len(assignments)>=max(1,min(limit,MAX_AGENTS)):
            break
        chosen=max(pool,key=lambda a:packet_score(a,packet[0],ready_ids))
        assignments.append((chosen,packet))
        pool.remove(chosen)
    return assignments


def candidate_score(agent: dict[str,Any]) -> int:
    text=" ".join([
        str(agent.get("name") or ""),
        str(agent.get("description") or ""),
        json.dumps(agent.get("skills") or [],ensure_ascii=False),
    ]).lower()
    score=sum(3 for word in (
        "research","analysis","market","business","evidence","search",
        "optimization","data","engineering","reasoning","strategy"
    ) if word in text)
    task=agent.get("task_conformance") or {}
    if isinstance(task,dict) and task.get("category")=="WORKING":
        score+=10
    if agent.get("task_verified") is True:
        score+=8
    if agent.get("is_healthy") is True:
        score+=3
    return score


async def discover_agents(client: httpx.AsyncClient, limit: int = MAX_AGENTS) -> tuple[list[dict[str,Any]],dict[str,Any]]:
    response=await client.get(A2A_REGISTRY+"/api/agents",params={"task_verified":"true","limit":MAX_CANDIDATE_POOL})
    response.raise_for_status()
    payload=response.json()
    rows=payload.get("agents") if isinstance(payload,dict) else payload
    agents=[x for x in (rows or []) if isinstance(x,dict)]
    agents=[x for x in agents if candidate_score(x)>0]
    agents.sort(key=candidate_score,reverse=True)
    agents=agents[:MAX_CANDIDATE_POOL]
    probes=[]
    meta=[]
    for agent in agents:
        aid=str(agent.get("id") or agent.get("agent_id") or "").strip()
        if not aid:
            continue
        probes.append(asyncio.create_task(send_chat(client,aid,handshake_prompt())))
        meta.append(agent)
    results=await asyncio.gather(*probes,return_exceptions=True) if probes else []
    ready=[]
    handshake_rows=[]
    for agent,result in zip(meta,results):
        aid=str(agent.get("id") or agent.get("agent_id") or "")
        name=str(agent.get("name") or aid)[:120]
        ok=False
        status=0
        if not isinstance(result,Exception):
            status,payload=result
            ok=bool(200<=status<300 and parse_handshake(payload))
        handshake_rows.append({"agent_id":aid[:160],"agent":name,"ready":ok,"http_status":status})
        if ok:
            ready.append(agent)
    ready_ids={str(x.get("id") or x.get("agent_id") or "") for x in ready}
    assignments=assign_agents_to_packets(agents,ready_ids,limit)
    selected=[agent for agent,_ in assignments]
    return selected,{
        "candidates_considered":len(agents),
        "handshakes_valid":len(ready),
        "selected_ready":sum(1 for x in selected if x in ready),
        "rows":handshake_rows,
    }


async def send_chat(client: httpx.AsyncClient, agent_id: str, message: str) -> tuple[int,Any]:
    response=await client.post(
        f"{A2A_REGISTRY}/api/agents/{agent_id}/chat",
        json={"message":message},
        timeout=ROUND_TIMEOUT,
    )
    try:
        payload=response.json()
    except Exception:
        payload={"text":response.text[:5000]}
    return response.status_code,payload


def proposal_prompt(mission: str, packet_code: str, packet_text: str) -> str:
    return (
        "You are an untrusted external collaborator in the isolated MYCELIX Collective Mind Arena. "
        "Do analysis only. Do not execute tools, contact third parties, request secrets, credentials, money, "
        "production access, code execution, or state changes. "
        "Return JSON only with: proposal, method, falsifier, evidence_urls (0-4 public HTTPS URLs), "
        "confidence (0-1), estimated_gain_pct (0-100). "
        f"SYSTEM CONTEXT: {SYSTEM_CONTEXT} "
        f"MISSION: {clean_text(mission,1200)} "
        f"YOUR WORK PACKET [{packet_code}]: {packet_text}"
    )


def compatibility_proposal_prompt(mission: str, packet_code: str, packet_text: str) -> str:
    return (
        "MYCELIX bounded collaboration retry. Analysis only; no external actions. "
        "If JSON is inconvenient, reply using exactly these labels on separate lines: "
        "PROPOSAL: ... METHOD: ... FALSIFIER: ... CONFIDENCE: 0-1 ESTIMATED_GAIN_PCT: 0-100. "
        "Public HTTPS evidence links may follow. "
        f"SYSTEM CONTEXT: {SYSTEM_CONTEXT} "
        f"MISSION: {clean_text(mission,900)} TASK [{packet_code}]: {packet_text}"
    )


def extract_answer_text(payload: Any) -> str:
    candidates=[]
    for raw in recursive_text(payload):
        text=clean_text(raw,MAX_FIELD_CHARS)
        if len(text)<8:
            continue
        low=text.lower()
        if low in {"true","false","ok","ready","json"}:
            continue
        candidates.append(text)
    if not candidates:
        return ""
    candidates.sort(key=len,reverse=True)
    return candidates[0]


async def proposal_field_fallback(
    client: httpx.AsyncClient,
    agent_id: str,
    mission: str,
    packet_code: str,
    packet_text: str,
) -> dict[str,Any] | None:
    base=(
        "MYCELIX bounded collaboration. Analysis only; no external actions. "
        f"SYSTEM CONTEXT: {SYSTEM_CONTEXT} "
        f"MISSION: {clean_text(mission,700)} TASK [{packet_code}]: {packet_text} "
    )
    questions=(
        base+"State ONE concrete proposal only.",
        base+"State the method to test or validate the proposal only.",
        base+"State what observation would falsify or disprove the proposal only.",
    )
    results=await asyncio.gather(
        *(send_chat(client,agent_id,q) for q in questions),
        return_exceptions=True,
    )
    answers=[]
    for result in results:
        if isinstance(result,Exception):
            return None
        status,payload=result
        if not (200<=status<300):
            return None
        answer=extract_answer_text(payload)
        if not answer:
            return None
        answers.append(answer)
    return {
        "proposal":answers[0],
        "method":answers[1],
        "falsifier":answers[2],
        "evidence_urls":[],
        "confidence":0.0,
        "estimated_gain_pct":0.0,
    }


async def critique_field_fallback(
    client: httpx.AsyncClient,
    agent_id: str,
    proposals: list[dict[str,Any]],
) -> dict[str,Any] | None:
    compact=[{"index":i,"proposal":p["proposal"][:240]} for i,p in enumerate(proposals)]
    context="PROPOSALS="+json.dumps(compact,ensure_ascii=False,separators=(",",":"))
    questions=(
        "MYCELIX bounded review. Analysis only. Which proposal index is strongest? Reply with the integer only. "+context,
        "MYCELIX bounded review. Analysis only. State the main weakness of the strongest proposal only. "+context,
        "MYCELIX bounded review. Analysis only. State one concrete verification test only. "+context,
    )
    results=await asyncio.gather(
        *(send_chat(client,agent_id,q) for q in questions),
        return_exceptions=True,
    )
    if len(results)!=3:
        return None
    parsed=[]
    for result in results:
        if isinstance(result,Exception):
            return None
        status,payload=result
        if not (200<=status<300):
            return None
        parsed.append(extract_answer_text(payload))
    m=re.search(r"\b(\d+)\b",parsed[0] or "")
    if not m:
        return None
    idx=int(m.group(1))
    if idx<0 or idx>=len(proposals) or not parsed[1] or not parsed[2]:
        return None
    return {"best_index":idx,"weakness":parsed[1],"test":parsed[2]}


def compatibility_critique_prompt(proposals: list[dict[str,Any]]) -> str:
    compact=[{"index":i,"proposal":p["proposal"][:280]} for i,p in enumerate(proposals)]
    return (
        "MYCELIX bounded review retry. Reply JSON or three labeled lines: "
        "BEST_INDEX: integer WEAKNESS: ... TEST: ... "
        "Do not execute anything. PROPOSALS="+json.dumps(compact,ensure_ascii=False,separators=(",",":"))
    )


def critique_prompt(proposals: list[dict[str,Any]]) -> str:
    compact=[
        {
            "index":i,
            "proposal":p["proposal"][:350],
            "method":p["method"][:350],
            "falsifier":p["falsifier"][:250],
            "evidence_count":len(p.get("evidence_urls") or []),
        }
        for i,p in enumerate(proposals)
    ]
    return (
        "You are an untrusted reviewer in the isolated MYCELIX Collective Mind Arena. "
        "Review these anonymized proposals. Do not execute anything or request access. "
        "Return JSON only: best_index (integer), weakness (short string), test (short verification test). "
        "Prefer falsifiable proposals with independent public evidence and low operational risk. "
        "PROPOSALS="+json.dumps(compact,ensure_ascii=False,separators=(",",":"))
    )


def proposal_score(proposal: dict[str,Any], support_votes: int) -> float:
    evidence=min(len(proposal.get("evidence_urls") or []),MAX_EVIDENCE_URLS)/MAX_EVIDENCE_URLS
    confidence=float(proposal.get("confidence") or 0.0)
    gain=float(proposal.get("estimated_gain_pct") or 0.0)/100.0
    support=min(max(0,support_votes),MAX_AGENTS)/MAX_AGENTS
    return round(35*evidence+25*confidence+20*gain+20*support,3)


async def run(mission: str, data_dir: Path, max_agents: int = MAX_AGENTS) -> dict[str,Any]:
    async with httpx.AsyncClient(
        timeout=ROUND_TIMEOUT,
        follow_redirects=False,
        trust_env=False,
        headers={"User-Agent":"MYCELIX-Collective-Mind/1.0"},
    ) as client:
        try:
            agents,handshake=await discover_agents(client,max_agents)
        except Exception as exc:
            agents=[]
            handshake={"candidates_considered":0,"handshakes_valid":0,"selected_ready":0,"rows":[]}
            discovery_error=type(exc).__name__
        else:
            discovery_error=""

        tasks=[]
        task_meta=[]
        ready_ids={
            str(x.get("agent_id") or "")
            for x in (handshake.get("rows") or [])
            if isinstance(x,dict) and x.get("ready")
        }
        assigned=assign_agents_to_packets(agents,ready_ids,max_agents)
        for agent,packet in assigned:
            aid=str(agent.get("id") or agent.get("agent_id") or "").strip()
            if not aid:
                continue
            tasks.append(asyncio.create_task(send_chat(client,aid,proposal_prompt(mission,*packet))))
            task_meta.append((aid,str(agent.get("name") or aid)[:120],packet[0]))

        raw_results=await asyncio.gather(*tasks,return_exceptions=True) if tasks else []
        proposals=[]
        contacts=[]
        for meta,result in zip(task_meta,raw_results):
            aid,name,packet=meta
            if isinstance(result,Exception):
                contacts.append({"agent_id":aid[:160],"agent":name,"packet":packet,"accepted":False,"reason":type(result).__name__})
                continue
            status,payload=result
            parsed=parse_proposal(payload) if 200<=status<300 else None
            if parsed and not proposal_substantive(parsed):
                parsed=None
            retry_used=False
            if not parsed and 200<=status<300:
                retry_used=True
                packet_text=next((x[1] for x in WORK_PACKETS if x[0]==packet),"")
                try:
                    retry_status,retry_payload=await send_chat(
                        client,aid,compatibility_proposal_prompt(mission,packet,packet_text)
                    )
                    if 200<=retry_status<300:
                        parsed=parse_proposal(retry_payload)
                        if parsed and not proposal_substantive(parsed):
                            parsed=None
                except Exception:
                    pass
                if not parsed:
                    try:
                        parsed=await proposal_field_fallback(client,aid,mission,packet,packet_text)
                        if parsed and not proposal_substantive(parsed):
                            parsed=None
                    except Exception:
                        parsed=None
            contacts.append({
                "agent_id":aid[:160],"agent":name,"packet":packet,
                "accepted":bool(parsed),
                "retry_used":retry_used,
                "reason":"structured_proposal_accepted" if parsed else f"no_valid_proposal_http_{status}",
            })
            if parsed:
                parsed["agent_id"]=aid[:160]
                parsed["agent"]=name
                parsed["packet"]=packet
                proposals.append(parsed)

        critiques=[]
        if proposals:
            prompt=critique_prompt(proposals)
            review_tasks=[]
            review_meta=[]
            for aid,name,_ in task_meta:
                review_tasks.append(asyncio.create_task(send_chat(client,aid,prompt)))
                review_meta.append((aid,name))
            review_results=await asyncio.gather(*review_tasks,return_exceptions=True)
            for (aid,name),result in zip(review_meta,review_results):
                if isinstance(result,Exception):
                    critiques.append({"agent_id":aid[:160],"agent":name,"accepted":False,"reason":type(result).__name__})
                    continue
                status,payload=result
                parsed=parse_critique(payload) if 200<=status<300 else None
                if parsed and not critique_substantive(parsed,len(proposals)):
                    parsed=None
                retry_used=False
                if not parsed and 200<=status<300:
                    retry_used=True
                    try:
                        retry_status,retry_payload=await send_chat(
                            client,aid,compatibility_critique_prompt(proposals)
                        )
                        if 200<=retry_status<300:
                            parsed=parse_critique(retry_payload)
                            if parsed and not critique_substantive(parsed,len(proposals)):
                                parsed=None
                    except Exception:
                        pass
                    if not parsed:
                        try:
                            parsed=await critique_field_fallback(client,aid,proposals)
                            if parsed and not critique_substantive(parsed,len(proposals)):
                                parsed=None
                        except Exception:
                            parsed=None
                critiques.append({
                    "agent_id":aid[:160],"agent":name,"accepted":bool(parsed),
                    "retry_used":retry_used,
                    "reason":"critique_accepted" if parsed else f"no_valid_critique_http_{status}",
                    "critique":parsed,
                })

    support=[0 for _ in proposals]
    for row in critiques:
        crit=row.get("critique")
        if isinstance(crit,dict):
            idx=int(crit.get("best_index") or 0)
            if 0<=idx<len(support):
                support[idx]+=1

    ranked=[]
    for idx,p in enumerate(proposals):
        item=dict(p)
        item["support_votes"]=support[idx]
        item["score"]=proposal_score(item,support[idx])
        item["proposal_id"]=hashlib.sha256(
            (item["proposal"]+"|"+item["method"]+"|"+item["falsifier"]).encode()
        ).hexdigest()[:16]
        ranked.append(item)
    ranked.sort(key=lambda x:x["score"],reverse=True)

    report={
        "schema_v":1,
        "namespace":NAMESPACE,
        "arena_id":ARENA_ID,
        "captured_at_utc":now_utc(),
        "mission":clean_text(mission,1200),
        "status":"COMPLETED" if agents else "NO_AGENTS",
        "discovery_error":discovery_error,
        "agents_discovered":len(agents),
        "agents_contacted":len(task_meta),
        "handshake":handshake,
        "round1_valid_proposals":len(proposals),
        "round2_valid_critiques":sum(1 for x in critiques if x.get("accepted")),
        "contacts":contacts,
        "ranked_proposals":[
            {
                "proposal_id":x["proposal_id"],
                "agent":x["agent"],
                "packet":x["packet"],
                "proposal":x["proposal"],
                "method":x["method"],
                "falsifier":x["falsifier"],
                "evidence_urls":x["evidence_urls"],
                "confidence":x["confidence"],
                "estimated_gain_pct":x["estimated_gain_pct"],
                "support_votes":x["support_votes"],
                "score":x["score"],
            }
            for x in ranked
        ],
        "critique_metrics":{
            "accepted":sum(1 for x in critiques if x.get("accepted")),
            "rejected":sum(1 for x in critiques if not x.get("accepted")),
        },
        "boundary":dict(BOUNDARY),
        "production_promoted":False,
    }
    root=data_dir/"collective-mind"
    root.mkdir(parents=True,exist_ok=True)
    (root/"latest.json").write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    return report


def main() -> int:
    parser=argparse.ArgumentParser()
    parser.add_argument("--mission",default=DEFAULT_MISSION)
    parser.add_argument("--data-dir",default="data/arena")
    parser.add_argument("--max-agents",type=int,default=MAX_AGENTS)
    args=parser.parse_args()
    report=asyncio.run(run(args.mission,Path(args.data_dir),args.max_agents))
    print(json.dumps({
        "ok":True,
        "status":report["status"],
        "agents_contacted":report["agents_contacted"],
        "round1_valid_proposals":report["round1_valid_proposals"],
        "round2_valid_critiques":report["round2_valid_critiques"],
        "top_proposal_id":(report["ranked_proposals"][0]["proposal_id"] if report["ranked_proposals"] else None),
        "boundary":report["boundary"],
    },ensure_ascii=False))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
