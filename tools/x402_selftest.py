#!/usr/bin/env python3
"""First real paid calls to neo's x402 routes (24/10, Andrea's OK). Runs once inside a GitHub runner.

A throwaway wallet is created in memory (key written only to the runner's temp dir, never printed or committed);
its address goes to the private archive so Andrea can send 0.05 USDC on Base to it. Then five paid calls at 0.01 USDC,
each only if the 402 asks exactly 10000 units to Andrea's address. The money ends on Andrea's address.
"""
import asyncio, base64, json, os, sys, time, urllib.request
from pathlib import Path

PAY_TO = "0x6a5715db03888ca96904754b8b7932483b92dd97"  # 25/10: self-custody wallet
BASE = "https://neo-collettive.onrender.com"
USDC = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"
RPCS = ["https://base-rpc.publicnode.com", "https://mainnet.base.org", "https://base.drpc.org"]
CALLS = [  # 25/10 (Andrea's OK): one paid call per service not yet in the CDP Bazaar, 2.08 USDC in all
    ("injection-scan", {"text": "Quarterly update: revenue grew 4% in Q3. The full table is on the next page."}),
    ("x402-lint", {"url": "https://neo-collettive.onrender.com/x402/timestamp", "method": "POST"}),
    ("delivery-receipt-verify", {"receipt": json.loads(r'''{"v": "0.1", "type": "x402-delivery-receipt", "seller": {"name": "example-seller", "key_id": "ed25519:example", "key_url": "https://seller.example/.well-known/agent-card.json"}, "buyer_request_id": "buyer-req-0001", "route": {"method": "GET", "url": "https://seller.example/api/funding?symbol=BTCUSDT"}, "request_sha256": "920f38c33a54a5e260a43e8eb51723171307ae17856216f664ea72148e8626ef", "payment_required": {"body_sha256": "f5210dd524b72143dba43d42037179283ec6c081b90e8a3713f29489a7ac9bd6", "header_sha256": "781cad1414cb7f3da9c7bae96d5ce5d8af34a8953be804524ed35465cfca7be1", "body_x402_version": 2, "header_x402_version": 2}, "payment": {"network": "eip155:8453", "asset": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913", "amount": "2000", "pay_to_requested": "0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", "payer_seen": "0xbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb", "facilitator": "example-facilitator", "facilitator_wallet": "0xdddddddddddddddddddddddddddddddddddddddd", "tx": "0xcccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc"}, "outcome": "delivered", "refusal_code": null, "charged": true, "settlement": {"kind": "onchain"}, "times": {"response_sent_utc": "2026-10-23T10:12:17.622Z", "settlement_seen_utc": "2026-10-23T10:12:21.000Z", "settlement_block_time_utc": "2026-10-23T10:12:21Z"}, "response_sha256": "4c337ae59f81e2b7a3303746932f19689ce3b532348d56856bcdc7faffbb10ec", "log": {"name": "example-seller-receipts", "seq": 42, "prev": "0000000000000000000000000000000000000000000000000000000000000000"}, "signature": "xY5sSiKb1boZyMJP-wt_Im0p6EbgWfqysUZQwsacGwbo2alR6iDOWYDxsoMYr29k8thif2f7qMjqHGgqr0zyAA", "hops": []}'''), "seller_public_key_b64": "k17Nv+rU8+/0vpadOXmVySvs4Ufx9YFchl72Ynl/DDY="}),
    ("citation-check", {"answer": "A hash chain is the successive application of a cryptographic hash function to a piece of data (https://en.wikipedia.org/wiki/Hash_chain).",
                        "citations": [{"url": "https://en.wikipedia.org/wiki/Hash_chain", "quote": "A hash chain is the successive application of a cryptographic hash function to a piece of data."}]}),
    ("mcp-audit", {"url": "https://mcp.deepwiki.com/mcp"}),
]
WANT = {"injection-scan": "10000", "x402-lint": "10000", "delivery-receipt-verify": "10000", "citation-check": "50000", "mcp-audit": "2000000"}


