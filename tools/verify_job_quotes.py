"""Check job results with neo's live verify_quote tool (signed receipts).

usage: verify_job_quotes.py <private_dir>
Reads  <private_dir>/common/verify_job_queue.json   [{"id","url","quote"}]
Writes <private_dir>/common/verify_job_results.json  {id: signed verify_quote result}
Calls carry the signed smoke proof, so they are not counted as outside demand.
The log prints outcomes and signature checks only (no URLs, no quotes).
"""
from __future__ import annotations

import json
import os
import re
import sys
import urllib.request
from pathlib import Path

from receipt_signing import verify_receipt
from self_traffic_auth import make_self_traffic_proof

BASE = "https://neo-collettive.onrender.com"


def call(payload: dict) -> dict:
    proof = make_self_traffic_proof(os.environ["SMOKE_SECRET"], "/mcp-smoke")
    req = urllib.request.Request(BASE + "/mcp", data=json.dumps(payload).encode(), method="POST", headers={
        "Content-Type": "application/json", "Accept": "application/json, text/event-stream",
        "X-MYCELIX-Smoke-Proof": proof})
    with urllib.request.urlopen(req, timeout=90) as r:
        raw = r.read().decode("utf-8", "replace")
    m = re.search(r"^data: (.*)$", raw, re.M)
    return json.loads(m.group(1) if m else raw)


def structured(d: dict) -> dict:
    res = d.get("result") or {}
    sc = res.get("structuredContent") or {}
    if not sc:
        for c in res.get("content") or []:
            try:
                return json.loads(c.get("text") or "{}")
            except Exception:
                pass
    return sc


def main(private: str) -> None:
    root = Path(private) / "common"
    queue = json.loads((root / "verify_job_queue.json").read_text())
    out_path = root / "verify_job_results.json"
    done = json.loads(out_path.read_text()) if out_path.exists() else {}
    with urllib.request.urlopen(BASE + "/.well-known/agent-card.json", timeout=60) as r:
        card = json.loads(r.read().decode())
    pub = (card.get("receipt_signing") or {}).get("public_key_b64", "")
    call({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
        "protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "verify-job-quotes", "version": "1"}}})
    n = 2
    for item in queue:
        if item["id"] in done:
            continue
        sc = structured(call({"jsonrpc": "2.0", "id": n, "method": "tools/call", "params": {
            "name": "verify_quote", "arguments": {"url": item["url"], "quote": item["quote"]}}}))
        n += 1
        ok = bool(sc.get("signature")) and verify_receipt(sc, pub)
        done[item["id"]] = sc
        print(f"::notice title=verify_quote job result::outcome={sc.get('outcome')} error={sc.get('error')} "
              f"signature_verified={ok} version={card.get('version')}")
    out_path.write_text(json.dumps(done, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main(sys.argv[1])
