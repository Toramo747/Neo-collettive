# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Andrea Gava
"""Optional paid search providers for MYCELIX public research.

Secrets are read only from environment variables. They are never returned,
persisted, logged, or interpolated into error messages.

Official provider contracts implemented:
- Brave Search API: GET https://api.search.brave.com/res/v1/web/search
  header X-Subscription-Token, query params q/count. Brave is the recommended
  provider for new MYCELIX deployments.
- Google Programmable Search JSON API:
  GET https://www.googleapis.com/customsearch/v1
  query params key/cx/q/num.

Google's current documentation says Custom Search JSON API is closed to new
customers and existing customers must transition by January 1, 2027. New
Programmable Search Engines are limited to Sites to Search across up to 50
distinct domains. Google support remains for existing customers only here; the
provider is retained for compatibility, not recommended for new deployments.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import time
from datetime import datetime, timezone
from typing import Any

BRAVE_ENDPOINT = "https://api.search.brave.com/res/v1/web/search"
GOOGLE_ENDPOINT = "https://www.googleapis.com/customsearch/v1"
PROVIDER_VALUES = {"auto", "brave", "google", "bing"}

_SENSITIVE_QUERY_RE = re.compile(
    r"(?i)([?&](?:key|cx)=)([^&\s]+)"
)


def _redact_search_log_text(value: str) -> str:
    text=_SENSITIVE_QUERY_RE.sub(r"\1[REDACTED]",str(value or ""))
    for env_name in ("BRAVE_SEARCH_API_KEY","GOOGLE_PSE_KEY","GOOGLE_PSE_CX"):
        secret=(os.getenv(env_name) or "").strip()
        if secret:
            text=text.replace(secret,"[REDACTED]")
    return text


class SearchSecretFilter(logging.Filter):
    """Redact search credentials from any HTTP client record that reaches logging."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            rendered=record.getMessage()
            sanitized=_redact_search_log_text(rendered)
            if sanitized != rendered:
                record.msg=sanitized
                record.args=()
        except Exception:
            pass
        return True


_SEARCH_SECRET_FILTER=SearchSecretFilter()


def configure_http_client_logging() -> None:
    """Reduce HTTP client verbosity and attach credential redaction at startup."""
    for name in ("httpx","httpcore"):
        logger=logging.getLogger(name)
        logger.setLevel(logging.WARNING)
        if _SEARCH_SECRET_FILTER not in logger.filters:
            logger.addFilter(_SEARCH_SECRET_FILTER)
    root=logging.getLogger()
    for handler in root.handlers:
        if _SEARCH_SECRET_FILTER not in handler.filters:
            handler.addFilter(_SEARCH_SECRET_FILTER)


configure_http_client_logging()


class SearchProviderError(RuntimeError):
    """Sanitized provider failure that never contains secret values."""


def configured_provider(mode: str | None = None) -> str:
    value=str(mode if mode is not None else os.getenv("NEO_SEARCH_PROVIDER","auto")).strip().lower()
    if value not in PROVIDER_VALUES:
        value="auto"
    brave=bool((os.getenv("BRAVE_SEARCH_API_KEY") or "").strip())
    google=bool((os.getenv("GOOGLE_PSE_KEY") or "").strip() and (os.getenv("GOOGLE_PSE_CX") or "").strip())
    if value=="bing":
        return "bing"
    if value=="brave":
        return "brave" if brave else "bing"
    if value=="google":
        return "google" if google else "bing"
    if brave:
        return "brave"
    if google:
        return "google"
    return "bing"


def new_search_state() -> dict[str, Any]:
    return {
        "day_utc":"",
        "calls_day":0,
        "cycle_id":None,
        "calls_cycle":0,
        "errors":0,
        "fallbacks":0,
        "fallback_reasons":{},
        "last_provider":"bing",
        "last_call_monotonic":0.0,
    }


def normalize_search_state(state: dict | None) -> dict[str, Any]:
    out=new_search_state()
    if isinstance(state,dict):
        for key in out:
            if key in state:
                out[key]=state.get(key)
    for key in ("calls_day","calls_cycle","errors","fallbacks"):
        try:
            out[key]=max(0,int(out.get(key) or 0))
        except Exception:
            out[key]=0
    out["day_utc"]=str(out.get("day_utc") or "")
    out["last_provider"]=str(out.get("last_provider") or "bing")
    out["fallback_reasons"]={
        str(k)[:80]:max(0,int(v or 0))
        for k,v in (out.get("fallback_reasons") or {}).items()
        if str(k).strip()
    } if isinstance(out.get("fallback_reasons"),dict) else {}
    try:
        out["last_call_monotonic"]=float(out.get("last_call_monotonic") or 0.0)
    except Exception:
        out["last_call_monotonic"]=0.0
    return out


