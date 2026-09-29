from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone, timedelta
import hashlib
import re
from typing import Any
from urllib.parse import urlparse
from inbound_security import classify_inbound_security

CATEGORIES=("crawler_probe","self_traffic","real_contact_pending","real_contact","legacy_unattributable","malicious_solicitation","unknown")
OFFICIAL_COUNTING_SINCE_UTC="2026-09-28T07:07:09+00:00"

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

def content_fingerprint(text: str) -> str|None:
    normalized=" ".join(str(text or "").lower().split())
    if not normalized:
        return None
    return hashlib.sha256(normalized.encode("utf-8","ignore")).hexdigest()[:24]

def active_probe_candidate(user_agent: str="", declared_agent_id: str="") -> bool:
    if _clean(declared_agent_id,300):
        return False
    return bool(re.search(r"(?i)\b(?:probe|healthcheck|health-check|liveness)\b",_clean(user_agent,500)))

def classify_inbound_event(*, endpoint: str, method: str, user_agent: str="", origin: str="",
                           rpc_method: str="", has_text: bool=False, text: str="", self_marker: str="", self_verified: bool=False, declared_agent_id: str="") -> tuple[str,str,str|None]:
    endpoint=_clean(endpoint,300)
    method=_clean(method,20).upper()
    rpc=_clean(rpc_method,120)
    self_hay=(" "+_clean(declared_agent_id,300)+" "+_clean(user_agent,500)+" "+_clean(origin,500)).lower()
    if _clean(self_marker,300) and bool(self_verified):
        return "self_traffic","verified_mycelix_self_marker",None
    if any(marker in self_hay for marker in ("chatgpt-research-session","mycelix-internal","jarvis-internal","neo-internal","pathwren.workers.dev/mcp-lint","growth-loop/1.0")):
        return "self_traffic","declared_internal_or_user_authorized_session",None
    if endpoint=="/a2a" and rpc in {"message/send","SendMessage"} and has_text:
        verdict=classify_inbound_security(text)
        if verdict.get("traffic_class")=="MALICIOUS_SOLICITATION":
            return "malicious_solicitation","download_execute_or_reward_solicitation",None
    crawler=known_crawler(user_agent,origin)
    if crawler:
        return "crawler_probe","known_directory_or_crawler_origin",crawler
    if endpoint in {"/.well-known/agent-card.json","/.well-known/agent.json"}:
        return "crawler_probe","agent_card_fetch",None
    if endpoint=="/health" and method=="GET":
        return "crawler_probe","health_fetch",None
    if endpoint=="/a2a" and rpc in {"message/send","SendMessage"} and has_text and active_probe_candidate(user_agent,declared_agent_id):
        return "real_contact_pending","active_a2a_probe_first_seen",None
    if endpoint=="/a2a" and rpc in {"message/send","SendMessage"} and has_text:
        return "real_contact","a2a_text_message",None
    if endpoint.startswith("/mcp") and rpc=="tools/call":
        return "real_contact","mcp_tools_call",None
    if endpoint.startswith("/mcp") and rpc in {"initialize","tools/list"}:
        return "crawler_probe","mcp_handshake_or_discovery_without_observed_tool_call",None
    return "unknown","no_contact_or_probe_rule_matched",None

def reclassify_legacy_contacts(events: list[dict] | None) -> list[dict]:
    """Preserve pre-baseline real contacts but exclude them from official counts."""
    out=[]
    cutoff=datetime.fromisoformat(OFFICIAL_COUNTING_SINCE_UTC)
    for item in events or []:
        if not isinstance(item,dict):
            continue
        row=dict(item)
        if row.get("category")=="real_contact":
            try:
                ts=datetime.fromisoformat(str(row.get("timestamp_utc") or "").replace("Z","+00:00"))
                if ts.tzinfo is None:
                    ts=ts.replace(tzinfo=timezone.utc)
            except Exception:
                ts=None
            if ts is not None and ts < cutoff:
                row["original_category"]=row.get("original_category") or "real_contact"
                row["original_reason"]=row.get("original_reason") or row.get("reason")
                row["category"]="legacy_unattributable"
                row["reason"]="pre_30aeb80_unattributable"
                row["official_counted"]=False
        out.append(row)
    return out


