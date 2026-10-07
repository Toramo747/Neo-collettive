# SPDX-License-Identifier: BUSL-1.1
"""Aggregate-only diagnosis for commercial evidence memory repair."""
from __future__ import annotations

import base64
from datetime import datetime
import hashlib
import json
import lzma
import os
from pathlib import Path
import sys
import urllib.parse
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from state_codec import decode_checkpoint

API = "https://api.render.com/v1"
SERVICE = os.getenv("RENDER_SERVICE_ID", "srv-dampj8bm8hqs73ac0an0").strip()
TOKEN = os.environ["RENDER_API_KEY"].strip()


def request(url: str):
    req = urllib.request.Request(url, headers={"Authorization": "Bearer " + TOKEN, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=45) as response:
        raw = response.read(32 * 1024 * 1024 + 1)
    if len(raw) > 32 * 1024 * 1024:
        raise ValueError("response_too_large")
    return json.loads(raw.decode("utf-8"))


def list_env() -> dict[str, str]:
    out = {}
    cursor = None
    while True:
        params={"limit":"100"}
        if cursor:
            params["cursor"]=cursor
        page=request(f"{API}/services/{SERVICE}/env-vars?"+urllib.parse.urlencode(params))
        if not isinstance(page,list):
            raise ValueError("invalid_env_list")
        if not page:
            break
        for wrapper in page:
            env=wrapper.get("envVar") if isinstance(wrapper,dict) and isinstance(wrapper.get("envVar"),dict) else wrapper
            if not isinstance(env,dict) or not isinstance(env.get("key"),str) or not isinstance(env.get("value"),str):
                raise ValueError("invalid_env_row")
            out[env["key"]]=env["value"]
        if len(page)<100:
            break
        cursor=str(page[-1].get("cursor") or "")
        if not cursor:
            raise ValueError("pagination_cursor_missing")
    return out


def decode_xz_chunks(values: list[str]) -> list[dict]:
    encoded="".join(values)
    if not encoded.startswith("xz64:"):
        raise ValueError("invalid_store_encoding")
    raw=lzma.decompress(base64.b64decode(encoded[5:],validate=True))
    rows=json.loads(raw.decode("utf-8"))
    if not isinstance(rows,list):
        raise ValueError("invalid_store_rows")
    return [row for row in rows if isinstance(row,dict)]


def valid_epoch(value) -> bool:
    try:
        return float(value)>0
    except Exception:
        return False


def stats(rows: list[dict]) -> dict:
    missing_last=sum(1 for row in rows if not valid_epoch(row.get("last_seen_epoch")))
    missing_first=sum(1 for row in rows if not valid_epoch(row.get("first_seen_epoch")))
    repaired=sum(1 for row in rows if bool(row.get("timestamp_repaired")))
    valid_last=[float(row.get("last_seen_epoch")) for row in rows if valid_epoch(row.get("last_seen_epoch"))]
    return {
        "rows":len(rows),
        "valid_last_seen":len(valid_last),
        "missing_last_seen":missing_last,
        "missing_first_seen":missing_first,
        "timestamp_repaired":repaired,
        "min_last_seen_epoch":min(valid_last) if valid_last else None,
        "max_last_seen_epoch":max(valid_last) if valid_last else None,
    }


def main() -> int:
    env=list_env()
    checkpoint=decode_checkpoint(env["NEO_STATE_JSON"])
    memory=checkpoint.get("commercial_evidence_memory") if isinstance(checkpoint,dict) else None
    checkpoint_kind="list" if isinstance(memory,list) else "reference" if isinstance(memory,dict) else "other"
    checkpoint_rows=[row for row in memory if isinstance(row,dict)] if isinstance(memory,list) else []

    groups={}
    for key,value in env.items():
        if key.startswith("BACKUP_"):
            continue
        if key.startswith("NEO_EVIDENCE_ARCHIVE_"):
            stem=key.rsplit("_",1)[0]
            groups.setdefault(("archive",stem),[]).append((int(key.rsplit("_",1)[1]),value))
        elif key.startswith("NEO_EVIDENCE_"):
            stem=key.rsplit("_",1)[0]
            groups.setdefault(("active",stem),[]).append((int(key.rsplit("_",1)[1]),value))
        elif key.startswith("NEO_COMMERCIAL_EVIDENCE_"):
            groups.setdefault(("legacy","NEO_COMMERCIAL_EVIDENCE"),[]).append((int(key.rsplit("_",1)[1]),value))

    generation_stats=[]
    for (kind,stem),parts in sorted(groups.items()):
        parts.sort()
        rows=decode_xz_chunks([value for _,value in parts])
        row=stats(rows)
        row.update({
            "kind":kind,
            "generation":stem.split("_")[-1] if kind!="legacy" else "legacy",
            "sha256":hashlib.sha256(json.dumps(rows,ensure_ascii=False,separators=(",",":"),sort_keys=False).encode()).hexdigest(),
        })
        generation_stats.append(row)

    backup_manifests=[]
    for key,value in env.items():
        if key.startswith("BACKUP_") and key.endswith("_MANIFEST"):
            try:
                manifest=json.loads(value)
                backup_manifests.append({
                    "key":key,
                    "created_at_utc":manifest.get("created_at_utc"),
                    "checkpoint_rows":((manifest.get("checkpoint") or {}).get("rows")),
                    "runtime_rows":((manifest.get("runtime") or {}).get("rows")),
                    "source_env_count":manifest.get("source_env_count"),
                })
            except Exception:
                pass

    def ref_summary(ref):
        if not isinstance(ref,dict):
            return None
        out={
            "store_mode":ref.get("store_mode"),
            "store":ref.get("store"),
            "generation":ref.get("generation"),
            "sha256":ref.get("sha256"),
            "evidence_count":int(ref.get("evidence_count") or 0),
            "chunk_count":int(ref.get("chunk_count") or 0),
        }
        previous=ref.get("previous_generation")
        if isinstance(previous,dict):
            out["previous_generation"]=ref_summary(previous)
        return out

    report={
        "checkpoint":{
            "kind":checkpoint_kind,
            "rows_declared":len(checkpoint_rows) if checkpoint_kind=="list" else int((memory or {}).get("evidence_count") or 0) if isinstance(memory,dict) else 0,
            **(stats(checkpoint_rows) if checkpoint_rows else {}),
            "reference":ref_summary(memory) if isinstance(memory,dict) else None,
            "store_reference":ref_summary(checkpoint.get("commercial_evidence_store_reference")) if isinstance(checkpoint,dict) else None,
            "archive_reference":ref_summary(checkpoint.get("commercial_evidence_archive_reference")) if isinstance(checkpoint,dict) else None,
            "cycles_completed":int(checkpoint.get("cycles_completed") or 0) if isinstance(checkpoint,dict) else 0,
            "state_saved_at_utc":checkpoint.get("state_saved_at_utc") if isinstance(checkpoint,dict) else None,
        },
        "generations":generation_stats,
        "backup_manifests":backup_manifests,
    }
    print(json.dumps(report,separators=(",",":"),sort_keys=True))
    return 0


if __name__=="__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(json.dumps({"ok":False,"reason":type(exc).__name__},separators=(",",":")))
        raise SystemExit(1)
