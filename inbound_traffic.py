from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone, timedelta
from typing import Any
from urllib.parse import urlparse

CATEGORIES=("crawler_probe","real_contact","unknown")

KNOWN_CRAWLERS=(
    ("agent-tools.cloud",("agent-tools.cloud","agent-tools")),
    ("community_a2a_registry",("a2a-registry","a2aregistry")),
    ("allagents",("allagents","allagents.ai")),
    ("mcp_registry",("registry.modelcontextprotocol.io","modelcontextprotocol")),
)

def _clean(value: Any, limit: int=500) -> str:
    return " ".join(str(value or "").split())[:limit]

def known_crawler(user_agent: str="", origin: str="") -> str|None:
    hay=(" "+_clean(user_agent,500)+" "+_clean(origin,500)).lower()
    for name,markers in KNOWN_CRAWLERS:
        if any(marker in hay for marker in markers):
            return name
    return None

def classify_inbound_event(*, endpoint: str, method: str, user_agent: str="", origin: str="",
                           rpc_method: str="", has_text: bool=False) -> tuple[str,str,str|None]:
    endpoint=_clean(endpoint,300)
    method=_clean(method,20).upper()
    rpc=_clean(rpc_method,120)
    crawler=known_crawler(user_agent,origin)
    if crawler:
        return "crawler_probe","known_directory_or_crawler_origin",crawler
    if endpoint in {"/.well-known/agent-card.json","/.well-known/agent.json"}:
        return "crawler_probe","agent_card_fetch",None
    if endpoint=="/health" and method=="GET":
        return "crawler_probe","health_fetch",None
    if endpoint=="/a2a" and rpc in {"message/send","SendMessage"} and has_text:
        return "real_contact","a2a_text_message",None
    if endpoint.startswith("/mcp") and rpc=="tools/call":
        return "real_contact","mcp_tools_call",None
    if endpoint.startswith("/mcp") and rpc in {"initialize","tools/list"}:
        return "crawler_probe","mcp_handshake_or_discovery_without_observed_tool_call",None
    return "unknown","no_contact_or_probe_rule_matched",None

def source_key(event: dict) -> str:
    session=_clean(event.get("mcp_session_id"),300)
    if session:
        return "session:"+session
    return "source:"+_clean(event.get("ip_or_origin"),300).lower()+"|"+_clean(event.get("user_agent"),300).lower()

def append_event(events: list[dict]|None, event: dict, *, max_events: int=1200) -> list[dict]:
    rows=[dict(x) for x in (events or []) if isinstance(x,dict)]
    row=dict(event)
    rows.append(row)
    if row.get("category")=="real_contact" and row.get("rpc_method")=="tools/call":
        key=source_key(row)
        if key not in {"source:|","source:|"}:
            for prior in reversed(rows[:-1]):
                if source_key(prior)!=key:
                    continue
                if prior.get("category")=="crawler_probe" and prior.get("rpc_method") in {"initialize","tools/list"}:
                    if prior.get("crawler_name"):
                        continue
                    prior["category"]="real_contact"
                    prior["reason"]="mcp_session_progressed_to_tools_call"
                if prior.get("rpc_method")=="initialize":
                    break
    return rows[-max_events:]

def summarize_events(events: list[dict]|None, *, now: datetime|None=None) -> dict:
    now=now or datetime.now(timezone.utc)
    rows=[x for x in (events or []) if isinstance(x,dict)]
    windows={"total":Counter(),"last_24h":Counter(),"last_7d":Counter()}
    real_times=[]
    crawler_origins=Counter()
    for row in rows:
        cat=str(row.get("category") or "unknown")
        if cat not in CATEGORIES: cat="unknown"
        windows["total"][cat]+=1
        try:
            ts=datetime.fromisoformat(str(row.get("timestamp_utc") or "").replace("Z","+00:00"))
            if ts.tzinfo is None: ts=ts.replace(tzinfo=timezone.utc)
        except Exception:
            ts=None
        if ts is not None:
            if ts >= now-timedelta(hours=24): windows["last_24h"][cat]+=1
            if ts >= now-timedelta(days=7): windows["last_7d"][cat]+=1
            if cat=="real_contact": real_times.append(ts)
        if cat=="crawler_probe":
            name=_clean(row.get("crawler_name") or row.get("ip_or_origin") or row.get("user_agent") or "unknown",300)
            crawler_origins[name]+=1
    def counts(c: Counter) -> dict:
        return {k:int(c.get(k,0)) for k in CATEGORIES}
    return {
        "schema_v":1,
        "events_total":len(rows),
        "counts":{
            "total":counts(windows["total"]),
            "last_24h":counts(windows["last_24h"]),
            "last_7d":counts(windows["last_7d"]),
        },
        "first_real_contact_utc":min(real_times).isoformat() if real_times else None,
        "last_real_contact_utc":max(real_times).isoformat() if real_times else None,
        "crawler_origins":[{"name":name,"requests":count} for name,count in crawler_origins.most_common()],
    }

def retroactive_from_inbound_messages(messages: list[dict]|None) -> list[dict]:
    out=[]
    for row in messages or []:
        if not isinstance(row,dict): continue
        rpc=_clean(row.get("method"),120)
        has_text=bool(_clean(row.get("text"),1))
        if rpc not in {"message/send","SendMessage"} or not has_text:
            continue
        sender=row.get("sender") if isinstance(row.get("sender"),dict) else {}
        origin=_clean(row.get("agent_card_url") or sender.get("agent_id") or sender.get("agent") or "historical_a2a",300)
        out.append({
            "timestamp_utc":row.get("received_at_utc"),
            "endpoint":"/a2a",
            "method":"POST",
            "user_agent":None,
            "ip_or_origin":origin,
            "category":"real_contact",
            "reason":"historical_a2a_text_message_from_existing_log",
            "rpc_method":rpc,
            "crawler_name":None,
            "historical_derived":True,
        })
    return out
