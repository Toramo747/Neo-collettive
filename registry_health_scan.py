# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Andrea Gava
"""Two-phase GitHub Actions runner for the MCP Registry Health Report."""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

import mcp_endpoint_verifier as verifier
from registry_health import (
    HOST_REQUEST_DELAY_SECONDS,
    MAX_CONCURRENCY,
    PER_HOST_CONCURRENCY,
    aggregate_dataset,
    classify_verification,
    dataset_csv,
    fetch_complete_registry,
    final_category,
    is_opted_out,
    read_opt_out,
    render_report,
    render_social_draft,
)

DATA_ROOT = Path("data/registry-health")
MIN_SECOND_PROBE_SECONDS = 6 * 60 * 60


def runtime_version() -> str:
    source=Path("cloud_mcp.py").read_text(encoding="utf-8")
    match=re.search(r'^VERSION = "([^"]+)"',source,re.M)
    if not match:
        raise RuntimeError("VERSION_not_found")
    return match.group(1)


def scanner_user_agent() -> str:
    return (
        "MYCELIX-RegistryHealth/"
        + runtime_version()
        + " (+https://neo-collettive.onrender.com/registry-health/about)"
    )


def parse_utc(value: str) -> datetime:
    return datetime.fromisoformat(str(value).replace("Z","+00:00")).astimezone(timezone.utc)


def compact_probe(result: dict[str, Any], category: str) -> dict[str, Any]:
    checks=result.get("checks") if isinstance(result.get("checks"),dict) else {}
    summary=result.get("summary") if isinstance(result.get("summary"),dict) else {}
    init=checks.get("initialize") if isinstance(checks.get("initialize"),dict) else {}
    http=checks.get("http") if isinstance(checks.get("http"),dict) else {}
    tls=checks.get("tls") if isinstance(checks.get("tls"),dict) else {}
    return {
        "timestamp": result.get("timestamp"),
        "category": category,
        "http_status": init.get("http_status") or http.get("status"),
        "summary": {
            "protocol_version": summary.get("protocol_version"),
            "tool_count": int(summary.get("tool_count") or 0),
            "valid_input_schemas": int(summary.get("valid_input_schemas") or 0),
            "invalid_input_schemas": int(summary.get("invalid_input_schemas") or 0),
            "discovery_present": summary.get("discovery_present") is True,
            "total_observed_latency_ms": summary.get("total_observed_latency_ms"),
        },
        "checks": {
            "tls": {
                "ok": tls.get("ok") is True,
                "error": tls.get("error"),
            },
            "initialize": {
                "ok": init.get("ok") is True,
                "http_status": init.get("http_status"),
            },
        },
        "errors": [str(x) for x in (result.get("errors") or [])],
        "request_counts_by_host": {
            str(k):int(v or 0) for k,v in (result.get("request_counts_by_host") or {}).items()
        },
        "read_only": result.get("read_only") is True,
        "remote_tools_called": result.get("remote_tools_called") is True,
        "credentials_forwarded": result.get("credentials_forwarded") is True,
        "usage_scope": result.get("usage_scope"),
    }


async def run_probe(
    server: dict[str, Any],
    *,
    pacer: verifier.RequestPacer,
    task_sem: asyncio.Semaphore,
    user_agent: str,
) -> dict[str, Any]:
    remote=(server.get("remotes") or [{}])[0]
    url=str(remote.get("url") or "")
    async with task_sem:
        result=await verifier.verify_endpoint(
            url=url,
            caller="registry-health:"+str(server.get("name") or ""),
            client_version=runtime_version(),
            usage_scope="internal_registry_health",
            user_agent=user_agent,
            request_pacer=pacer,
            enforce_rate_limit=False,
        )
    category=classify_verification(result)
    return compact_probe(result,category)


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2,sort_keys=False)+"\n",encoding="utf-8")


def latest_scan_dir() -> Path:
    candidates=[
        p for p in DATA_ROOT.iterdir()
        if p.is_dir() and re.fullmatch(r"\d{4}-\d{2}-\d{2}",p.name)
        and (p/"scan-state.json").exists()
    ] if DATA_ROOT.exists() else []
    if not candidates:
        raise RuntimeError("no_prior_registry_health_scan")
    return sorted(candidates)[-1]


def _request_count(rows: list[dict[str, Any]]) -> dict[str,int]:
    out: dict[str,int]={}
    for row in rows:
        for key in ("probe1","probe2"):
            probe=row.get(key)
            if not isinstance(probe,dict):
                continue
            for host,count in (probe.get("request_counts_by_host") or {}).items():
                out[str(host)]=out.get(str(host),0)+int(count or 0)
    return dict(sorted(out.items()))