def reclassify_known_self_events(events: list[dict]|None) -> list[dict]:
    """Return a derived copy with known historical self traffic excluded from real contacts."""
    out=[]
    for item in events or []:
        if not isinstance(item,dict):
            continue
        row=dict(item)
        hay=(" "+_clean(row.get("user_agent"),500)+" "+_clean(row.get("ip_or_origin"),500)+" "+_clean(row.get("self_source"),300)).lower()
        source=None
        if "chatgpt-research-session" in hay:
            source="user_authorized_session"
        elif "pathwren.workers.dev/mcp-lint" in hay or "growth-loop/1.0" in hay:
            source="pathwren_ci_validation"
        elif (
            _clean(row.get("user_agent"),300).startswith("python-httpx2/")
            and _clean(row.get("ip_or_origin"),100)=="20.102.46.202"
            and "2026-09-28T07:43:30" <= _clean(row.get("timestamp_utc"),80) <= "2026-09-28T07:44:23"
        ):
            source="github_actions_verify_mcp_live_probe"
        elif row.get("self_source"):
            source=_clean(row.get("self_source"),300)
        if source and row.get("category")!="self_traffic":
            row["original_category"]=row.get("category")
            row["original_reason"]=row.get("reason")
            row["category"]="self_traffic"
            row["reason"]="retroactive_known_self_traffic"
            row["self_source"]=source
        out.append(row)
    return out


def source_key(event: dict) -> str:
    session=_clean(event.get("mcp_session_id"),300)
    if session:
        return "session:"+session
    return "source:"+_clean(event.get("ip_or_origin"),300).lower()+"|"+_clean(event.get("user_agent"),300).lower()

