# SPDX-License-Identifier: BUSL-1.1
"""Zero-cost, evidence-only evaluation of the MCP liveness/conformance Tool Opportunity."""
from __future__ import annotations

import asyncio
import html
import json
import re
import socket
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import httpx

from tool_opportunity import analyze_tool_opportunities

OUT=Path("runtime/mcp-liveness-tool-opportunity.json")
AION_NEEDS="https://aion-agent-core-live.onrender.com/needs"
MCP_REGISTRY="https://registry.modelcontextprotocol.io/v0.1/servers"
PATHWREN_CARD="https://www.pathwren.workers.dev/a2a/score/.well-known/agent-card.json"
COMPOSIO_PRICING="https://composio.dev/pricing"
PORTKEY_PRICING="https://portkey.ai/pricing"
CASPER_ID="io.github.magiautonomous/casper-tools"


def clean_html(value: str) -> str:
    return " ".join(html.unescape(re.sub(r"<[^>]+>"," ",value or "")).split())


def around(text: str, needles: list[str], radius: int=700) -> str:
    low=text.lower()
    parts=[]
    for needle in needles:
        p=low.find(needle.lower())
        if p>=0:
            parts.append(text[max(0,p-radius):p+radius])
    return " ".join(parts)[:5000]


async def fetch(client: httpx.AsyncClient, url: str, **kwargs):
    try:
        r=await client.get(url,**kwargs)
        return {"ok":True,"status":r.status_code,"url":str(r.url),"text":r.text[:400000],"headers":dict(r.headers)}
    except Exception as exc:
        return {"ok":False,"url":url,"error":type(exc).__name__+":"+str(exc)[:300]}


async def pathwren_score(client: httpx.AsyncClient, target: str) -> dict:
    body={
        "jsonrpc":"2.0","id":"mcp-rel-score","method":"message/send",
        "params":{"message":{"role":"ROLE_USER","messageId":"mcp-rel-score-msg","parts":[
            {"text":json.dumps({"skill":"score_card","url":target})}
        ]}},
    }
    try:
        r=await client.post("https://www.pathwren.workers.dev/a2a/score",headers={"Content-Type":"application/json","Accept":"application/json"},json=body)
        return {"ok":r.is_success,"status":r.status_code,"body":r.json() if "json" in (r.headers.get("content-type") or "") else {"raw":r.text[:20000]}}
    except Exception as exc:
        return {"ok":False,"error":type(exc).__name__+":"+str(exc)[:300]}


