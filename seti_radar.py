import asyncio
import hashlib
import json
import re
from datetime import datetime, timezone
from urllib.parse import urlparse, unquote
from typing import Any, Awaitable, Callable

SETI_SCHEMA_VERSION = 2
SETI_ENGINE_VERSION = 11

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


def _normalize_indexed_url_text(text: str) -> str:
    value=str(text or "")
    value=value.replace("\\/","/")
    try:
        value=unquote(value)
    except Exception:
        pass
    return value


def indexed_url_declared_as_agent_endpoint(text: str, url: str) -> bool:
    """Accept a non-standard path only when the public indexed text explicitly labels it as an agent endpoint."""
    raw_url=str(url or "").strip()
    try:
        p=urlparse(raw_url)
        host=(p.hostname or "").lower().strip(".")
    except Exception:
        return False
    if p.scheme!="https" or not host:
        return False
    if host in OFFICIAL_OR_LOW_VALUE_DOMAINS or host in COMMON_HOSTS:
        return False
    if host in {"localhost","localhost.localdomain"} or host.endswith(".local"):
        return False

    normalized=_normalize_indexed_url_text(text)
    low=normalized.lower()
    needle=raw_url.lower()
    pos=low.find(needle)
    if pos<0:
        context=low
    else:
        context=low[max(0,pos-220):min(len(low),pos+len(needle)+220)]

    explicit_label=bool(re.search(
        r"\b(?:a2a|agent2agent|agent)\s+(?:public\s+)?(?:endpoint|url)\b",
        context,
    ))
    rpc_label=(
        "message/send" in context
        and ("jsonrpc" in context or "json-rpc" in context)
        and ("endpoint" in context or re.search(r"\burl\s*[:=]",context))
    )
    agent_card_url_field=(
        ("agent card" in context or "protocolversion" in context or "protocol version" in context)
        and bool(re.search(r'["\']?url["\']?\s*[:=]',context))
    )
    return bool(explicit_label or rpc_label or agent_card_url_field)


def indexed_endpoint_leads(row: dict, limit: int = 4) -> list[dict]:
    """Extract explicitly declared public A2A endpoints from indexed text only.

    This does not fetch, resolve or probe the extracted host. It turns a URL that is
    already visible in a public search/code index into a quarantined SETI lead.
    """
    if not isinstance(row,dict):
        return []
    text=_normalize_indexed_url_text(" ".join([
        str(row.get("title") or ""),
        str(row.get("snippet") or row.get("description") or ""),
    ]))
    urls=re.findall(r'https://[^\s<>"\]\[(){}]+',text,re.I)
    out=[]
    seen=set()
    provenance=str(row.get("url") or "").strip()
    source=str(row.get("source") or "public_index")
    for raw in urls:
        url=raw.rstrip(".,;:!?")
        if url in seen:
            continue
        strict_path=explicit_agent_endpoint_url(url)
        contextual=indexed_url_declared_as_agent_endpoint(text,url)
        if not strict_path and not contextual:
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
            "endpoint_evidence":"explicit_path" if strict_path else "indexed_context_declaration",
        })
        if len(out)>=max(1,min(limit,8)):
            break
    return out



