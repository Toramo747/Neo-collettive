# SPDX-License-Identifier: BUSL-1.1
"""Scan private checkpoint history and emit aggregate counts/hashes only."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import subprocess
import sys


def evidence_count(payload) -> int:
    if not isinstance(payload,dict):
        return 0
    value=payload.get("commercial_evidence_memory")
    if isinstance(value,list):
        return sum(1 for row in value if isinstance(row,dict))
    if isinstance(value,dict):
        return max(0,int(value.get("evidence_count") or 0))
    return 0


def main(root: str) -> int:
    repo=Path(root)
    path="runtime-checkpoints/runtime-backup.json"
    proc=subprocess.run(
        ["git","-C",str(repo),"log","--all","--format=%H","--",path],
        check=True,capture_output=True,text=True,
    )
    commits=[line.strip() for line in proc.stdout.splitlines() if line.strip()]
    out=[]
    seen=set()
    for commit in commits[:100]:
        show=subprocess.run(
            ["git","-C",str(repo),"show",f"{commit}:{path}"],
            capture_output=True,
        )
        if show.returncode!=0:
            continue
        raw=show.stdout
        try:
            payload=json.loads(raw.decode("utf-8"))
        except Exception:
            continue
        digest=hashlib.sha256(raw).hexdigest()
        key=(digest,evidence_count(payload))
        if key in seen:
            continue
        seen.add(key)
        out.append({
            "commit":commit,
            "sha256":digest,
            "rows":evidence_count(payload),
            "cycles_completed":max(0,int(payload.get("cycles_completed") or 0)) if isinstance(payload,dict) else 0,
            "state_saved_at_utc":payload.get("state_saved_at_utc") if isinstance(payload,dict) else None,
        })
    print(json.dumps({"copies":out,"max_rows":max([x["rows"] for x in out] or [0])},separators=(",",":"),sort_keys=True))
    return 0


if __name__=="__main__":
    raise SystemExit(main(sys.argv[1]))
