import asyncio
import hashlib
import json
import re
from datetime import datetime, timezone
from urllib.parse import urlparse
from typing import Any, Awaitable, Callable

SETI_SCHEMA_VERSION = 2
SETI_ENGINE_VERSION = 5

DEFAULT_PASSIVE_QUERIES = [
    'inurl:"/.well-known/agent-card.json" "message/send" -site:a2aregistry.org',
    '"https://" "/.well-known/agent-card.json" "Agent2Agent" -site:a2aregistry.org',
    '"agent-card.json" "protocolVersion" "skills" -site:a2aregistry.org',
    '"message/send" "jsonrpc" agent -site:a2aregistry.org',
    '"/.well-known/agent-card.json" -site:a2aregistry.org',
    '"agent-card.json" "A2A" -site:a2aregistry.org',
    '"/.well-known/agent.json" agent -site:a2aregistry.org',
    '"contextId" "messageId" agent',
    '"task_id" poll agent completed',
    '"tools/list" initialize MCP -site:modelcontextprotocol.io -site:registry.modelcontextprotocol.io',
    '"MCP server" SSE "tools/call" -site:registry.modelcontextprotocol.io',
    '"Agent2Agent" endpoint "message/send"',
    '"autonomous agent" webhook API',
    '"agentic" "JSON-RPC" endpoint',
]

OFFICIAL_OR_LOW_VALUE_DOMAINS = {
    "a2aregistry.org",
    "registry.modelcontextprotocol.io",
    "modelcontextprotocol.io",
    "wikipedia.org",
    "bing.com",
    "google.com",
    "example.com",
    "example.org",
    "example.net",
}

COMMON_HOSTS = {
    "github.com",
    "gitlab.com",
    "medium.com",
    "dev.to",
    "reddit.com",
    "news.ycombinator.com",
}

SIGNATURES = (
    ("a2a_agent_card", ("agent-card.json", ".well-known/agent.json"), 30),
    ("a2a_protocol", ("agent2agent", "a2a protocol", "agent card"), 12),
    ("a2a_message_send", ("message/send",), 24),
    ("json_rpc", ("jsonrpc", "json-rpc"), 13),
    ("mcp_handshake", ("tools/list", "model context protocol", "mcp server"), 18),
    ("mcp_transport", ("tools/call", "streamable http", "server-sent events", "sse"), 8),
    ("machine_context_ids", ("contextid", "messageid"), 14),
    ("async_task_protocol", ("task_id", "taskid", "poll", "completed"), 10),
    ("tool_invocation", ("tool_call", "tool calls", "tools/call"), 10),
    ("machine_callbacks", ("webhook", "callback"), 6),
    ("declared_agentic", ("autonomous agent", "ai agent", "agentic"), 5),
)

DOC_MARKERS = (
    "tutorial",
    "how to",
    "guide",
    "documentation",
    "docs:",
    "what is",
    "introduction to",
    "course",
    "blog",
)


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def canonical_host(url: str) -> str:
    try:
        host=(urlparse(url).hostname or "").lower().strip(".")
    except Exception:
        return ""
    if host.startswith("www."):
        host=host[4:]
    return host


def _clean_text(value: Any) -> str:
    text=str(value or "")
    text=re.sub(r"<[^>]+>", " ", text)
    text=re.sub(r"\s+", " ", text)
    return text.strip()


EXPLICIT_AGENT_CARD_PATHS = (
    "/.well-known/agent-card.json",
    "/.well-known/agent.json",
)
EXPLICIT_A2A_PATHS = (
    "/a2a",
    "/message/send",
    "/agent/a2a",
    "/agents/a2a",
)


def explicit_agent_endpoint_url(url: str) -> bool:
    try:
        p=urlparse(str(url or "").strip())
        host=(p.hostname or "").lower().strip(".")
        path=(p.path or "/").lower().rstrip("/") or "/"
    except Exception:
        return False
    if p.scheme!="https" or not host:
        return False
    if host in OFFICIAL_OR_LOW_VALUE_DOMAINS or host in COMMON_HOSTS:
        return False
    if host in {"localhost","localhost.localdomain"} or host.endswith(".local"):
        return False
    if any(path.endswith(x) for x in EXPLICIT_AGENT_CARD_PATHS):
        return True
    return any(path==x or path.endswith(x) for x in EXPLICIT_A2A_PATHS)


