# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Andrea Gava
"""Two-phase GitHub Actions runner for the MCP Registry Health Report."""
from __future__ import annotations

import argparse
import asyncio
import json
import random
import re
import secrets
import subprocess
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
PROBE_WALL_TIMEOUT_SECONDS = 45
CHECKPOINT_EVERY_COMPLETIONS = 20
CHECKPOINT_PUBLISH_ENV = "REGISTRY_HEALTH_PUBLISH_CHECKPOINTS"
SCOPE_FULL = "FULL"
SCOPE_SAMPLE = "SAMPLE"
DEFAULT_SAMPLE_MINUTES = 30


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
        result=await asyncio.wait_for(
            verifier.verify_endpoint(
                url=url,
                caller="registry-health:"+str(server.get("name") or ""),
                client_version=runtime_version(),
                usage_scope="internal_registry_health",
                user_agent=user_agent,
                request_pacer=pacer,
                enforce_rate_limit=False,
            ),
            timeout=PROBE_WALL_TIMEOUT_SECONDS,
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


def _publish_progress_checkpoint(outdir: Path, state: dict[str, Any]) -> None:
    """Persist an IN_PROGRESS checkpoint to main so runner timeout does not erase it."""
    import os
    if str(os.getenv(CHECKPOINT_PUBLISH_ENV) or "").strip() != "1":
        return
    subprocess.run(["git","config","user.name","MYCELIX Registry Health"],check=True)
    subprocess.run(["git","config","user.email","actions@users.noreply.github.com"],check=True)
    subprocess.run(["git","add",str(outdir)],check=True)
    if subprocess.run(["git","diff","--cached","--quiet"]).returncode == 0:
        return
    completed=int(state.get("completed_probes") or 0)
    total=int(state.get("total_probes") or 0)
    subprocess.run([
        "git","commit","-m",
        f"registry health checkpoint: {completed}/{total} {outdir.name} [skip render]",
    ],check=True)
    for attempt in range(1,4):
        subprocess.run(["git","fetch","origin","main"],check=True)
        rebased=subprocess.run(["git","rebase","origin/main"]).returncode == 0
        if rebased and subprocess.run(["git","push","origin","HEAD:main"]).returncode == 0:
            return
        subprocess.run(["git","rebase","--abort"],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        time.sleep(attempt*3)
    raise RuntimeError("registry_health_checkpoint_publish_failed")


def _write_first_progress_checkpoint(
    outdir: Path,
    listing: dict[str, Any],
    rows: list[dict[str, Any]],
    state: dict[str, Any],
) -> None:
    """Persist resumable first-pass progress without publishing it as latest/final."""
    _write_json(outdir/"registry-snapshot.json",listing)
    _write_json(outdir/"registry-health.json",{"listing":listing,"remote_results":rows})
    (outdir/"registry-health.csv").write_text(dataset_csv(rows),encoding="utf-8")
    _write_json(outdir/"scan-state.json",state)
    _publish_progress_checkpoint(outdir,state)


def _sample_budget_seconds(max_minutes: int) -> int:
    """Return the hard wall-clock budget for a sample run."""
    return max(60, min(int(max_minutes) * 60, 6 * 60 * 60))


def _sample_order(remote_servers: list[dict[str, Any]], seed: int) -> list[dict[str, Any]]:
    """Deterministically randomize Registry remotes from a recorded seed."""
    items=list(remote_servers)
    random.Random(int(seed)).shuffle(items)
    return items


async def first_phase(mode: str = "full", max_minutes: int = DEFAULT_SAMPLE_MINUTES) -> Path:
    started=time.monotonic()
    started_utc=datetime.now(timezone.utc)
    mode=str(mode or "full").strip().lower()
    if mode not in {"full","sample"}:
        raise ValueError("invalid_scan_mode")
    scope=SCOPE_SAMPLE if mode=="sample" else SCOPE_FULL
    sample_seed=secrets.randbits(63) if scope==SCOPE_SAMPLE else None
    budget_seconds=_sample_budget_seconds(max_minutes) if scope==SCOPE_SAMPLE else None
    deadline=(started+budget_seconds) if budget_seconds is not None else None

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
    candidates=_sample_order(remote_servers,sample_seed) if scope==SCOPE_SAMPLE else list(remote_servers)
    rows: list[dict[str,Any]]=[]
    completed=0
    attempted=0
    stopped_reason="registry_exhausted"

    state={
        "phase":"first",
        "status":"IN_PROGRESS",
        "scope":scope,
        "scan_date":day,
        "snapshot_at_utc":listing["snapshot_at_utc"],
        "first_probe_started_at_utc":started_utc.isoformat(),
        "second_probe_not_before_utc":(
            datetime.fromtimestamp(started_utc.timestamp()+MIN_SECOND_PROBE_SECONDS,timezone.utc).isoformat()
        ),
        "completed_probes":0,
        "total_probes":len(candidates) if scope==SCOPE_FULL else None,
        "sample_seed":sample_seed,
        "sample_server_names":[],
        "sample_size":0,
        "max_minutes":int(max_minutes) if scope==SCOPE_SAMPLE else None,
        "final":False,
    }
    _write_first_progress_checkpoint(outdir,listing,rows,state)

    def make_base(server: dict[str,Any]) -> dict[str,Any]:
        opted=is_opted_out(server,optouts)
        return {
            "name":server["name"],
            "version":server.get("version"),
            "remote_url":((server.get("remotes") or [{}])[0].get("url")),
            "remote_urls":[x.get("url") for x in (server.get("remotes") or [])],
            "opted_out":opted,
            "probe1":None,
            "probe2":None,
            "category":None,
            "final":bool(opted),
        }

    idx=0
    while idx < len(candidates):
        if deadline is not None and time.monotonic() >= deadline:
            stopped_reason="max_minutes_reached"
            break

        batch=[]
        while idx < len(candidates) and len(batch) < MAX_CONCURRENCY:
            if deadline is not None and time.monotonic() >= deadline:
                stopped_reason="max_minutes_reached"
                break
            server=candidates[idx]
            idx+=1
            attempted+=1
            base=make_base(server)
            if base["opted_out"]:
                rows.append(base)
                state["sample_server_names"]=[x["name"] for x in rows]
                state["sample_size"]=len(rows)
                continue
            task=asyncio.create_task(run_probe(server,pacer=pacer,task_sem=task_sem,user_agent=ua))
            batch.append((task,base))

        if not batch:
            if stopped_reason=="max_minutes_reached":
                break
            continue

        task_map={task:base for task,base in batch}
        wait_timeout=None if deadline is None else max(0.0,deadline-time.monotonic())
        done,pending=await asyncio.wait(set(task_map),timeout=wait_timeout)
        if pending:
            stopped_reason="max_minutes_reached"
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending,return_exceptions=True)

        for task in done:
            base=task_map[task]
            try:
                result=task.result()
            except Exception as exc:
                result=exc
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
            rows.append(base)
            completed+=1

        state["completed_probes"]=completed
        state["sample_server_names"]=[x["name"] for x in rows]
        state["sample_size"]=len(rows)
        if completed and (completed % CHECKPOINT_EVERY_COMPLETIONS == 0 or pending):
            state["checkpointed_at_utc"]=datetime.now(timezone.utc).isoformat()
            _write_first_progress_checkpoint(outdir,listing,rows,state)
        if pending:
            break

    elapsed=round(time.monotonic()-started,2)
    aggregate=aggregate_dataset(listing,rows)
    aggregate.update({
        "phase":"first",
        "status":"FIRST_PASS",
        "scope":scope,
        "final":False,
        "started_at_utc":started_utc.isoformat(),
        "finished_at_utc":datetime.now(timezone.utc).isoformat(),
        "duration_seconds":elapsed,
        "max_minutes":int(max_minutes) if scope==SCOPE_SAMPLE else None,
        "stopped_reason":stopped_reason,
        "sample_seed":sample_seed,
        "sample_size":len(rows),
        "sample_server_names":[x["name"] for x in rows],
        "sample_population_remote_count":len(remote_servers) if scope==SCOPE_SAMPLE else None,
        "attempted_servers":attempted,
        "second_probe_not_before_utc":(
            datetime.fromtimestamp(started_utc.timestamp()+MIN_SECOND_PROBE_SECONDS,timezone.utc).isoformat()
        ),
        "requests_by_host":_request_count(rows),
        "internal_verifier_metrics":verifier.internal_usage_metrics_snapshot(),
        "external_verifier_metrics":verifier.usage_metrics_snapshot(),
    })

    state.update({
        "phase":"first",
        "status":"FIRST_PASS",
        "scope":scope,
        "second_probe_not_before_utc":aggregate["second_probe_not_before_utc"],
        "completed_probes":completed,
        "sample_server_names":aggregate["sample_server_names"],
        "sample_size":len(rows),
        "stopped_reason":stopped_reason,
        "checkpointed_at_utc":datetime.now(timezone.utc).isoformat(),
        "final":False,
    })
    _write_json(outdir/"registry-snapshot.json",listing)
    _write_json(outdir/"registry-health.json",{"listing":listing,"remote_results":rows})
    (outdir/"registry-health.csv").write_text(dataset_csv(rows),encoding="utf-8")
    _write_json(outdir/"summary.json",aggregate)
    _write_json(outdir/"scan-state.json",state)
    _write_json(DATA_ROOT/"latest-summary.json",aggregate)
    _write_json(DATA_ROOT/"latest-servers.json",{
        "generated_at_utc":aggregate["generated_at_utc"],
        "scope":scope,
        "sample_seed":sample_seed,
        "sample_server_names":aggregate["sample_server_names"],
        "servers":rows,
    })
    print(json.dumps({
        "outdir":str(outdir),
        "summary":aggregate,
        "report_status":"pending_second_probe",
    },ensure_ascii=False))
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
    scope=str(state.get("scope") or SCOPE_FULL)
    sample_names=list(state.get("sample_server_names") or [])
    if scope==SCOPE_SAMPLE:
        row_names=[str(x.get("name") or "") for x in rows]
        if row_names != sample_names:
            raise RuntimeError("sample_membership_changed_before_second_probe")
    aggregate.update({
        "phase":"second",
        "status":"FINAL",
        "scope":scope,
        "final":True,
        "started_at_utc":state["first_probe_started_at_utc"],
        "finished_at_utc":datetime.now(timezone.utc).isoformat(),
        "second_probe_started_at_utc":started_utc.isoformat(),
        "duration_seconds_second_probe":round(time.monotonic()-started,2),
        "sample_seed":state.get("sample_seed"),
        "sample_size":len(rows) if scope==SCOPE_SAMPLE else None,
        "sample_server_names":sample_names if scope==SCOPE_SAMPLE else [],
        "sample_population_remote_count":state.get("sample_population_remote_count"),
        "requests_by_host":_request_count(rows),
        "internal_verifier_metrics":verifier.internal_usage_metrics_snapshot(),
        "external_verifier_metrics":verifier.usage_metrics_snapshot(),
    })
    state.update({
        "phase":"second",
        "status":"FINAL",
        "second_probe_started_at_utc":started_utc.isoformat(),
        "final":True,
    })
    _write_json(outdir/"registry-health.json",{"listing":listing,"remote_results":rows})
    (outdir/"registry-health.csv").write_text(dataset_csv(rows),encoding="utf-8")
    _write_json(outdir/"summary.json",aggregate)
    _write_json(outdir/"scan-state.json",state)
    _write_json(DATA_ROOT/"latest-summary.json",aggregate)
    _write_json(DATA_ROOT/"latest-servers.json",{
        "generated_at_utc":aggregate["generated_at_utc"],
        "scope":aggregate.get("scope"),
        "sample_seed":aggregate.get("sample_seed"),
        "sample_server_names":aggregate.get("sample_server_names") or [],
        "servers":rows,
    })
    month=outdir.name[:7]
    report_path=Path("docs/reports")/(month+"-mcp-registry-health.md")
    social_path=Path("docs/reports")/(month+"-mcp-registry-health-social-draft.md")
    report_path.parent.mkdir(parents=True,exist_ok=True)
    report_path.write_text(render_report(aggregate,outdir.name),encoding="utf-8")
    social_path.write_text(render_social_draft(aggregate,outdir.name),encoding="utf-8")
    print(json.dumps({"outdir":str(outdir),"summary":aggregate,"report":str(report_path),"social":str(social_path)},ensure_ascii=False))
    return outdir


def persistence_contract(scan_dir: Path, *, require_final: bool = False) -> dict[str, Any]:
    """Validate the on-disk contract that the workflow must commit."""
    required=(
        scan_dir/"registry-snapshot.json",
        scan_dir/"registry-health.json",
        scan_dir/"registry-health.csv",
        scan_dir/"summary.json",
        scan_dir/"scan-state.json",
        DATA_ROOT/"latest-summary.json",
        DATA_ROOT/"latest-servers.json",
    )
    missing=[str(p) for p in required if not p.exists() or p.stat().st_size <= 0]
    if missing:
        raise RuntimeError("registry_health_persistence_missing:"+",".join(missing))
    summary=json.loads((scan_dir/"summary.json").read_text(encoding="utf-8"))
    latest=json.loads((DATA_ROOT/"latest-summary.json").read_text(encoding="utf-8"))
    servers=json.loads((DATA_ROOT/"latest-servers.json").read_text(encoding="utf-8"))
    state=json.loads((scan_dir/"scan-state.json").read_text(encoding="utf-8"))
    if str(state.get("scan_date") or "") != scan_dir.name:
        raise RuntimeError("registry_health_scan_date_mismatch")
    if summary.get("generated_at_utc") != latest.get("generated_at_utc"):
        raise RuntimeError("registry_health_latest_summary_not_updated")
    rows=servers.get("servers")
    if not isinstance(rows,list):
        raise RuntimeError("registry_health_latest_servers_missing")
    if require_final and (summary.get("final") is not True or state.get("final") is not True):
        raise RuntimeError("registry_health_final_scan_required")
    return {
        "scan_dir":str(scan_dir),
        "phase":summary.get("phase"),
        "final":summary.get("final") is True,
        "servers_total":summary.get("servers_total"),
        "scanned":summary.get("scanned"),
        "latest_summary":str(DATA_ROOT/"latest-summary.json"),
        "latest_servers":str(DATA_ROOT/"latest-servers.json"),
    }


async def main() -> int:
    parser=argparse.ArgumentParser()
    parser.add_argument("phase",choices=("first","second"))
    parser.add_argument("--scan-date",default="")
    parser.add_argument("--mode",choices=("full","sample"),default="full")
    parser.add_argument("--max-minutes",type=int,default=DEFAULT_SAMPLE_MINUTES)
    args=parser.parse_args()
    if args.phase=="first":
        await first_phase(args.mode,args.max_minutes)
    else:
        scan_dir=DATA_ROOT/args.scan_date if args.scan_date else None
        await second_phase(scan_dir)
    return 0


if __name__=="__main__":
    raise SystemExit(asyncio.run(main()))
