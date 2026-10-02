#!/usr/bin/env python3
from __future__ import annotations

import json
import urllib.request

URL="https://neo-collettive.onrender.com/api/autonomy/status"

with urllib.request.urlopen(URL,timeout=30) as response:
    data=json.load(response)

latest=data.get("latest_result") if isinstance(data,dict) else {}
latest=latest if isinstance(latest,dict) else {}
quality=latest.get("evidence_quality") if isinstance(latest.get("evidence_quality"),dict) else {}
ing=quality.get("ingestion_diagnostics") if isinstance(quality.get("ingestion_diagnostics"),dict) else {}
strategy=latest.get("search_strategy") if isinstance(latest.get("search_strategy"),dict) else {}
web=latest.get("web_research") if isinstance(latest.get("web_research"),list) else []
provider=ing.get("search_provider") if isinstance(ing.get("search_provider"),dict) else {}
funnel=ing.get("funnel") if isinstance(ing.get("funnel"),dict) else {}

out={
    "cycles_completed":((data.get("autopilot") or {}).get("cycles_completed")),
    "last_finished_utc":((data.get("autopilot") or {}).get("last_finished_utc")),
    "latest_status":latest.get("status"),
    "ingestion_enabled":ing.get("enabled"),
    "ingestion_keys":sorted(str(k) for k in ing.keys()),
    "planned_query_count":strategy.get("planned_query_count"),
    "web_research_groups":len(web),
    "web_source_count":latest.get("web_source_count"),
    "provider":{
        "name":provider.get("name"),
        "configured_provider":provider.get("configured_provider"),
        "provider_key_present":provider.get("provider_key_present"),
        "calls_cycle":provider.get("calls_cycle"),
        "calls_day":provider.get("calls_day"),
        "fallbacks":provider.get("fallbacks"),
    },
    "funnel":{
        "queries_planned":funnel.get("queries_planned"),
        "queries_executed":funnel.get("queries_executed"),
        "raw_received":funnel.get("raw_received"),
        "deduped":funnel.get("deduped"),
        "query_relevant":funnel.get("query_relevant"),
        "family_matched":funnel.get("family_matched"),
        "buyer_voice":funnel.get("buyer_voice"),
        "commercial_signal":funnel.get("commercial_signal"),
        "persisted":funnel.get("persisted"),
    },
}
print(json.dumps(out,indent=2,sort_keys=True))