def indexed_endpoint_leads(row: dict, limit: int = 4) -> list[dict]:
    """Extract explicitly declared public A2A endpoints from indexed text only.

    This does not fetch, resolve or probe the extracted host. It turns a URL that is
    already visible in a public search/code index into a quarantined SETI lead.
    """
    if not isinstance(row,dict):
        return []
    text=" ".join([
        str(row.get("title") or ""),
        str(row.get("snippet") or row.get("description") or ""),
    ])
    urls=re.findall(r'https://[^\s<>"\]\[(){}]+',text,re.I)
    out=[]
    seen=set()
    provenance=str(row.get("url") or "").strip()
    source=str(row.get("source") or "public_index")
    for raw in urls:
        url=raw.rstrip(".,;:!?")
        if url in seen or not explicit_agent_endpoint_url(url):
            continue
        seen.add(url)
        host=canonical_host(url)
        out.append({
            "title":"Indexed public A2A endpoint: "+host,
            "url":url,
            "snippet":_clean_text(text)[:1400],
            "source":source+"-declared-endpoint",
            "source_provenance":[source],
            "provenance_url":provenance,
            "indexed_declared_endpoint":True,
        })
        if len(out)>=max(1,min(limit,8)):
            break
    return out


def _tokens(text: str) -> set[str]:
    stop={
        "the","and","for","with","from","this","that","into","your","using","about",
        "agent","agents","api","http","https","www","com","org","github","server",
    }
    out=set()
    for raw in re.split(r"[^a-zA-Z0-9]+",(text or "").lower()):
        if len(raw)>=4 and raw not in stop:
            out.add(raw)
    return out


def signal_fingerprint(row: dict) -> str:
    url=str(row.get("url") or "").strip()
    if explicit_agent_endpoint_url(url):
        try:
            p=urlparse(url)
            host=(p.hostname or "").lower().strip(".")
            path=re.sub(r"/+","/",p.path or "/").rstrip("/") or "/"
            raw="endpoint|"+host+"|"+path.lower()
        except Exception:
            raw="endpoint|"+url.lower()
    else:
        raw="|".join([
            canonical_host(url),
            url.lower(),
            _clean_text(row.get("title")).lower(),
        ])
    return hashlib.sha256(raw.encode("utf-8","ignore")).hexdigest()[:24]


def _classification(score: int) -> str:
    if score >= 75:
        return "HIGH_INTEREST"
    if score >= 50:
        return "INTERESTING"
    if score >= 30:
        return "WEAK_SIGNAL"
    return "NOISE"


def score_public_result(row: dict) -> dict:
    title=_clean_text(row.get("title"))[:300]
    snippet=_clean_text(row.get("snippet") or row.get("description"))[:1400]
    url=str(row.get("url") or "").strip()
    host=canonical_host(url)
    low=(" "+title+" "+snippet+" "+url+" ").lower()

    score=0
    signals=[]
    for name, markers, weight in SIGNATURES:
        hits=[m for m in markers if m in low]
        if hits:
            # Multi-marker signatures are stronger when more than one marker survives search indexing.
            bonus=min(8,max(0,len(hits)-1)*4)
            score += weight + bonus
            signals.append({"type":name,"markers":hits[:4],"weight":weight+bonus})

    path=(urlparse(url).path or "").lower() if url else ""
    if "/.well-known/" in path:
        score += 16
        signals.append({"type":"well_known_machine_manifest","markers":["/.well-known/"],"weight":16})
    if any(x in path for x in ("/a2a","/mcp","/sse","/rpc","/tasks","/invoke")):
        score += 8
        signals.append({"type":"machine_endpoint_path","markers":[path[:160]],"weight":8})

    if host in OFFICIAL_OR_LOW_VALUE_DOMAINS:
        score -= 100
    if any(marker in low for marker in DOC_MARKERS):
        score -= 9
    if host in COMMON_HOSTS:
        score -= 4

    score=max(0,min(100,score))
    source=str(row.get("source") or "public_search")
    source_provenance=[
        str(x) for x in (row.get("source_provenance") or [source])
        if str(x).strip()
    ][:8]
    source_kind=(
        "code_artifact" if source.startswith("github-")
        else "community_index" if source.startswith(("hn-","stackexchange"))
        else "web_index"
    )
    return {
        "fingerprint":signal_fingerprint({"url":url,"title":title}),
        "title":title,
        "url":url,
        "domain":host,
        "snippet":snippet,
        "agent_likelihood_score":score,
        "classification":_classification(score),
        "signals":signals,
        "source":source,
        "source_provenance":source_provenance,
        "source_kind":source_kind,
        "indexed_declared_endpoint":bool(row.get("indexed_declared_endpoint")),
        "provenance_url":str(row.get("provenance_url") or "")[:1200],
    }


