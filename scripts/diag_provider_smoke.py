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

import cloud_mcp
from search_providers import begin_cycle as begin_search_provider_cycle
from search_providers import configured_provider, provider_diagnostics
from search_providers import search_with_fallback as provider_search_with_fallback


QUERY = "Python documentation"


def safe_state(value):
    state=dict(value or {})
    # State contains counters/provider metadata only; never print secrets.
    return state


async def main() -> int:
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
            "exception_message":str(exc)[:500],
            "traceback":traceback.format_exc(limit=3),
            "state_after_call":safe_state(cloud_mcp.AUTOPILOT_STATE.get("search_provider_state") or {}),
        })

    print(json.dumps(report,indent=2,sort_keys=True))
    return 0


if __name__=="__main__":
    raise SystemExit(asyncio.run(main()))
