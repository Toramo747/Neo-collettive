# SPDX-License-Identifier: BUSL-1.1
"""Post-deploy live probe for verify_mcp_endpoint. Zero-cost, read-only."""
from __future__ import annotations

import asyncio
import json
import random
from pathlib import Path

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

MYCELIX_MCP="https://neo-collettive.onrender.com/mcp"
REGISTRY="https://registry.modelcontextprotocol.io/v0.1/servers"
CASPER="io.github.magiautonomous/casper-tools"
OUT=Path("runtime/verify-mcp-endpoint-live.json")


def _rows(payload):
    if isinstance(payload,list):
        return payload
    if isinstance(payload,dict):
        for key in ("servers","results","items"):
            if isinstance(payload.get(key),list):
                return payload[key]
    return []


def _server(row):
    if isinstance(row,dict) and isinstance(row.get("server"),dict):
        return row["server"]
    return row if isinstance(row,dict) else {}


def _remote(server):
    for r in server.get("remotes") or []:
        if isinstance(r,dict) and str(r.get("type") or "").lower()=="streamable-http":
            url=str(r.get("url") or "").strip()
            if url.startswith("https://"):
                return url
    return None


def _result_dict(result):
    structured=getattr(result,"structuredContent",None)
    if isinstance(structured,dict):
        return structured
    structured=getattr(result,"structured_content",None)
    if isinstance(structured,dict):
        return structured
    for item in getattr(result,"content",[]) or []:
        text=getattr(item,"text",None)
        if text:
            try:
                data=json.loads(text)
                if isinstance(data,dict):
                    return data
            except Exception:
                continue
    return {"ok":False,"error":"tool_result_not_machine_readable"}


async def main():
    async with httpx.AsyncClient(timeout=30,follow_redirects=False) as web:
        r=await web.get(REGISTRY,params={"limit":100})
        r.raise_for_status()
        payload=r.json()
    candidates=[]
    seen=set()
    for row in _rows(payload):
        srv=_server(row)
        name=str(srv.get("name") or "")
        url=_remote(srv)
        if not name or not url or name in {CASPER,"io.github.Toramo747/mycelix"}:
            continue
        if name in seen:
            continue
        seen.add(name)
        candidates.append({"name":name,"url":url})
    if len(candidates)<5:
        raise SystemExit(f"registry yielded only {len(candidates)} usable remote servers")
    chosen=random.SystemRandom().sample(candidates,5)

    requests=[
        {"label":"MYCELIX","arguments":{"url":MYCELIX_MCP}},
        {"label":"casper-tools","arguments":{"registry_name":CASPER}},
    ] + [
        {"label":x["name"],"arguments":{"registry_name":x["name"]}}
        for x in chosen
    ]

    report={"mycelix_mcp":MYCELIX_MCP,"random_registry_peers":chosen,"results":[]}
    async with streamable_http_client(MYCELIX_MCP,headers={"X-MYCELIX-Self-Traffic":"github-actions-verify-mcp-live"}) as streams:
        read,write=streams[0],streams[1]
        async with ClientSession(read,write) as session:
            await session.initialize()
            for req in requests:
                try:
                    result=await session.call_tool("verify_mcp_endpoint",req["arguments"])
                    data=_result_dict(result)
                except Exception as exc:
                    data={"ok":False,"live":False,"error":type(exc).__name__+":"+str(exc)[:300]}
                report["results"].append({"label":req["label"],"arguments":req["arguments"],"result":data})
                await asyncio.sleep(1)

    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(report,ensure_ascii=False,indent=2))


if __name__=="__main__":
    asyncio.run(main())