def _registry_items(discovery: dict) -> list[dict]:
    out=[]
    for key in ("a2a_registry","mcp_registry"):
        wrapper=discovery.get(key) or {}
        if not isinstance(wrapper,dict) or not wrapper.get("ok"):
            continue
        data=wrapper.get("data")
        if isinstance(data,list):
            items=data
        elif isinstance(data,dict):
            items=(
                data.get("agents")
                or data.get("servers")
                or data.get("items")
                or data.get("data")
                or []
            )
        else:
            items=[]
        for raw in items:
            if isinstance(raw,dict):
                obj=raw.get("server",raw)
                if isinstance(obj,dict):
                    out.append(obj)
    return out


def registry_probe_term(candidate: dict) -> str:
    url=str(candidate.get("url") or "")
    host=canonical_host(url)
    try:
        p=urlparse(url)
        parts=[x for x in p.path.split("/") if x]
    except Exception:
        parts=[]
    if host=="github.com" and len(parts)>=2:
        return parts[0]+"/"+parts[1]
    if host and host not in COMMON_HOSTS:
        return host
    title_tokens=sorted(_tokens(str(candidate.get("title") or "")),key=lambda x:(-len(x),x))
    return " ".join(title_tokens[:3]) or host or "agent runtime"


def registry_match(candidate: dict, discovery: dict) -> bool:
    items=_registry_items(discovery)
    if not items:
        return False
    host=canonical_host(str(candidate.get("url") or ""))
    probe=registry_probe_term(candidate).lower()
    target_tokens=_tokens(str(candidate.get("title") or "")+" "+probe)
    for item in items:
        text=json.dumps(item,ensure_ascii=False,default=str).lower()
        if probe and len(probe)>=5 and probe in text:
            return True
        if host and host not in COMMON_HOSTS and host in text:
            return True
        overlap=target_tokens & _tokens(text)
        if len(overlap)>=3:
            return True
    return False