def begin_cycle(state: dict | None, cycle_id: int, now: datetime | None = None) -> dict[str, Any]:
    out=normalize_search_state(state)
    now=now or datetime.now(timezone.utc)
    today=now.astimezone(timezone.utc).date().isoformat()
    if out.get("day_utc") != today:
        out["day_utc"]=today
        out["calls_day"]=0
    if out.get("cycle_id") != int(cycle_id):
        out["cycle_id"]=int(cycle_id)
        out["calls_cycle"]=0
        out["errors"]=0
        out["fallbacks"]=0
        out["fallback_reasons"]={}
    return out


def provider_diagnostics(state: dict | None, provider_name: str | None = None) -> dict[str, Any]:
    st=normalize_search_state(state)
    return {
        "name":str(provider_name or st.get("last_provider") or "bing"),
        "calls_cycle":int(st.get("calls_cycle") or 0),
        "calls_day":int(st.get("calls_day") or 0),
        "errors":int(st.get("errors") or 0),
        "fallbacks":int(st.get("fallbacks") or 0),
        "fallback_reasons":dict(sorted((st.get("fallback_reasons") or {}).items())),
    }


def _record_fallback(state: dict[str, Any], reason: str, error: bool = False) -> None:
    reason=str(reason or "fallback")[:80]
    state["fallbacks"]=int(state.get("fallbacks") or 0)+1
    if error:
        state["errors"]=int(state.get("errors") or 0)+1
    reasons=dict(state.get("fallback_reasons") or {})
    reasons[reason]=int(reasons.get(reason) or 0)+1
    state["fallback_reasons"]=reasons


def _budget_available(state: dict[str, Any], max_cycle: int, max_day: int) -> bool:
    return (
        int(state.get("calls_cycle") or 0) < max(0,int(max_cycle))
        and int(state.get("calls_day") or 0) < max(0,int(max_day))
    )


