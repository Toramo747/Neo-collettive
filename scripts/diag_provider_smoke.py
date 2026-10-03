#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import json
import os
import sys
import traceback
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0,str(ROOT))

from search_providers import begin_cycle as begin_search_provider_cycle
from search_providers import configured_provider, provider_diagnostics
from search_providers import search_with_fallback as provider_search_with_fallback


QUERY = "Python documentation"


def safe_state(value):
    state=dict(value or {})
    # State contains counters/provider metadata only; never print secrets.
    return state


async def main() -> int:
    import cloud_mcp
    env_presence={
        "NEO_SEARCH_PROVIDER": bool((os.getenv("NEO_SEARCH_PROVIDER") or "").strip()),
        "BRAVE_SEARCH_API_KEY": bool((os.getenv("BRAVE_SEARCH_API_KEY") or "").strip()),
        "GOOGLE_PSE_KEY": bool((os.getenv("GOOGLE_PSE_KEY") or "").strip()),
        "GOOGLE_PSE_CX": bool((os.getenv("GOOGLE_PSE_CX") or "").strip()),
    }
    before=safe_state(cloud_mcp.AUTOPILOT_STATE.get("search_provider_state") or {})
    cycle_state=begin_search_provider_cycle(before, 1)
    cloud_mcp.AUTOPILOT_STATE["search_provider_state"]=cycle_state
    provider=configured_provider(cloud_mcp.SEARCH_PROVIDER_MODE)

    report={
        "query":QUERY,
        "env_presence":env_presence,
        "configured_provider":provider,
        "state_before":before,
        "state_after_begin_cycle":safe_state(cycle_state),
    }

    try:
        result,new_state=await provider_search_with_fallback(
            QUERY,
            5,
            bing_search=cloud_mcp._bing_rss_search,
            state=cloud_mcp.AUTOPILOT_STATE.get("search_provider_state") or {},
            provider_mode=cloud_mcp.SEARCH_PROVIDER_MODE,
            max_calls_cycle=cloud_mcp.SEARCH_MAX_CALLS_PER_CYCLE,
            max_calls_day=cloud_mcp.SEARCH_MAX_CALLS_PER_DAY,
            timeout_seconds=min(cloud_mcp.TIMEOUT,6),
            http_get=cloud_mcp._provider_http_get,
            min_interval_ms=0,
        )
        cloud_mcp.AUTOPILOT_STATE["search_provider_state"]=new_state
        report.update({
            "result_count":len(result.get("results") or []),
            "result_ok":bool(result.get("ok")),
            "result_provider":result.get("provider"),
            "provider_fallback_from":result.get("provider_fallback_from"),
            "provider_fallback_reason":result.get("provider_fallback_reason"),
            "state_after_call":safe_state(new_state),
            "provider_diagnostics":provider_diagnostics(new_state,provider),
        })
    except Exception as exc:
        report.update({
            "exception_type":type(exc).__name__,
            "state_after_call":safe_state(cloud_mcp.AUTOPILOT_STATE.get("search_provider_state") or {}),
        })

    print(json.dumps(report,indent=2,sort_keys=True))
    return 0


def production_smoke() -> int:
    """One fixed-query smoke on the running service; counters only, no evidence ingest."""
    import urllib.request
    from self_traffic_auth import make_self_traffic_proof
    token=os.getenv('NEO_HEARTBEAT_TOKEN','')
    if not token:
        print(json.dumps({'scope':'render-production','error':'heartbeat_secret_missing'}))
        return 1
    def request(path,payload=None):
        headers={'X-MYCELIX-Self-Traffic':'github-actions-heartbeat',
                 'X-MYCELIX-Self-Traffic-Proof':make_self_traffic_proof(token,path),
                 'Accept':'application/json, text/event-stream',
                 'Content-Type':'application/json','MCP-Protocol-Version':'2025-03-26'}
        data=json.dumps(payload).encode() if payload is not None else None
        req=urllib.request.Request('https://neo-collettive.onrender.com'+path,data=data,headers=headers)
        with urllib.request.urlopen(req,timeout=20) as response:
            return json.load(response)
    def counters():
        d=request('/api/autonomy/status')
        ap=d.get('autopilot') or {}
        st=ap.get('search_provider_state') or {}
        return {k:st.get(k) for k in ('calls_cycle','calls_day','errors','fallbacks','last_provider')}
    report={'scope':'render-production','fixed_query':QUERY,'queries_requested':1,
            'evidence_ingest':False,'uses_render_credentials':True}
    try:
        report['before']=counters()
        initialized=request('/mcp',{'jsonrpc':'2.0','id':1,'method':'initialize','params':{
            'protocolVersion':'2025-03-26','capabilities':{},
            'clientInfo':{'name':'osixbay-provider-smoke','version':'1'}}})
        if initialized.get('error'):
            report['error']='initialize_rejected'
        else:
            reply=request('/mcp',{'jsonrpc':'2.0','id':2,'method':'tools/call','params':{
                'name':'neo_web_search','arguments':{'query':QUERY,'limit':3}}})
            result=reply.get('result') or {}
            parsed={}
            for item in result.get('content') or []:
                if item.get('type')=='text':
                    try:
                        candidate=json.loads(item.get('text') or '')
                        if isinstance(candidate,dict):parsed=candidate
                    except (ValueError,TypeError):pass
            report.update({'result_ok':bool(parsed.get('ok')),
                           'result_count':len(parsed.get('results') or []),
                           'result_provider':parsed.get('provider'),
                           'tool_error':bool(result.get('isError') or reply.get('error')),
                           'fallback_used':bool(parsed.get('provider_fallback_from'))})
    except Exception as exc:
        report['error']=type(exc).__name__
        # Deliberately omit exception text, URLs, response rows and auth headers.
    try:report['after']=counters()
    except Exception as exc:report['after_error']=type(exc).__name__
    print(json.dumps(report,sort_keys=True))
    return 0


if __name__=="__main__":
    raise SystemExit(production_smoke() if '--production' in sys.argv else asyncio.run(main()))