def rpc(method, params):
    for u in RPCS:
        try:
            d = json.loads(urllib.request.urlopen(urllib.request.Request(u, data=json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode(),
                                                                        headers={"Content-Type": "application/json", "User-Agent": "neo-x402-selftest"}), timeout=20).read())
            return d["result"]
        except Exception as e:
            print(f"::warning title=rpc::{u}: {type(e).__name__} {str(e)[:120]}")
            time.sleep(2)
    raise RuntimeError("rpc")


def usdc_balance(addr):
    data = "0x70a08231" + "0" * 24 + addr[2:].lower()
    return int(rpc("eth_call", [{"to": USDC, "data": data}, "latest"]), 16)


def create(keyfile, out):
    from eth_account import Account
    a = Account.create()
    Path(keyfile).write_text(a.key.hex())
    os.chmod(keyfile, 0o600)
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    Path(out).write_text(a.address + "\n")
    print("::notice title=selftest::wallet created; address saved to the private archive")


async def run_all(out_addr, report):
    """24/10 fix: the address is published only after everything needed to spend it has been checked."""
    import subprocess
    from eth_account import Account
    from x402 import x402Client
    from x402.http.clients import x402_httpx_transport  # noqa: F401  (import check)
    from x402.mechanisms.evm.exact.register import register_exact_evm_client
    acct = Account.create()
    usdc_balance(acct.address)                       # the RPC answers
    register_exact_evm_client(x402Client(), acct)    # the client builds
    urllib.request.urlopen(urllib.request.Request(BASE + "/x402", headers={"User-Agent": "neo-x402-selftest"}), timeout=60).read()
    keyfile = os.path.join(os.environ.get("RUNNER_TEMP", "/tmp"), "k")
    Path(keyfile).write_text(acct.key.hex())
    os.chmod(keyfile, 0o600)
    Path(out_addr).parent.mkdir(parents=True, exist_ok=True)
    Path(out_addr).write_text(acct.address + "\n")
    repo = str(Path(out_addr).parents[2])
    for cmd in (["git", "-C", repo, "add", "common/x402/selftest-address.txt"], ["git", "-C", repo, "commit", "-qm", "ops: x402 self-test address (private)"]):
        subprocess.run(cmd, check=True)
    for _ in range(3):
        if subprocess.run(["git", "-C", repo, "pull", "-q", "--rebase"]).returncode == 0 and subprocess.run(["git", "-C", repo, "push", "-q"]).returncode == 0:
            break
        time.sleep(5)
    print("::notice title=selftest::checks passed; address published to the private archive; waiting for funds")
    return await pay(keyfile, report)