async def first_phase() -> Path:
    started=time.monotonic()
    started_utc=datetime.now(timezone.utc)
    ua=scanner_user_agent()
    timeout=httpx.Timeout(connect=5.0,read=12.0,write=8.0,pool=5.0)
    async with httpx.AsyncClient(
        timeout=timeout,
        follow_redirects=False,
        trust_env=False,
        headers={"User-Agent":ua,"Accept":"application/json"},
    ) as client:
        listing=await fetch_complete_registry(client)

    day=started_utc.date().isoformat()
    outdir=DATA_ROOT/day
    optouts=read_opt_out()
    pacer=verifier.RequestPacer(
        max_concurrency=MAX_CONCURRENCY,
        per_host=PER_HOST_CONCURRENCY,
        min_host_interval=HOST_REQUEST_DELAY_SECONDS,
    )
    task_sem=asyncio.Semaphore(MAX_CONCURRENCY)

    remote_servers=[x for x in listing["servers"] if x.get("access_class")=="remote"]
    rows: list[dict[str,Any]]=[]
    tasks=[]
    task_servers=[]
    for server in remote_servers:
        opted=is_opted_out(server,optouts)
        base={
            "name":server["name"],
            "version":server.get("version"),
            "remote_url":((server.get("remotes") or [{}])[0].get("url")),
            "remote_urls":[x.get("url") for x in (server.get("remotes") or [])],
            "opted_out":opted,
            "probe1":None,
            "probe2":None,
            "category":None,
            "final":False,
        }
        rows.append(base)
        if not opted:
            task_servers.append((base,server))
            tasks.append(run_probe(server,pacer=pacer,task_sem=task_sem,user_agent=ua))

    results=await asyncio.gather(*tasks,return_exceptions=True)
    for (base,_server),result in zip(task_servers,results):
        if isinstance(result,Exception):
            probe={
                "timestamp":datetime.now(timezone.utc).isoformat(),
                "category":"UNREACHABLE",
                "http_status":None,
                "summary":{},
                "checks":{},
                "errors":[type(result).__name__+":"+str(result)[:240]],
                "request_counts_by_host":{},
                "usage_scope":"internal_registry_health",
            }
        else:
            probe=result
        base["probe1"]=probe
        base["category"]=probe["category"]
        if probe["category"] in {"OK","AUTH_REQUIRED"}:
            base["final"]=True

    elapsed=round(time.monotonic()-started,2)
    aggregate=aggregate_dataset(listing,rows)
    aggregate.update({
        "phase":"first",
        "final":False,
        "started_at_utc":started_utc.isoformat(),
        "finished_at_utc":datetime.now(timezone.utc).isoformat(),
        "duration_seconds":elapsed,
        "second_probe_not_before_utc":(
            datetime.fromtimestamp(started_utc.timestamp()+MIN_SECOND_PROBE_SECONDS,timezone.utc).isoformat()
        ),
        "requests_by_host":_request_count(rows),
        "internal_verifier_metrics":verifier.internal_usage_metrics_snapshot(),
        "external_verifier_metrics":verifier.usage_metrics_snapshot(),
    })

    state={
        "phase":"first",
        "scan_date":day,
        "snapshot_at_utc":listing["snapshot_at_utc"],
        "first_probe_started_at_utc":started_utc.isoformat(),
        "second_probe_not_before_utc":aggregate["second_probe_not_before_utc"],
        "final":False,
    }
    _write_json(outdir/"registry-snapshot.json",listing)
    _write_json(outdir/"registry-health.json",{"listing":listing,"remote_results":rows})
    (outdir/"registry-health.csv").write_text(dataset_csv(rows),encoding="utf-8")
    _write_json(outdir/"summary.json",aggregate)
    _write_json(outdir/"scan-state.json",state)
    _write_json(DATA_ROOT/"latest-summary.json",aggregate)
    _write_json(DATA_ROOT/"latest-servers.json",{"generated_at_utc":aggregate["generated_at_utc"],"servers":rows})
    print(json.dumps({"outdir":str(outdir),"summary":aggregate,"report_status":"pending_second_probe"},ensure_ascii=False))
    return outdir