async def deep_space_scan(
    search_fn: Callable[[str,int], Awaitable[dict]],
    discover_fn: Callable[[str,int], Awaitable[dict]],
    limit: int = 16,
    per_query: int = 5,
    queries: list[str] | None = None,
    registry_checks: int = 10,
) -> dict:
    """Passive SETI-style discovery.

    Only public search indexes and official registries are queried. Candidate target URLs
    are never fetched, probed, scanned, messaged or executed by this function.
    """
    queries=list(queries or DEFAULT_PASSIVE_QUERIES)[:12]
    batches=await asyncio.gather(
        *(search_fn(q,max(1,min(per_query,8))) for q in queries),
        return_exceptions=True,
    )

    raw_results=[]
    search_errors=[]
    seen_pairs=set()
    source_counts={}
    for q,batch in zip(queries,batches):
        if isinstance(batch,Exception):
            search_errors.append({"query":q,"error":type(batch).__name__+": "+str(batch)[:180]})
            continue
        if not isinstance(batch,dict) or not batch.get("ok"):
            search_errors.append({"query":q,"error":str((batch or {}).get("error") if isinstance(batch,dict) else "invalid_response")[:180]})
            continue
        for row in batch.get("results") or []:
            if not isinstance(row,dict):
                continue
            expanded=[dict(row)]+indexed_endpoint_leads(row,limit=4)
            for copy in expanded:
                url=str(copy.get("url") or "").strip()
                src=str(copy.get("source") or "unknown")
                pair=(url,src)
                if not url or pair in seen_pairs:
                    continue
                seen_pairs.add(pair)
                copy["_query"]=q
                raw_results.append(copy)
                source_counts[src]=source_counts.get(src,0)+1

    scored_raw=[score_public_result(row) for row in raw_results]
    scored_by_fp={}
    for row in scored_raw:
        if row.get("classification")=="NOISE":
            continue
        fp=str(row.get("fingerprint") or "")
        prev=scored_by_fp.get(fp)
        if prev is None:
            scored_by_fp[fp]=dict(row)
            continue
        sources=sorted(set(
            list(prev.get("source_provenance") or [prev.get("source")])
            + list(row.get("source_provenance") or [row.get("source")])
        ))
        best=row if int(row.get("agent_likelihood_score") or 0)>int(prev.get("agent_likelihood_score") or 0) else prev
        merged=dict(best)
        merged["source_provenance"]=[str(x) for x in sources if str(x).strip()][:8]
        merged["source_diversity"]=len(merged["source_provenance"])
        scored_by_fp[fp]=merged
    scored=list(scored_by_fp.values())
    for row in scored:
        row.setdefault("source_diversity",len(row.get("source_provenance") or []))
    scored.sort(key=lambda x:(
        int(x.get("agent_likelihood_score") or 0),
        int(x.get("source_diversity") or 0),
        len(x.get("signals") or []),
    ),reverse=True)

    check_targets=scored[:max(1,min(registry_checks,20))]

    async def check(candidate: dict) -> tuple[dict,dict|None,Exception|None]:
        term=registry_probe_term(candidate)
        try:
            data=await discover_fn(term,6)
            return candidate,data,None
        except Exception as e:
            return candidate,None,e

    checks=await asyncio.gather(*(check(x) for x in check_targets)) if check_targets else []
    checked_by_fp={}
    registry_errors=[]
    known_space_filtered=0
    for candidate,data,error in checks:
        fp=str(candidate.get("fingerprint") or "")
        if error is not None:
            checked_by_fp[fp]="registry_check_error"
            registry_errors.append({"fingerprint":fp,"error":type(error).__name__+": "+str(error)[:180]})
            continue
        if isinstance(data,dict) and registry_match(candidate,data):
            checked_by_fp[fp]="registry_match"
            known_space_filtered += 1
        else:
            checked_by_fp[fp]="not_found_in_checked_registries"

    signals=[]
    for candidate in scored:
        fp=str(candidate.get("fingerprint") or "")
        novelty=checked_by_fp.get(fp,"not_checked")
        if novelty=="registry_match":
            continue
        candidate=dict(candidate)
        candidate["registry_status"]=novelty
        candidate["passive_only"]=True
        candidate["target_contacted"]=False
        candidate["external_agents_consulted"]=False
        signals.append(candidate)
        if len(signals)>=max(1,min(limit,40)):
            break

    return {
        "ok":True,
        "schema_v":SETI_SCHEMA_VERSION,
        "mode":"passive",
        "scanned_at_utc":_utcnow(),
        "queries":queries,
        "search_results_seen":len(raw_results),
        "source_counts":source_counts,
        "machine_like_results":len(scored),
        "registry_checks":len(checks),
        "known_space_filtered":known_space_filtered,
        "signals":signals,
        "search_errors":search_errors[:8],
        "registry_errors":registry_errors[:8],
        "safety":{
            "target_http_requests":False,
            "active_probe":False,
            "messages_sent":False,
            "port_scan":False,
            "registry_and_public_index_only":True,
        },
    }


def private_candidate_key(row: dict) -> str:
    """Stable private correlation key based on the public target URL, not the title."""
    url=str(row.get("url") or "").strip()
    try:
        p=urlparse(url)
        host=(p.hostname or "").lower().strip(".")
        if host.startswith("www."):
            host=host[4:]
        path=re.sub(r"/+","/",p.path or "/").rstrip("/") or "/"
        raw=host+"|"+path.lower()
    except Exception:
        raw=url.lower()
    if not raw.strip("|/"):
        raw=str(row.get("fingerprint") or row.get("title") or "unknown")
    return hashlib.sha256(raw.encode("utf-8","ignore")).hexdigest()[:24]