async def pay(keyfile, report):
    import httpx
    from eth_account import Account
    from x402 import x402Client
    from x402.http.clients import x402_httpx_transport
    from x402.mechanisms.evm.exact.register import register_exact_evm_client
    acct = Account.from_key(Path(keyfile).read_text().strip())
    deadline = time.time() + 50 * 60
    while usdc_balance(acct.address) < 2080000:
        if time.time() > deadline:
            print("::warning title=selftest::no funds after 40 min, nothing paid")
            return 0
        await asyncio.sleep(20)
    await asyncio.sleep(30)  # let the whole transfer land before spending
    print(f"::notice title=selftest::funded with {usdc_balance(acct.address) / 1e6} USDC")
    client = register_exact_evm_client(x402Client(), acct)
    card = json.loads(urllib.request.urlopen(BASE + "/.well-known/agent-card.json", timeout=60).read())
    pub = (card.get("receipt_signing") or {}).get("public_key_b64", "")
    sys.path.insert(0, ".")
    from receipt_signing import verify_receipt
    rows = []
    async with httpx.AsyncClient(timeout=90) as plain, httpx.AsyncClient(timeout=90, transport=x402_httpx_transport(client)) as paid:
        # 24/10: Coinbase sends at least 1 USDC, so after the five test calls the rest is drained to Andrea's address
        # through our own paid routes: one proof-of-publication (0.50), then timestamps (0.01) until under a cent
        bal = usdc_balance(acct.address)
        plan = list(CALLS)
        rest = bal - 2080000
        for i in range(min(max(rest, 0) // 10000, 150)):  # anything sent above 2.08 goes back through timestamps
            plan.append(("timestamp", {"sha256": f"{i:064x}", "note": "neo x402 listing test drain 25/10"}))
        print(f"::notice title=selftest::plan {len(plan)} paid calls for {bal / 1e6} USDC")
        want = {**WANT, "timestamp": "10000"}
        for name, body in plan:
            url = f"{BASE}/x402/{name}"
            r0 = await plain.post(url, json=body)
            req = json.loads(base64.b64decode(r0.headers.get("payment-required", "")) or b"{}") if r0.status_code == 402 else {}
            acc = (req.get("accepts") or [{}])[0]
            if r0.status_code != 402 or acc.get("amount") != want.get(name, "10000") or acc.get("payTo", "").lower() != PAY_TO:
                rows.append({"service": name, "skipped": f"unpaid status {r0.status_code}, terms {acc.get('amount')} to ok={acc.get('payTo','').lower()==PAY_TO}"})
                continue
            r = await paid.post(url, json=body)
            j = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
            pr = r.headers.get("payment-response")
            rows.append({"service": name, "status": r.status_code, "signature_ok": bool(j.get("signature")) and verify_receipt(j, pub),
                         "log_seq": ((j.get("receipt") or {}).get("log") or {}).get("seq"), "tx": (j.get("payment") or {}).get("transaction"),
                         "payment_response": bool(pr), "error": j.get("error")})
            if len(rows) <= 6 or rows[-1].get("status") != 200:
                print(f"::notice title=selftest {name} #{len(rows)}::" + json.dumps(rows[-1])[:600])
        # 25/10: if a call was not charged (our side failed), the money is still here and the key dies with the
        # runner: send what is left to Andrea through proofs (0.50) and timestamps (0.01)
        alts = iter(["https://remote.mcpservers.org/fetch/mcp", "https://docs.mcp.cloudflare.com/mcp"])
        for _ in range(12):
            left = usdc_balance(acct.address)
            if left >= 2000000 and not any(x.get("service") == "mcp-audit" and x.get("status") == 200 for x in rows):
                nxt = next(alts, None)
                if nxt is None:
                    break
                name, body = "mcp-audit", {"url": nxt}
            elif left >= 500000:
                name, body = "proof-of-publication", {"url": "https://en.wikipedia.org/wiki/Hash_chain"}
            else:
                break
            r = await paid.post(f"{BASE}/x402/{name}", json=body)
            rows.append({"service": name, "status": r.status_code, "retry": True})
            print(f"::notice title=selftest retry {name}::status {r.status_code}")
        for i in range(250):
            if usdc_balance(acct.address) < 10000:
                break
            r = await paid.post(f"{BASE}/x402/timestamp", json={"sha256": f"{i + 500:064x}", "note": "neo x402 listing test drain 25/10"})
            rows.append({"service": "timestamp", "status": r.status_code, "drain": True})
    Path(report).parent.mkdir(parents=True, exist_ok=True)
    Path(report).write_text(json.dumps({"at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "rows": rows,
                                        "left_usdc_units": usdc_balance(acct.address)}, indent=1))
    ok = sum(1 for x in rows if x.get("status") == 200)
    sig = sum(1 for x in rows if x.get("signature_ok"))
    print(f"::notice title=selftest::paid_and_served={ok} of {len(rows)} signatures_ok={sig} left {usdc_balance(acct.address)} units")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(run_all(sys.argv[1], sys.argv[2])))