async def second_phase(scan_dir: Path | None = None) -> Path:
    started=time.monotonic()
    started_utc=datetime.now(timezone.utc)
    outdir=scan_dir or latest_scan_dir()
    state=json.loads((outdir/"scan-state.json").read_text(encoding="utf-8"))
    not_before=parse_utc(state["second_probe_not_before_utc"])
    if started_utc < not_before:
        remaining=int((not_before-started_utc).total_seconds())
        raise RuntimeError("second_probe_too_early_seconds="+str(remaining))

    payload=json.loads((outdir/"registry-health.json").read_text(encoding="utf-8"))
    listing=payload["listing"]
    rows=payload["remote_results"]
    by_name={x["name"]:x for x in listing["servers"]}
    ua=scanner_user_agent()
    pacer=verifier.RequestPacer(
        max_concurrency=MAX_CONCURRENCY,
        per_host=PER_HOST_CONCURRENCY,
        min_host_interval=HOST_REQUEST_DELAY_SECONDS,
    )
    task_sem=asyncio.Semaphore(MAX_CONCURRENCY)
    tasks=[]
    task_rows=[]
    for row in rows:
        first=row.get("probe1") if isinstance(row.get("probe1"),dict) else {}
        if row.get("opted_out") or first.get("category") in {"OK","AUTH_REQUIRED"}:
            row["category"]=first.get("category") if first else None
            row["final"]=True
            continue
        server=by_name.get(row.get("name"))
        if not isinstance(server,dict):
            continue
        task_rows.append((row,server))
        tasks.append(run_probe(server,pacer=pacer,task_sem=task_sem,user_agent=ua))

    results=await asyncio.gather(*tasks,return_exceptions=True)
    for (row,_server),result in zip(task_rows,results):
        if isinstance(result,Exception):
            probe={
                "timestamp":datetime.now(timezone.utc).isoformat(),
                "category":"UNREACHABLE",
                "http_status":None,
                "summary":{},
                "checks":{},
                "errors":[type(result).__name__+":"+str(result)[:240]],
                "request_counts_by_host":{},
                "usage_scope":"internal_registry_health",
            }
        else:
            probe=result
        row["probe2"]=probe
        row["category"]=final_category(row["probe1"],probe)
        row["final"]=True

    aggregate=aggregate_dataset(listing,rows)
    aggregate.update({
        "phase":"second",
        "final":True,
        "started_at_utc":state["first_probe_started_at_utc"],
        "finished_at_utc":datetime.now(timezone.utc).isoformat(),
        "second_probe_started_at_utc":started_utc.isoformat(),
        "duration_seconds_second_probe":round(time.monotonic()-started,2),
        "requests_by_host":_request_count(rows),
        "internal_verifier_metrics":verifier.internal_usage_metrics_snapshot(),
        "external_verifier_metrics":verifier.usage_metrics_snapshot(),
    })
    state.update({
        "phase":"second",
        "second_probe_started_at_utc":started_utc.isoformat(),
        "final":True,
    })
    _write_json(outdir/"registry-health.json",{"listing":listing,"remote_results":rows})
    (outdir/"registry-health.csv").write_text(dataset_csv(rows),encoding="utf-8")
    _write_json(outdir/"summary.json",aggregate)
    _write_json(outdir/"scan-state.json",state)
    _write_json(DATA_ROOT/"latest-summary.json",aggregate)
    _write_json(DATA_ROOT/"latest-servers.json",{"generated_at_utc":aggregate["generated_at_utc"],"servers":rows})
    month=outdir.name[:7]
    report_path=Path("docs/reports")/(month+"-mcp-registry-health.md")
    social_path=Path("docs/reports")/(month+"-mcp-registry-health-social-draft.md")
    report_path.parent.mkdir(parents=True,exist_ok=True)
    report_path.write_text(render_report(aggregate,outdir.name),encoding="utf-8")
    social_path.write_text(render_social_draft(aggregate,outdir.name),encoding="utf-8")
    print(json.dumps({"outdir":str(outdir),"summary":aggregate,"report":str(report_path),"social":str(social_path)},ensure_ascii=False))
    return outdir


async def main() -> int:
    parser=argparse.ArgumentParser()
    parser.add_argument("phase",choices=("first","second"))
    parser.add_argument("--scan-date",default="")
    args=parser.parse_args()
    if args.phase=="first":
        await first_phase()
    else:
        scan_dir=DATA_ROOT/args.scan_date if args.scan_date else None
        await second_phase(scan_dir)
    return 0


if __name__=="__main__":
    raise SystemExit(asyncio.run(main()))
