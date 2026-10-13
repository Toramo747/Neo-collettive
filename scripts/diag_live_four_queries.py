#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0,str(ROOT))

import cloud_mcp


QUERIES = [
    ("pricing","project management software pricing"),
    ("hn","manual reporting automation"),
    ("github","manual data entry automation"),
    ("stackexchange","automate repetitive spreadsheet workflow"),
]


def summarize(label: str, result: dict, query: str) -> dict:
    rows=[x for x in (result.get("results") or []) if isinstance(x,dict)]
    passed=0
    sources=set()
    for row in rows:
        sources.add(str(row.get("source") or label))
        rel=row.get("query_relevance")
        if isinstance(rel,dict):
            if rel.get("relevant"):
                passed+=1
        else:
            calc=cloud_mcp.query_relevance(
                str(row.get("title") or ""),
                str(row.get("snippet") or ""),
                query,
                {},
            )
            if calc.get("relevant"):
                passed+=1
    return {
        "status":"ok" if result.get("ok",True) else "error",
        "count":len(rows),
        "source":sorted(sources) or [label],
        "relevance_pass":passed,
    }


async def main() -> int:
    out=[]
    for label,query in QUERIES:
        if label=="pricing":
            result=await cloud_mcp.free_web_search(query,4)
        elif label=="hn":
            rows=await cloud_mcp._hn_query_search(query,4)
            result={"ok":True,"results":rows}
        elif label=="github":
            rows=await cloud_mcp._github_issue_query_search(query,4)
            result={"ok":True,"results":rows}
        else:
            rows=await cloud_mcp._stackexchange_query_search(query,4,{})
            result={"ok":True,"results":rows}
        out.append({"query_type":label,**summarize(label,result,query)})
    print(json.dumps({"read_only":True,"results":out},indent=2,sort_keys=True))
    return 0


if __name__=="__main__":
    raise SystemExit(asyncio.run(main()))