def append_event(events: list[dict]|None, event: dict, *, max_events: int=1200) -> list[dict]:
    rows=[dict(x) for x in (events or []) if isinstance(x,dict)]
    row=dict(event)
    rows.append(row)
    if row.get("category")=="real_contact_pending" and row.get("reason")=="active_a2a_probe_first_seen":
        key=source_key(row)
        fingerprint=_clean(row.get("content_fingerprint"),100)
        try:
            current=datetime.fromisoformat(str(row.get("timestamp_utc") or "").replace("Z","+00:00"))
            if current.tzinfo is None: current=current.replace(tzinfo=timezone.utc)
        except Exception:
            current=None
        matches=[]
        for prior in reversed(rows[:-1]):
            if source_key(prior)!=key or _clean(prior.get("content_fingerprint"),100)!=fingerprint or not fingerprint:
                continue
            if prior.get("endpoint")!="/a2a" or prior.get("rpc_method") not in {"message/send","SendMessage"}:
                continue
            try:
                earlier=datetime.fromisoformat(str(prior.get("timestamp_utc") or "").replace("Z","+00:00"))
                if earlier.tzinfo is None: earlier=earlier.replace(tzinfo=timezone.utc)
            except Exception:
                continue
            if current is not None and timedelta(0) <= current-earlier <= timedelta(minutes=60):
                matches.append(prior)
                break
        if matches:
            for probe in matches+[row]:
                probe["original_category"]=probe.get("category")
                probe["category"]="crawler_probe"
                probe["reason"]="active_a2a_probe_repeated_within_60m"
                probe["crawler_name"]="active_a2a_probe"
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
    rows=reclassify_legacy_contacts(reclassify_known_self_events(events))
    windows={"total":Counter(),"last_24h":Counter(),"last_7d":Counter()}
    real_times=[]
    crawler_origins=Counter()
    real_contact_origins=Counter()
    self_traffic_origins=Counter()
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
        if cat=="real_contact":
            name=_clean(row.get("ip_or_origin") or row.get("user_agent") or "unknown",300)
            real_contact_origins[name]+=1
        if cat=="self_traffic":
            name=_clean(row.get("self_source") or row.get("ip_or_origin") or row.get("user_agent") or "unknown",300)
            self_traffic_origins[name]+=1
    def counts(c: Counter) -> dict:
        return {k:int(c.get(k,0)) for k in CATEGORIES}
    return {
        "schema_v":2,
        "official_counting_since_utc":OFFICIAL_COUNTING_SINCE_UTC,
        "legacy_rule":"real_contact before commit 30aeb80 is preserved as legacy_unattributable and excluded from official real_contact counts",
        "events_total":len(rows),
        "counts":{
            "total":counts(windows["total"]),
            "last_24h":counts(windows["last_24h"]),
            "last_7d":counts(windows["last_7d"]),
        },
        "first_real_contact_utc":min(real_times).isoformat() if real_times else None,
        "last_real_contact_utc":max(real_times).isoformat() if real_times else None,
        "crawler_origins":[{"name":name,"requests":count} for name,count in crawler_origins.most_common()],
        "real_contact_origins":[{"name":name,"requests":count} for name,count in real_contact_origins.most_common()],
        "self_traffic_origins":[{"name":name,"requests":count} for name,count in self_traffic_origins.most_common()],
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
        is_self="chatgpt-research-session" in origin.lower()
        verdict=classify_inbound_security(str(row.get("text") or ""))
        is_malicious=verdict.get("traffic_class")=="MALICIOUS_SOLICITATION"
        out.append({
            "timestamp_utc":row.get("received_at_utc"),
            "endpoint":"/a2a",
            "method":"POST",
            "user_agent":None,
            "ip_or_origin":origin,
            "category":"self_traffic" if is_self else ("malicious_solicitation" if is_malicious else "real_contact"),
            "reason":"historical_user_authorized_session" if is_self else ("historical_download_execute_or_reward_solicitation" if is_malicious else "historical_a2a_text_message_from_existing_log"),
            "rpc_method":rpc,
            "crawler_name":None,
            "self_source":"user_authorized_session" if is_self else None,
            "source_message_id":row.get("message_id"),
            "content_fingerprint":content_fingerprint(str(row.get("text") or "")),
            "historical_derived":True,
        })
    return out

def _event_time(row: dict) -> datetime|None:
    try:
        ts=datetime.fromisoformat(str(row.get("timestamp_utc") or "").replace("Z","+00:00"))
        if ts.tzinfo is None:
            ts=ts.replace(tzinfo=timezone.utc)
        return ts
    except Exception:
        return None


def _same_logical_a2a_evidence(live: dict, derived: dict, *, window_seconds: int=5) -> bool:
    """Match one live request with its historical reconstruction only."""
    if live.get("endpoint")!="/a2a" or derived.get("endpoint")!="/a2a":
        return False
    if str(live.get("rpc_method") or "") != str(derived.get("rpc_method") or ""):
        return False
    fp=str(live.get("content_fingerprint") or "")
    if not fp or fp != str(derived.get("content_fingerprint") or ""):
        return False
    if bool(live.get("historical_derived")) == bool(derived.get("historical_derived")):
        return False
    a,b=_event_time(live),_event_time(derived)
    return bool(a and b and abs((a-b).total_seconds()) <= window_seconds)


def reconcile_message_events(events: list[dict]|None, messages: list[dict]|None) -> list[dict]:
    """Overlay safety classes and coalesce only duplicate live/historical evidence."""
    rows=[dict(x) for x in (events or []) if isinstance(x,dict)]
    for derived in retroactive_from_inbound_messages(messages):
        matched=None
        derived_second=_clean(derived.get("timestamp_utc"),80)[:19]
        for row in rows:
            same_id=bool(derived.get("source_message_id") and row.get("source_message_id")==derived.get("source_message_id"))
            same_shape=(
                _clean(row.get("timestamp_utc"),80)[:19]==derived_second
                and row.get("endpoint")=="/a2a"
                and row.get("rpc_method")==derived.get("rpc_method")
            )
            same_evidence=_same_logical_a2a_evidence(row,derived)
            if same_id or same_shape or same_evidence:
                matched=row
                break
        if matched is None:
            derived["logical_message_id"]="a2a:"+str(derived.get("source_message_id") or derived.get("content_fingerprint") or "historical")
            derived["logical_evidence_count"]=1
            rows=append_event(rows,derived)
            continue

        evidence=list(matched.get("logical_evidence") or [])
        if not evidence:
            evidence.append({
                "timestamp_utc":matched.get("timestamp_utc"),
                "user_agent":matched.get("user_agent"),
                "ip_or_origin":matched.get("ip_or_origin"),
                "historical_derived":bool(matched.get("historical_derived")),
            })
        evidence.append({
            "timestamp_utc":derived.get("timestamp_utc"),
            "user_agent":derived.get("user_agent"),
            "ip_or_origin":derived.get("ip_or_origin"),
            "historical_derived":bool(derived.get("historical_derived")),
        })
        matched["logical_evidence"]=evidence
        matched["logical_evidence_count"]=len(evidence)
        matched["logical_message_id"]=matched.get("logical_message_id") or ("a2a:"+str(derived.get("source_message_id") or derived.get("content_fingerprint") or "unknown"))
        matched["source_message_id"]=matched.get("source_message_id") or derived.get("source_message_id")
        if derived.get("category") in {"malicious_solicitation","self_traffic"}:
            if matched.get("category")!=derived.get("category"):
                matched["original_category"]=matched.get("category")
                matched["original_reason"]=matched.get("reason")
            matched["category"]=derived.get("category")
            matched["reason"]=derived.get("reason")
            matched["content_fingerprint"]=derived.get("content_fingerprint")
    return rows[-1200:]