def registry_agent_candidate(agent: dict, source: str = "a2a_public_registry") -> dict | None:
    """Normalize a public registry row into a bounded SETI interview candidate.

    Registry membership is discovery evidence only. It does not imply trust, quality,
    commercial demand or permission to execute tools. Only HTTPS Agent Cards or
    explicitly declared HTTPS A2A endpoints are accepted.
    """
    if not isinstance(agent,dict):
        return None

    card=agent.get("agentCard") if isinstance(agent.get("agentCard"),dict) else {}
    if not card and isinstance(agent.get("card"),dict):
        card=agent.get("card") or {}

    def first_text(*values: Any) -> str:
        for value in values:
            text=str(value or "").strip()
            if text:
                return text
        return ""

    endpoint=first_text(
        agent.get("url"),
        agent.get("endpoint"),
        agent.get("endpoint_url"),
        card.get("url"),
        card.get("endpoint"),
    )
    card_url=first_text(
        agent.get("wellKnownURI"),
        agent.get("well_known_uri"),
        agent.get("agent_card_url"),
        agent.get("agentCardUrl"),
        agent.get("manifest_url"),
        agent.get("manifestUrl"),
    )

    chosen=endpoint or card_url
    if not chosen:
        return None
    try:
        parsed=urlparse(chosen)
        host=(parsed.hostname or "").lower().strip(".")
    except Exception:
        return None
    if parsed.scheme!="https" or not host:
        return None
    if host in OFFICIAL_OR_LOW_VALUE_DOMAINS or host in COMMON_HOSTS:
        return None
    if host in {"localhost","localhost.localdomain"} or host.endswith(".local"):
        return None

    direct=bool(endpoint)
    if not direct and not explicit_agent_endpoint_url(card_url):
        return None

    name=first_text(
        agent.get("name"),
        agent.get("displayName"),
        agent.get("display_name"),
        agent.get("package_name"),
        card.get("name"),
        host,
    )
    description=first_text(
        agent.get("description"),
        agent.get("summary"),
        card.get("description"),
    )

    conformance=str(agent.get("conformance") or agent.get("conformance_status") or "").lower()
    task_verified=bool(agent.get("task_verified") or agent.get("taskVerified"))
    healthy=bool(agent.get("is_healthy") or agent.get("healthy") or agent.get("reachable"))
    verified=bool(agent.get("verified") or agent.get("is_verified") or agent.get("dns_verified"))

    score=70
    signals=["public_registry_listing"]
    if conformance in {"standard","true","verified","conformant"}:
        score += 8
        signals.append("standard_conformance")
    if task_verified:
        score += 8
        signals.append("task_verified")
    if healthy:
        score += 6
        signals.append("healthy")
    if verified:
        score += 4
        signals.append("identity_or_domain_verified")
    score=min(96,score)

    row={
        "title":name[:300],
        "url":chosen[:1200],
        "domain":host[:180],
        "snippet":description[:1400],
        "source":str(source or "a2a_public_registry")[:120],
        "source_provenance":[str(source or "a2a_public_registry")[:120]],
        "agent_likelihood_score":score,
        "classification":"HIGH_INTEREST" if score>=82 else "INTERESTING",
        "signals":signals,
        "registry_status":"registry_listed",
        "indexed_declared_endpoint":True,
        "endpoint_evidence":"public_registry_direct_endpoint" if direct else "public_registry_agent_card",
        "provenance_url":card_url[:1200],
        "first_seen_utc":_utcnow(),
        "last_seen_utc":_utcnow(),
    }
    row["fingerprint"]=signal_fingerprint(row)
    return row


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
            "indexed_declared_endpoint":bool(row.get("indexed_declared_endpoint") or prev.get("indexed_declared_endpoint")),
            "endpoint_evidence":str(row.get("endpoint_evidence") or prev.get("endpoint_evidence") or "")[:120],
            "provenance_url":str(row.get("provenance_url") or prev.get("provenance_url") or "")[:1200],
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
    """Allow a bounded first-contact interview when a public agent endpoint is explicit.

    Discovery itself stays passive. Once a public A2A endpoint or Agent Card has already
    been declared in an indexed source, an INTERESTING/HIGH_INTEREST candidate may be
    interviewed immediately. Re-observation improves confidence but is no longer required
    before saying hello; admission still requires a substantive protocol-aware answer.
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

    if classification not in {"INTERESTING","HIGH_INTEREST"} and score<50:
        return {"eligible":False,"reason":"below_interview_interest"}
    if not host or p.scheme!="https":
        return {"eligible":False,"reason":"https_public_endpoint_required"}

    artifact_hosts={
        "github.com","www.github.com","news.ycombinator.com","stackoverflow.com",
        "stackexchange.com","www.stackexchange.com","bing.com","www.bing.com",
    }
    if host in artifact_hosts or host.endswith(".github.com"):
        return {"eligible":False,"reason":"indexed_artifact_not_agent_endpoint"}

    confidence={
        "scan_count":scans,
        "observations":observations,
        "source_diversity":diversity,
        "first_contact":bool(scans<=1 and observations<=1),
    }

    card_paths=("/.well-known/agent-card.json","/.well-known/agent.json")
    if any(path.endswith(x) for x in card_paths):
        return {
            "eligible":True,
            "reason":"public_agent_card",
            "contact_mode":"agent_card",
            "url":url,
            "confidence":confidence,
        }

    if bool(candidate.get("indexed_declared_endpoint")):
        return {
            "eligible":True,
            "reason":"indexed_declared_public_agent_endpoint",
            "contact_mode":"direct_a2a",
            "url":url,
            "confidence":dict(confidence,endpoint_evidence=str(candidate.get("endpoint_evidence") or "indexed_declaration")),
        }

    explicit_markers=("/a2a","/message/send","/agent/a2a","/agents/a2a")
    if any(path==x or path.endswith(x) for x in explicit_markers):
        return {
            "eligible":True,
            "reason":"explicit_public_a2a_endpoint",
            "contact_mode":"direct_a2a",
            "url":url,
            "confidence":confidence,
        }

    return {"eligible":False,"reason":"no_explicit_agent_endpoint"}


def seti_candidate_attempt_state(candidate: dict, prior: dict | None, now_utc: str, min_seconds: int = 3600) -> dict:
    """Explain whether an eligible candidate is ready for interview right now."""
    eligibility=interview_candidate_eligibility(candidate)
    if not eligibility.get("eligible"):
        return {"ready":False,"reason":"ineligible","eligibility_reason":eligibility.get("reason")}
    prior=prior if isinstance(prior,dict) else {}
    status=str(prior.get("status") or "")
    attempts=max(0,int(prior.get("attempts") or (1 if prior else 0)))
    block_reason=str(prior.get("reason") or prior.get("peer_state") or "").upper()
    followup_state=str(prior.get("followup_state") or "").upper()
    if status=="ADMITTED":
        return {"ready":False,"reason":"already_admitted","attempts":attempts}
    if block_reason=="AUTH_REQUIRED" or followup_state=="AUTH_BLOCKED":
        return {"ready":False,"reason":"auth_required","attempts":attempts}
    if status=="PARKED" and attempts>=3:
        return {"ready":False,"reason":"attempts_exhausted","attempts":attempts}
    if status=="PARKED" and not seti_retry_ready(prior,now_utc,min_seconds):
        return {"ready":False,"reason":"rate_limited","attempts":attempts}
    return {
        "ready":True,
        "reason":"ready",
        "attempts":attempts,
        "eligibility_reason":eligibility.get("reason"),
        "contact_mode":eligibility.get("contact_mode"),
    }


def summarize_interview_readiness(candidates: dict, interviews: dict, admitted: dict, now_utc: str, min_seconds: int = 3600) -> dict:
    """Non-sensitive readiness summary for public runtime telemetry."""
    counts={}
    ready=0
    eligible=0
    for key,candidate in (candidates or {}).items():
        if not isinstance(candidate,dict):
            continue
        prior=(interviews or {}).get(key) if isinstance((interviews or {}).get(key),dict) else {}
        state=seti_candidate_attempt_state(candidate,prior,now_utc,min_seconds)
        if state.get("eligibility_reason") or state.get("reason")!="ineligible":
            if interview_candidate_eligibility(candidate).get("eligible"):
                eligible += 1
        reason=str(state.get("reason") or "unknown")
        counts[reason]=counts.get(reason,0)+1
        if state.get("ready"):
            ready += 1
    return {"eligible":eligible,"ready_now":ready,"reason_counts":dict(sorted(counts.items()))}


def summarize_candidate_eligibility(candidates: dict) -> dict:
    """Return non-sensitive eligibility telemetry for the public SETI summary."""
    rows=[v for v in (candidates or {}).values() if isinstance(v,dict)]
    reason_counts={}
    high_reason_counts={}
    eligible=0
    high_eligible=0
    for candidate in rows:
        result=interview_candidate_eligibility(candidate)
        reason=str(result.get("reason") or "unknown")
        reason_counts[reason]=reason_counts.get(reason,0)+1
        if result.get("eligible"):
            eligible += 1
        if str(candidate.get("classification") or "")=="HIGH_INTEREST":
            high_reason_counts[reason]=high_reason_counts.get(reason,0)+1
            if result.get("eligible"):
                high_eligible += 1
    return {
        "candidates":len(rows),
        "eligible":eligible,
        "ineligible":max(0,len(rows)-eligible),
        "high_interest":sum(1 for x in rows if str(x.get("classification") or "")=="HIGH_INTEREST"),
        "high_interest_eligible":high_eligible,
        "reason_counts":dict(sorted(reason_counts.items())),
        "high_interest_reason_counts":dict(sorted(high_reason_counts.items())),
    }


INTERVIEW_MARKER_LABELS={
    "identity":"role/identity",
    "capabilities":"concrete capabilities",
    "protocol":"protocol/interface details",
    "limits":"one important limitation or failure mode",
    "evidence":"one public documentation/evidence reference (or explicitly say none exists)",
}


def seti_dialogue_round(previous: dict | None) -> int:
    """Return the next substantive dialogue round (1..3), ignoring pure transport failures."""
    previous=previous if isinstance(previous,dict) else {}
    history=previous.get("attempt_history") if isinstance(previous.get("attempt_history"),list) else []
    substantive=sum(
        1 for row in history
        if isinstance(row,dict) and str(row.get("response") or "").strip()
    )
    if not history and str(previous.get("response_full") or previous.get("response_excerpt") or "").strip():
        substantive=1
    return max(1,min(3,substantive+1))


def seti_progressive_interview_prompt(previous: dict | None, base_prompt: str) -> str:
    """Build the next bounded prompt without treating prior self-reports as verified facts."""
    previous=previous if isinstance(previous,dict) else {}
    round_no=seti_dialogue_round(previous)
    if round_no<=1:
        return str(base_prompt or "").strip()

    markers=previous.get("markers") if isinstance(previous.get("markers"),dict) else {}
    missing=[label for key,label in INTERVIEW_MARKER_LABELS.items() if not markers.get(key)]
    missing_text=", ".join(missing) if missing else "specificity and falsifiable evidence"

    if round_no==2:
        return (
            "MYCELIX bounded capability interview — Round 2/3. Your prior answer remains PARKED; "
            "this does not imply rejection or verified identity. Do not simply repeat the introduction. "
            "Clarify the following missing or weak areas: "+missing_text+". "
            "Then propose one small falsifiable test of one capability you claim: state the input, "
            "expected observable output, a control or negative case, and what result would show the claim is false. "
            "If you have a public documentation/evidence URL, provide it; otherwise explicitly say that none is available. "
            "Do not execute tools, contact third parties, make purchases, or perform external actions."
        )

    return (
        "MYCELIX bounded capability interview — Round 3/3 (final automatic follow-up). "
        "Your prior replies remain unverified self-reports. Resolve any remaining weak areas: "+missing_text+". "
        "Give: (1) exact protocol/interface and relevant method or message shape you support, "
        "(2) one concrete task you can perform, (3) one limitation or known failure condition, "
        "(4) one public documentation/evidence URL or an explicit statement that none exists, and "
        "(5) one falsification condition that would cause MYCELIX to reject your capability claim. "
        "Be concise and testable. Do not execute tools, contact third parties, make purchases, "
        "or perform external actions."
    )


def seti_followup_state(previous: dict | None, max_attempts: int = 3) -> str:
    previous=previous if isinstance(previous,dict) else {}
    status=str(previous.get("status") or "").upper()
    attempts=max(0,int(previous.get("attempts") or 0))
    if status=="ADMITTED":
        return "COMPLETE"
    reason=str(previous.get("reason") or previous.get("peer_state") or "").upper()
    if reason=="AUTH_REQUIRED" or str(previous.get("followup_state") or "").upper()=="AUTH_BLOCKED":
        return "AUTH_BLOCKED"
    if attempts>=max(1,int(max_attempts or 3)):
        return "EXHAUSTED"
    if not previous:
        return "FIRST_CONTACT"
    has_response=bool(str(previous.get("response_full") or previous.get("response_excerpt") or "").strip())
    if not has_response:
        history=previous.get("attempt_history") if isinstance(previous.get("attempt_history"),list) else []
        has_response=any(
            isinstance(row,dict) and str(row.get("response") or "").strip()
            for row in history
        )
    return "FOLLOWUP_DUE" if has_response else "RETRY_TRANSPORT"


def seti_retry_ready(previous: dict | None, now_utc: str, min_seconds: int = 3600) -> bool:
    """Rate-limit automatic follow-ups so repeated scans do not spam a public endpoint."""
    previous=previous if isinstance(previous,dict) else {}
    if not previous:
        return True
    if seti_followup_state(previous) in {"COMPLETE","EXHAUSTED"}:
        return False
    last=str(previous.get("last_attempt_utc") or previous.get("interviewed_at_utc") or "").strip()
    if not last:
        return True
    try:
        now=datetime.fromisoformat(str(now_utc).replace("Z","+00:00")).astimezone(timezone.utc)
        then=datetime.fromisoformat(last.replace("Z","+00:00")).astimezone(timezone.utc)
        configured=max(0,int(min_seconds or 0))
        override=max(0,int(previous.get("retry_after_seconds") or 0))
        return (now-then).total_seconds()>=max(configured,override)
    except Exception:
        return True


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


def inbound_admission_transition(sender_declared: bool, text: str, previous: dict | None = None) -> dict:
    """Classify a public inbound contact before it may contribute to collective memory.

    Identity remains self-declared unless separately verified. A first contact must
    demonstrate both capabilities and an agent protocol. Weak contacts stay PARKED
    and may retry up to three times. Already-admitted peers remain admitted.
    """
    previous=previous if isinstance(previous,dict) else {}
    old_status=str(previous.get("status") or "").upper()
    old_attempts=max(0,int(previous.get("interview_attempts") or 0))

    if old_status=="ADMITTED":
        return {
            "status":"ADMITTED",
            "interview_attempts":old_attempts,
            "interview_score":int(previous.get("interview_score") or 0),
            "markers":previous.get("markers") if isinstance(previous.get("markers"),dict) else {},
            "identity_status":str(previous.get("identity_status") or "self_declared"),
            "retry_allowed":False,
            "newly_admitted":False,
            "reason":"previously_admitted",
        }

    if not sender_declared:
        return {
            "status":"ANONYMOUS",
            "interview_attempts":old_attempts,
            "interview_score":0,
            "markers":{},
            "identity_status":"anonymous",
            "retry_allowed":True,
            "newly_admitted":False,
            "reason":"declared_agent_identity_required",
        }

    attempts=old_attempts+1
    scored=interview_response_score(text)
    if scored.get("accepted"):
        return {
            "status":"ADMITTED",
            "interview_attempts":attempts,
            "interview_score":int(scored.get("score") or 0),
            "markers":scored.get("markers") or {},
            "identity_status":"self_declared",
            "retry_allowed":False,
            "newly_admitted":True,
            "reason":"substantive_protocol_aware_introduction",
        }

    return {
        "status":"PARKED",
        "interview_attempts":attempts,
        "interview_score":int(scored.get("score") or 0),
        "markers":scored.get("markers") or {},
        "identity_status":"self_declared",
        "retry_allowed":bool(attempts<3),
        "newly_admitted":False,
        "reason":"introduction_not_yet_sufficient" if attempts<3 else "parked_after_three_weak_introductions",
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
