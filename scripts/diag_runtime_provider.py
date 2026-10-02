#!/usr/bin/env python3
from __future__ import annotations
import asyncio, json

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

URL="https://neo-collettive.onrender.com/mcp"

async def call_tool(name,args=None):
    async with streamable_http_client(URL) as (read,write,_):
        async with ClientSession(read,write) as session:
            await session.initialize()
            result=await session.call_tool(name,args or {})
            payload=[]
            for item in result.content or []:
                text=getattr(item,"text",None)
                if text:
                    try: payload.append(json.loads(text))
                    except Exception: payload.append(text)
            return payload

async def main():
    out={}
    for name,args in [
        ("neo_director_results",{"limit":1}),
        ("neo_render_status",{}),
    ]:
        try:
            out[name]=await call_tool(name,args)
        except Exception as exc:
            out[name]={"error":type(exc).__name__,"detail":str(exc)[:300]}
    print(json.dumps(out,indent=2,ensure_ascii=False))

if __name__=="__main__":
    asyncio.run(main())
