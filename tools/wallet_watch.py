#!/usr/bin/env python3
"""Watch-only: incoming USDC on Base to OSIXBAY's receiving address (24/10, Andrea's OK). Never sends anything.

The address lives only in the private archive (common/wallet/address.txt); it is public on chain but we do not
publish it. This reads public USDC Transfer logs from a public Base RPC and appends each incoming transfer to
common/wallet/incoming.jsonl in the private archive. Logs print counts only, never amounts or addresses.

  python tools/wallet_watch.py <private_dir>
There is no key anywhere in this code or its inputs: it cannot move funds.
"""
from __future__ import annotations

import json
import re
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

RPCS = ("https://base-rpc.publicnode.com", "https://mainnet.base.org", "https://base.drpc.org")  # public, keyless
USDC = "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913"  # USDC on Base (6 decimals)
TRANSFER = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
CHUNK = 2000            # blocks per eth_getLogs call (public RPC limits the range)
FIRST_LOOKBACK = 2000   # about an hour of Base blocks on the very first run


def rpc(method: str, params: list, call=None):
    if call:
        return call(method, params)
    import time
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
    last = None
    for attempt in range(6):  # rotate public endpoints, back off on 429 and errors
        url = RPCS[attempt % len(RPCS)]
        try:
            req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json", "User-Agent": "neo-wallet-watch"})
            with urllib.request.urlopen(req, timeout=30) as r:
                d = json.loads(r.read().decode())
            if "error" in d:
                raise RuntimeError(str(d["error"])[:200])
            time.sleep(0.5)
            return d["result"]
        except Exception as e:
            last = e
            time.sleep(2 * (attempt + 1))
    raise last


def watch(private_dir: str, call=None, max_chunks: int = 60) -> int:
    w = Path(private_dir) / "common" / "wallet"
    addr = (w / "address.txt").read_text().strip().lower()
    if not re.fullmatch(r"0x[0-9a-f]{40}", addr):
        print("::error title=wallet watch::address.txt is not an address")
        return 1
    state_p, out_p = w / "state.json", w / "incoming.jsonl"
    state = json.loads(state_p.read_text()) if state_p.exists() else {}
    head = int(rpc("eth_blockNumber", [], call), 16)
    start = int(state.get("next_block") or head - FIRST_LOOKBACK)
    seen = {json.loads(l)["id"] for l in out_p.read_text().splitlines() if l.strip()} if out_p.exists() else set()
    topic_to = "0x" + "0" * 24 + addr[2:]
    new, frm = [], start
    for _ in range(max_chunks):
        if frm > head:
            break
        to = min(frm + CHUNK - 1, head)
        logs = rpc("eth_getLogs", [{"address": USDC, "topics": [TRANSFER, None, topic_to],
                                    "fromBlock": hex(frm), "toBlock": hex(to)}], call)
        for lg in logs:
            lid = f"{lg['transactionHash']}:{int(lg['logIndex'], 16)}"
            if lid in seen:
                continue
            seen.add(lid)
            new.append({"id": lid, "tx": lg["transactionHash"], "block": int(lg["blockNumber"], 16),
                        "from": "0x" + lg["topics"][1][-40:], "amount_usdc": int(lg["data"], 16) / 1e6,
                        "seen_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")})
        frm = to + 1
    w.mkdir(parents=True, exist_ok=True)
    if new:
        with out_p.open("a") as fh:
            for r in new:
                fh.write(json.dumps(r, sort_keys=True) + "\n")
    state_p.write_text(json.dumps({"next_block": frm, "checked_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds")}))
    behind = head - frm + 1
    print(f"::notice title=wallet watch::new incoming transfers={len(new)} total={len(seen)}" + (f" (still {behind} blocks to scan)" if behind > 0 else ""))
    return 0


if __name__ == "__main__":
    if len(sys.argv) == 2:
        try:
            sys.exit(watch(sys.argv[1]))
        except Exception as e:  # the message never contains the address: RPC errors and HTTP codes only
            msg = re.sub(r"0x[0-9a-fA-F]{40}", "0x…", str(e))[:240]
            print(f"::error title=wallet watch::{type(e).__name__}: {msg}")
            sys.exit(1)
    print(__doc__)
    sys.exit(2)