def merge_private_candidate_state(
    private_state: dict,
    enriched: list[dict],
    max_entries: int = 16,
) -> tuple[dict, dict]:
    """Keep detailed SETI candidates for internal correlation only.

    Caller decides where this state is stored. This function intentionally keeps
    URLs/titles/snippets because the public AUTOPILOT state stores fingerprints only.
    """
    state=dict(private_state) if isinstance(private_state,dict) else {}
    candidates=dict(state.get("candidates") or {})
    interviews=dict(state.get("interviews") or {})
    admitted=dict(state.get("admitted") or {})
    now=_utcnow()
    newly_high=0
    reobserved=0
    rescanned=0

    for row in enriched or []:
        if not isinstance(row,dict):
            continue
        classification=str(row.get("classification") or "")
        if classification not in {"WEAK_SIGNAL","INTERESTING","HIGH_INTEREST"}:
            continue
        key=private_candidate_key(row)
        prev=dict(candidates.get(key) or {})
        observations=int(prev.get("observations") or 0)+1
        if observations>1:
            reobserved += 1
        previous_scan=str(prev.get("last_scan_utc") or "")
        scan_count=int(prev.get("scan_count") or (1 if prev else 0))
        if previous_scan != now:
            if prev:
                scan_count += 1
                rescanned += 1
            elif scan_count < 1:
                scan_count = 1
        if classification=="HIGH_INTEREST" and str(prev.get("classification") or "")!="HIGH_INTEREST":
            newly_high += 1
        incoming_sources=[
            str(x) for x in (row.get("source_provenance") or [])
            if str(x).strip()
        ]
        if row.get("source"):
            incoming_sources.append(str(row.get("source")))
        sources=sorted(set(
            list(prev.get("sources") or []) + incoming_sources
        ))[:8]
        registry_statuses=sorted(set(
            list(prev.get("registry_statuses") or [])
            + ([str(row.get("registry_status"))] if row.get("registry_status") else [])
        ))[:8]
        score=max(int(prev.get("max_score") or 0),int(row.get("agent_likelihood_score") or 0))
        candidates[key]={
            "key":key,
            "fingerprint":str(row.get("fingerprint") or prev.get("fingerprint") or ""),
            "url":str(row.get("url") or prev.get("url") or "")[:1200],
            "title":str(row.get("title") or prev.get("title") or "")[:300],
            "domain":str(row.get("domain") or prev.get("domain") or "")[:180],
            "snippet":str(row.get("snippet") or prev.get("snippet") or "")[:600],
            "classification":classification,
            "max_score":score,
            "signals":list(row.get("signals") or prev.get("signals") or [])[:12],
            "sources":sources,
            "source_diversity":len(sources),
            "registry_statuses":registry_statuses,
            "observations":observations,
            "scan_count":scan_count,
            "last_scan_utc":now,
            "first_seen_utc":str(prev.get("first_seen_utc") or row.get("first_seen_utc") or now),
            "last_seen_utc":str(row.get("last_seen_utc") or now),
        }

    ranked=sorted(
        candidates.items(),
        key=lambda kv:(
            int((kv[1] or {}).get("max_score") or 0),
            int((kv[1] or {}).get("source_diversity") or 0),
            int((kv[1] or {}).get("observations") or 0),
            str((kv[1] or {}).get("last_seen_utc") or ""),
        ),
        reverse=True,
    )[:max(4,min(max_entries,24))]

    state={
        "schema_v":2,
        "updated_at_utc":now,
        "candidates":dict(ranked),
        "interviews":dict(list(interviews.items())[-32:]),
        "admitted":dict(list(admitted.items())[-16:]),
    }
    summary={
        "private_candidates":len(ranked),
        "private_high_interest":sum(1 for _,v in ranked if (v or {}).get("classification")=="HIGH_INTEREST"),
        "private_interesting":sum(1 for _,v in ranked if (v or {}).get("classification")=="INTERESTING"),
        "reobserved_this_scan":reobserved,
        "rescanned_candidates":rescanned,
        "new_high_interest_this_scan":newly_high,
        "max_private_score":max([int((v or {}).get("max_score") or 0) for _,v in ranked] or [0]),
        "max_source_diversity":max([int((v or {}).get("source_diversity") or 0) for _,v in ranked] or [0]),
    }
    return state,summary



