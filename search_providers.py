"""Optional paid search providers for MYCELIX public research.

Secrets are read only from environment variables. They are never returned,
persisted, logged, or interpolated into error messages.

Official provider contracts implemented:
- Brave Search API: GET https://api.search.brave.com/res/v1/web/search
  header X-Subscription-Token, query params q/count.
- Google Programmable Search JSON API:
  GET https://www.googleapis.com/customsearch/v1
  query params key/cx/q/num.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

BRAVE_ENDPOINT = "https://api.search.brave.com/res/v1/web/search"
GOOGLE_ENDPOINT = "https://www.googleapis.com/customsearch/v1"
PROVIDER_VALUES = {"auto", "brave", "google", "bing"}


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
        "last_provider":"bing",
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
    return out


def provider_diagnostics(state: dict | None, provider_name: str | None = None) -> dict[str, Any]:
    st=normalize_search_state(state)
    return {
        "name":str(provider_name or st.get("last_provider") or "bing"),
        "calls_cycle":int(st.get("calls_cycle") or 0),
        "calls_day":int(st.get("calls_day") or 0),
        "errors":int(st.get("errors") or 0),
        "fallbacks":int(st.get("fallbacks") or 0),
    }


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
        st["fallbacks"]+=1
        return [],st,{"provider":provider,"fallback":True,"reason":"budget_exhausted"}
    if http_get is None:
        st["errors"]+=1
        st["fallbacks"]+=1
        return [],st,{"provider":provider,"fallback":True,"reason":"transport_unavailable"}

    st["calls_cycle"]+=1
    st["calls_day"]+=1
    try:
        if provider=="brave":
            key=(os.getenv("BRAVE_SEARCH_API_KEY") or "").strip()
            if not key:
                st["fallbacks"]+=1
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
            st["fallbacks"]+=1
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
        st["errors"]+=1
        st["fallbacks"]+=1
        return [],st,{"provider":provider,"fallback":True,"reason":str(exc)[:80]}
    except Exception as exc:
        st["errors"]+=1
        st["fallbacks"]+=1
        return [],st,{"provider":provider,"fallback":True,"reason":type(exc).__name__}