async def search(
    query: str,
    limit: int,
    *,
    state: dict | None = None,
    provider_mode: str | None = None,
    max_calls_cycle: int = 10,
    max_calls_day: int = 150,
    timeout_seconds: float = 6.0,
    http_get: Any = None,
    min_interval_ms: int = 0,
    sleep_fn: Any = asyncio.sleep,
    monotonic_fn: Any = time.monotonic,
) -> tuple[list[dict[str,str]], dict[str,Any], dict[str,Any]]:
    """Search one configured provider with an injected HTTP transport.

    The transport receives endpoint, params, headers and timeout_seconds, and
    returns {"status": int, "json": dict}. This keeps provider logic pure and
    testable without network access.
    """
    st=normalize_search_state(state)
    provider=configured_provider(provider_mode)
    st["last_provider"]=provider
    q=" ".join(str(query or "").split())
    count=max(1,min(int(limit or 1),10))
    if not q:
        return [],st,{"provider":provider,"fallback":True,"reason":"empty_query"}
    if provider=="bing":
        return [],st,{"provider":"bing","fallback":True,"reason":"provider_unconfigured_or_bing"}
    if not _budget_available(st,max_calls_cycle,max_calls_day):
        _record_fallback(st,"budget_exhausted")
        return [],st,{"provider":provider,"fallback":True,"reason":"budget_exhausted"}
    if http_get is None:
        _record_fallback(st,"transport_unavailable",error=True)
        return [],st,{"provider":provider,"fallback":True,"reason":"transport_unavailable"}

    interval=max(0,int(min_interval_ms or 0))/1000.0
    if interval>0:
        last=float(st.get("last_call_monotonic") or 0.0)
        now=float(monotonic_fn())
        remaining=interval-(now-last) if last>0 else 0.0
        if remaining>0:
            await sleep_fn(remaining)
        st["last_call_monotonic"]=float(monotonic_fn())
    st["calls_cycle"]+=1
    st["calls_day"]+=1
    try:
        if provider=="brave":
            key=(os.getenv("BRAVE_SEARCH_API_KEY") or "").strip()
            if not key:
                _record_fallback(st,"not_configured")
                return [],st,{"provider":"brave","fallback":True,"reason":"not_configured"}
            response=await http_get(
                BRAVE_ENDPOINT,
                params={"q":q,"count":count},
                headers={"Accept":"application/json","X-Subscription-Token":key},
                timeout_seconds=max(1.0,min(float(timeout_seconds),10.0)),
            )
            status=int((response or {}).get("status") or 0)
            if status<200 or status>=300:
                raise SearchProviderError("HTTPStatusError:"+str(status))
            data=(response or {}).get("json")
            results=((data.get("web") or {}).get("results") or []) if isinstance(data,dict) else []
            if not isinstance(results,list):
                raise SearchProviderError("unexpected_response_shape")
            rows=[]
            for item in results[:count]:
                if not isinstance(item,dict):
                    continue
                url=str(item.get("url") or "").strip()
                if not url:
                    continue
                rows.append({
                    "title":str(item.get("title") or "")[:300],
                    "url":url,
                    "snippet":str(item.get("description") or "")[:1200],
                    "source":"brave-search",
                })
            return rows,st,{"provider":"brave","fallback":False,"reason":"ok"}

        key=(os.getenv("GOOGLE_PSE_KEY") or "").strip()
        cx=(os.getenv("GOOGLE_PSE_CX") or "").strip()
        if not key or not cx:
            _record_fallback(st,"not_configured")
            return [],st,{"provider":"google","fallback":True,"reason":"not_configured"}
        response=await http_get(
            GOOGLE_ENDPOINT,
            params={"key":key,"cx":cx,"q":q,"num":count},
            headers={"Accept":"application/json"},
            timeout_seconds=max(1.0,min(float(timeout_seconds),10.0)),
        )
        status=int((response or {}).get("status") or 0)
        if status<200 or status>=300:
            raise SearchProviderError("HTTPStatusError:"+str(status))
        data=(response or {}).get("json")
        items=(data.get("items") or []) if isinstance(data,dict) else []
        if not isinstance(items,list):
            raise SearchProviderError("unexpected_response_shape")
        rows=[]
        for item in items[:count]:
            if not isinstance(item,dict):
                continue
            url=str(item.get("link") or "").strip()
            if not url:
                continue
            rows.append({
                "title":str(item.get("title") or "")[:300],
                "url":url,
                "snippet":str(item.get("snippet") or "")[:1200],
                "source":"google-pse",
            })
        return rows,st,{"provider":"google","fallback":False,"reason":"ok"}
    except SearchProviderError as exc:
        reason=str(exc)[:80]
        _record_fallback(st,reason,error=True)
        return [],st,{"provider":provider,"fallback":True,"reason":reason}
    except Exception as exc:
        reason=type(exc).__name__
        _record_fallback(st,reason,error=True)
        return [],st,{"provider":provider,"fallback":True,"reason":reason}


async def search_with_fallback(
    query: str,
    limit: int,
    *,
    bing_search: Any,
    state: dict | None = None,
    provider_mode: str | None = None,
    max_calls_cycle: int = 10,
    max_calls_day: int = 150,
    timeout_seconds: float = 6.0,
    http_get: Any = None,
    min_interval_ms: int = 0,
    sleep_fn: Any = asyncio.sleep,
    monotonic_fn: Any = time.monotonic,
) -> tuple[dict[str,Any], dict[str,Any]]:
    """Run configured provider and use Bing callback only when fallback is required."""
    rows,new_state,meta=await search(
        query,
        limit,
        state=state,
        provider_mode=provider_mode,
        max_calls_cycle=max_calls_cycle,
        max_calls_day=max_calls_day,
        timeout_seconds=timeout_seconds,
        http_get=http_get,
        min_interval_ms=min_interval_ms,
        sleep_fn=sleep_fn,
        monotonic_fn=monotonic_fn,
    )
    if not meta.get("fallback"):
        return {
            "ok":True,
            "query":" ".join(str(query or "").split()),
            "results":rows,
            "count":len(rows),
            "provider":str(meta.get("provider") or "unknown"),
        },new_state
    fallback=await bing_search(query,limit)
    fallback=dict(fallback or {})
    fallback["provider_fallback_from"]=str(meta.get("provider") or "bing")
    fallback["provider_fallback_reason"]=str(meta.get("reason") or "fallback")[:80]
    return fallback,new_state