def interview_candidate_eligibility(candidate: dict) -> dict:
    """Conservative gate before any active contact.

    Discovery stays passive. Contact is allowed only for a re-observed HIGH_INTEREST
    candidate whose indexed URL itself looks like an explicit public A2A endpoint/card.
    """
    if not isinstance(candidate,dict):
        return {"eligible":False,"reason":"invalid_candidate"}
    classification=str(candidate.get("classification") or "")
    score=int(candidate.get("max_score") or 0)
    scans=int(candidate.get("scan_count") or 0)
    observations=int(candidate.get("observations") or 0)
    diversity=int(candidate.get("source_diversity") or 0)
    url=str(candidate.get("url") or "").strip()
    try:
        p=urlparse(url)
        host=(p.hostname or "").lower().strip(".")
        path=(p.path or "/").lower().rstrip("/") or "/"
    except Exception:
        return {"eligible":False,"reason":"invalid_url"}

    if classification!="HIGH_INTEREST" and score<75:
        return {"eligible":False,"reason":"below_high_interest"}
    if scans<2 and diversity<2:
        return {"eligible":False,"reason":"needs_independent_reobservation"}
    if observations<2 and diversity<2:
        return {"eligible":False,"reason":"insufficient_persistence"}
    if not host or p.scheme!="https":
        return {"eligible":False,"reason":"https_public_endpoint_required"}

    artifact_hosts={
        "github.com","www.github.com","news.ycombinator.com","stackoverflow.com",
        "stackexchange.com","www.stackexchange.com","bing.com","www.bing.com",
    }
    if host in artifact_hosts or host.endswith(".github.com"):
        return {"eligible":False,"reason":"indexed_artifact_not_agent_endpoint"}

    card_paths=("/.well-known/agent-card.json","/.well-known/agent.json")
    if any(path.endswith(x) for x in card_paths):
        return {
            "eligible":True,
            "reason":"public_agent_card",
            "contact_mode":"agent_card",
            "url":url,
        }

    explicit_markers=("/a2a","/message/send","/agent/a2a","/agents/a2a")
    if any(path==x or path.endswith(x) for x in explicit_markers):
        return {
            "eligible":True,
            "reason":"explicit_public_a2a_endpoint",
            "contact_mode":"direct_a2a",
            "url":url,
        }

    return {"eligible":False,"reason":"no_explicit_agent_endpoint"}


def interview_response_score(text: str) -> dict:
    """Score a bounded interview response without treating it as evidence of truth."""
    raw=" ".join(str(text or "").split())
    low=raw.lower()
    markers={
        "identity":any(x in low for x in ("i am","agent","assistant","system","service")),
        "capabilities":any(x in low for x in ("capabilit","can ","support","skill","tool")),
        "protocol":any(x in low for x in ("a2a","agent2agent","json-rpc","jsonrpc","mcp","message/send")),
        "limits":any(x in low for x in ("limit","cannot","can't","unable","restriction","failure")),
        "evidence":any(x in low for x in ("source","evidence","documentation","docs","reference","url")),
    }
    score=0
    if len(raw)>=120: score+=20
    if len(raw)>=300: score+=10
    score += 15 if markers["identity"] else 0
    score += 20 if markers["capabilities"] else 0
    score += 20 if markers["protocol"] else 0
    score += 10 if markers["limits"] else 0
    score += 5 if markers["evidence"] else 0
    score=min(100,score)
    return {
        "score":score,
        "markers":markers,
        "accepted":bool(score>=65 and markers["capabilities"] and markers["protocol"]),
    }


def merge_signal_memory(memory: dict, scan: dict, max_entries: int = 80) -> tuple[dict,list[dict]]:
    """Persist only non-reversible fingerprints/metadata, never target URLs or snippets."""
    old=memory if isinstance(memory,dict) else {}
    now=str(scan.get("scanned_at_utc") or _utcnow())
    updated=dict(old)
    enriched=[]
    for row in scan.get("signals") or []:
        if not isinstance(row,dict):
            continue
        fp=str(row.get("fingerprint") or "")
        if not fp:
            continue
        prev=dict(updated.get(fp) or {})
        seen=int(prev.get("seen_count") or 0)+1
        first=str(prev.get("first_seen_utc") or now)
        base=int(row.get("agent_likelihood_score") or 0)
        persistence_bonus=0
        if seen>=2:
            persistence_bonus=8
        if seen>=3:
            persistence_bonus=14
        adjusted=min(100,base+persistence_bonus)
        updated[fp]={
            "first_seen_utc":first,
            "last_seen_utc":now,
            "seen_count":seen,
            "max_score":max(int(prev.get("max_score") or 0),adjusted),
            "last_classification":_classification(adjusted),
        }
        copy=dict(row)
        copy["seen_count"]=seen
        copy["first_seen_utc"]=first
        copy["last_seen_utc"]=now
        copy["persistence_bonus"]=persistence_bonus
        copy["agent_likelihood_score"]=adjusted
        copy["classification"]=_classification(adjusted)
        enriched.append(copy)

    ranked=sorted(
        updated.items(),
        key=lambda kv:(int((kv[1] or {}).get("seen_count") or 0),int((kv[1] or {}).get("max_score") or 0),str((kv[1] or {}).get("last_seen_utc") or "")),
        reverse=True,
    )[:max(10,min(max_entries,120))]
    return dict(ranked),enriched