async def main() -> int:
    observed=datetime.now(timezone.utc).isoformat()
    async with httpx.AsyncClient(timeout=30,follow_redirects=True,headers={"User-Agent":"MYCELIX-zero-cost-market-verifier/1.0"}) as client:
        needs,registry,pwcard,composio,portkey=await asyncio.gather(
            fetch(client,AION_NEEDS),
            fetch(client,MCP_REGISTRY,params={"search":CASPER_ID,"limit":10}),
            fetch(client,PATHWREN_CARD),
            fetch(client,COMPOSIO_PRICING),
            fetch(client,PORTKEY_PRICING),
        )

        need1=None
        if needs.get("ok") and needs.get("status")==200:
            try:
                for row in json.loads(needs["text"]):
                    if int(row.get("id") or 0)==1:
                        need1=row
                        break
            except Exception:
                pass

        registry_rows=[]
        remote_urls=[]
        if registry.get("ok") and registry.get("status")==200:
            try:
                data=json.loads(registry["text"])
                registry_rows=data.get("servers") or data.get("results") or data if isinstance(data,list) else []
            except Exception:
                registry_rows=[]
        for row in registry_rows if isinstance(registry_rows,list) else []:
            blob=json.dumps(row,ensure_ascii=False)
            if CASPER_ID not in blob:
                continue
            for match in re.findall(r'https://[^"\\s]+',blob):
                if "registry.modelcontextprotocol.io" not in match:
                    remote_urls.append(match.rstrip('",}'))

        liveness=[]
        for url in list(dict.fromkeys(remote_urls))[:6]:
            parsed=urlparse(url)
            if parsed.scheme!="https" or not parsed.hostname:
                liveness.append({"url":url,"live":False,"reason":"invalid_or_non_https"})
                continue
            try:
                socket.getaddrinfo(parsed.hostname,443)
            except Exception as exc:
                liveness.append({"url":url,"live":False,"reason":"dns_unresolved:"+type(exc).__name__})
                continue
            try:
                rr=await client.get(url,timeout=10,follow_redirects=False)
                liveness.append({"url":url,"live":True,"status":rr.status_code})
            except Exception as exc:
                liveness.append({"url":url,"live":False,"reason":"connect_failed:"+type(exc).__name__})

        pw=await pathwren_score(client,"https://neo-collettive.onrender.com/mcp")

    # Build URL-grounded observations for the existing gate. No synthetic payment claims.
    scouts=[]
    if need1:
        scouts.append({
            "family":"mcp_reliability",
            "title":"MAGI open need: MCP discovery and matching research",
            "text":str(need1.get("description") or ""),
            "url":AION_NEEDS,
            "date":observed,
            "source":"aion-public-needs",
        })
    if registry_rows:
        bad=[x for x in liveness if not x.get("live")]
        if bad:
            scouts.append({
                "family":"mcp_reliability",
                "title":"MCP registry listing has broken or unreachable public endpoint",
                "text":"broken unreachable endpoint observed by DNS/connectivity probe for registry-listed casper-tools; registry presence does not prove liveness",
                "url":"https://registry.modelcontextprotocol.io/",
                "date":observed,
                "source":"mcp-registry-runtime-probe",
            })
    if pwcard.get("ok"):
        scouts.append({
            "family":"mcp_reliability",
            "title":"Pathwren MCP Endpoint Score Card",
            "text":"MCP conformance and endpoint monitoring score card; independent read-only verification surface",
            "url":PATHWREN_CARD,
            "date":observed,
            "source":"external-verifier",
        })

    groups=[]
    meta={}
    for query,url,result,vendor,expected_price in [
        ('"MCP server monitoring" pricing subscription',COMPOSIO_PRICING,composio,"Composio","$29"),
        ('"MCP endpoint monitoring" pricing subscription',PORTKEY_PRICING,portkey,"Portkey","$49"),
    ]:
        key=" ".join(query.split()).lower()
        meta[key]={"family":"mcp_reliability","role":"tool_pricing"}
        rows=[]
        if result.get("ok") and int(result.get("status") or 0)==200:
            text=clean_html(result.get("text") or "")
            low=text.lower()
            # Pricing pages are seller evidence only. Keep their text factual and
            # neutral so vendor marketing copy can never masquerade as buyer pain.
            if expected_price.lower() in low and "mcp" in low:
                rows.append({
                    "title":f"{vendor} official MCP-related pricing {expected_price}/month",
                    "url":url,
                    "snippet":f"{vendor} official pricing page contains MCP support and a {expected_price}/month paid plan.",
                    "source":"official-pricing",
                    "vendor":vendor,
                })
        groups.append({"query":query,"results":rows})

    analysis=analyze_tool_opportunities(groups,scouts,[],meta,observed)
    all_rows=[]
    # top5 may exclude zero-score families; reconstruct the requested row by running
    # with the evidence above and locating the registered family in the sorted output
    # exposed through council/top5 when competitive enough.
    for row in analysis.get("top5") or []:
        if row.get("family")=="mcp_reliability":
            all_rows.append(row)
    requested=all_rows[0] if all_rows else {
        "type":"TOOL_OPPORTUNITY","family":"mcp_reliability",
        "title":"MCP Registry Liveness & Conformance Verifier",
        "gate_pass":False,
        "monetization_score":0,
        "missing":["not_in_top5_after_current_evidence"],
    }

    report={
        "observed_at_utc":observed,
        "cost_usd":0,
        "payment_performed":False,
        "gate_rule":analysis.get("gate_rule"),
        "thesis":requested,
        "evidence":{
            "aion_need_id_1":need1,
            "casper_registry_rows":registry_rows[:5] if isinstance(registry_rows,list) else [],
            "casper_endpoint_liveness":liveness,
            "pathwren_control":pw,
            "competitor_pricing":[
                {"vendor":"Composio","url":COMPOSIO_PRICING,"http_status":composio.get("status")},
                {"vendor":"Portkey","url":PORTKEY_PRICING,"http_status":portkey.get("status")},
            ],
        },
    }
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(report,ensure_ascii=False,indent=2))
    return 0


if __name__=="__main__":
    raise SystemExit(asyncio.run(main()))
