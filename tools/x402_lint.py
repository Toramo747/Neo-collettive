#!/usr/bin/env python3
"""x402 lint (trial, 24/10): read a seller's unpaid 402 and list what would make a payment fail. Never pays.

Checks come from real cases on Agent Commons (skitter, 19-23/10): a body and a PAYMENT-REQUIRED header that
disagree, an asset address that fails EIP-55, a description that says POST while the schema says GET.

  python tools/x402_lint.py <url> [GET|POST]          one route, findings as JSON (exit 1 if any error)
  python tools/x402_lint.py --discovery <out.json> [n]  lint n routes from Coinbase's public Bazaar catalog

Findings: {"level": "error"|"warn"|"info", "code": "...", "detail": "..."}. Errors are things that make a
correct client fail or pay the wrong party; warnings are things a careful client would stop on.
"""
from __future__ import annotations

import base64
import json
import re
import sys
import urllib.error
import urllib.request

USDC = {"eip155:8453": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",   # Base
        "eip155:84532": "0x036CbD53842c5426634e7929541eC2318f3dCF7e"}  # Base Sepolia
V1_NAMES = {"base": "eip155:8453", "base-sepolia": "eip155:84532"}
DISCOVERY = "https://api.cdp.coinbase.com/platform/v2/x402/discovery/resources"

# --- keccak-256 (pure Python, for EIP-55 checksums; no extra dependency) ---------------------------------
_RC = [0x0000000000000001, 0x0000000000008082, 0x800000000000808A, 0x8000000080008000, 0x000000000000808B,
       0x0000000080000001, 0x8000000080008081, 0x8000000000008009, 0x000000000000008A, 0x0000000000000088,
       0x0000000080008009, 0x000000008000000A, 0x000000008000808B, 0x800000000000008B, 0x8000000000008089,
       0x8000000000008003, 0x8000000000008002, 0x8000000000000080, 0x000000000000800A, 0x800000008000000A,
       0x8000000080008081, 0x8000000000008080, 0x0000000080000001, 0x8000000080008008]
_ROT = [[0, 36, 3, 41, 18], [1, 44, 10, 45, 2], [62, 6, 43, 15, 61], [28, 55, 25, 21, 56], [27, 20, 39, 8, 14]]
_M = (1 << 64) - 1


def _rol(x, n):
    return ((x << n) | (x >> (64 - n))) & _M if n else x


def _f(a):
    for rc in _RC:
        c = [a[x][0] ^ a[x][1] ^ a[x][2] ^ a[x][3] ^ a[x][4] for x in range(5)]
        d = [c[(x - 1) % 5] ^ _rol(c[(x + 1) % 5], 1) for x in range(5)]
        a = [[a[x][y] ^ d[x] for y in range(5)] for x in range(5)]
        b = [[0] * 5 for _ in range(5)]
        for x in range(5):
            for y in range(5):
                b[y][(2 * x + 3 * y) % 5] = _rol(a[x][y], _ROT[x][y])
        a = [[b[x][y] ^ ((~b[(x + 1) % 5][y]) & b[(x + 2) % 5][y]) for y in range(5)] for x in range(5)]
        a[0][0] ^= rc
    return a


def keccak256(data: bytes) -> bytes:
    rate = 136
    msg = bytearray(data) + b"\x01"
    msg += b"\x00" * (-len(msg) % rate)
    msg[-1] |= 0x80
    a = [[0] * 5 for _ in range(5)]
    for off in range(0, len(msg), rate):
        blk = msg[off:off + rate]
        for i in range(rate // 8):
            a[i % 5][i // 5] ^= int.from_bytes(blk[8 * i:8 * i + 8], "little")
        a = _f(a)
    out = b"".join(a[i % 5][i // 5].to_bytes(8, "little") for i in range(rate // 8))
    return out[:32]


def checksum(addr: str) -> str:
    h = addr[2:].lower()
    d = keccak256(h.encode()).hex()
    return "0x" + "".join(c.upper() if c.isalpha() and int(d[i], 16) >= 8 else c for i, c in enumerate(h))


def addr_findings(field: str, a) -> list[dict]:
    a = str(a or "")
    if not re.fullmatch(r"0x[0-9a-fA-F]{40}", a):
        return [{"level": "error", "code": f"{field}_not_an_address", "detail": f"{field} is not a 20-byte hex address"}]
    if a[2:] in (a[2:].lower(), a[2:].upper()):
        return [{"level": "info", "code": f"{field}_no_checksum", "detail": f"{field} has no EIP-55 checksum (single case)"}]
    if checksum(a) != a:
        return [{"level": "error", "code": f"{field}_bad_checksum",
                 "detail": f"{field} fails EIP-55: strict clients reject it or sign a different spelling than the seller expects"}]
    return []


# --- parsing --------------------------------------------------------------------------------------------
def parse_header(v: str | None):
    if not v:
        return None
    for dec in (lambda s: base64.b64decode(s + "=" * (-len(s) % 4)), lambda s: base64.urlsafe_b64decode(s + "=" * (-len(s) % 4)),
                lambda s: s.encode()):
        try:
            return json.loads(dec(v.strip()).decode())
        except Exception:
            pass
    return "unparseable"


def norm_accept(acc: dict) -> dict:
    net = str(acc.get("network") or "")
    return {"network": V1_NAMES.get(net, net), "asset": str(acc.get("asset") or ""),
            "amount": str(acc.get("amount") or acc.get("maxAmountRequired") or ""),
            "payTo": str(acc.get("payTo") or ""), "scheme": acc.get("scheme")}


def declared_methods(doc: dict) -> set[str]:
    """HTTP methods the seller declares for the route. Skips JSON-schema "properties" (24/10: our own x402-lint
    service has a body parameter named "method", which is input data, not the route's method)."""
    found = set()
    def walk(o, path=""):
        if isinstance(o, dict):
            for k, v in o.items():
                if k.lower() == "method" and isinstance(v, str) and v.upper() in ("GET", "POST", "PUT", "PATCH", "DELETE", "HEAD"):
                    found.add(v.upper())
                if k in ("properties", "body", "queryParams", "input_schema", "inputSchema", "example"):
                    continue  # input data and schemas, not the route's own method
                walk(v, path + "/" + k)
        elif isinstance(o, list):
            for v in o:
                walk(v, path)
    walk(doc)
    return found


def lint(status: int, body_text: str, headers: dict, url: str, method: str = "GET") -> list[dict]:
    out = []
    h = {k.lower(): v for k, v in headers.items()}
    if status in (400, 405, 415, 422):
        return [{"level": "info", "code": "needs_valid_request", "detail": f"HTTP {status} before any payment requirements: the route checks the request first; probe again with a valid method/body"}]
    if status != 402:
        return [{"level": "error", "code": "not_402", "detail": f"unpaid request returned HTTP {status}, not 402"}]
    try:
        body = json.loads(body_text) if body_text.strip() else None
    except Exception:
        body = None
        out.append({"level": "warn", "code": "body_not_json", "detail": "402 body is not JSON"})
    header = parse_header(h.get("payment-required"))
    if header == "unparseable":
        out.append({"level": "error", "code": "header_unparseable", "detail": "PAYMENT-REQUIRED header is not base64 JSON"})
        header = None
    if not body and not header:
        return out + [{"level": "error", "code": "no_requirements", "detail": "neither body nor PAYMENT-REQUIRED header carries payment requirements"}]
    # a body without x402Version/accepts is a plain error message, not payment requirements
    docs = {k: d for k, d in (("body", body), ("header", header)) if isinstance(d, dict) and ("accepts" in d or "x402Version" in d)}
    if not docs:
        return out + [{"level": "error", "code": "no_requirements", "detail": "neither body nor PAYMENT-REQUIRED header carries payment requirements"}]
    vers = {k: d.get("x402Version") for k, d in docs.items()}
    if len(docs) == 2 and vers["body"] != vers["header"]:
        # 24/10: a v1 body beside a v2 header is a common compatibility pattern; it is only a fault when the
        # payment fields disagree (checked below). Recorded as info so receipts hash both.
        out.append({"level": "info", "code": "dual_version",
                    "detail": f"body is x402 v{vers['body']}, header is v{vers['header']} (compatibility pattern; fields compared below)"})
    acc = {k: [norm_accept(a) for a in (d.get("accepts") or []) if isinstance(a, dict)] for k, d in docs.items()}
    for k, lst in acc.items():
        if not lst:
            out.append({"level": "error", "code": f"{k}_no_accepts", "detail": f"{k} has no accepts entry"})
    if len(acc) == 2 and acc["body"] and acc["header"]:
        b0, h0 = acc["body"][0], acc["header"][0]
        for f in ("network", "asset", "amount", "payTo"):
            if b0[f].lower() != h0[f].lower():
                out.append({"level": "error", "code": f"{f}_mismatch", "detail": f"body and header disagree on {f}"})
    for k, lst in acc.items():
        for i, a in enumerate(lst[:4]):
            if not a["network"].startswith("eip155:"):
                continue  # EVM checks only; Solana and other chains use other address formats
            out += [dict(x, detail=f"{k} accepts[{i}]: " + x["detail"]) for x in addr_findings("asset", a["asset"]) + addr_findings("payTo", a["payTo"])]
            usdc = USDC.get(a["network"])
            if usdc and a["asset"] and a["asset"].lower() != usdc.lower():
                out.append({"level": "warn", "code": "asset_not_usdc", "detail": f"{k} accepts[{i}]: asset is not USDC on {a['network']}"})
            if not re.fullmatch(r"[1-9][0-9]*", a["amount"]):
                out.append({"level": "error", "code": "amount_invalid", "detail": f"{k} accepts[{i}]: amount must be a positive integer string in base units"})
            if not re.fullmatch(r"[a-z0-9-]+:[A-Za-z0-9-]+", a["network"]):
                out.append({"level": "warn", "code": "network_unknown", "detail": f"{k} accepts[{i}]: network '{a['network']}' is neither CAIP-2 nor a known v1 name"})
    meths = set().union(*[declared_methods(d) for d in docs.values()]) if docs else set()
    if len(meths) > 1:
        out.append({"level": "warn", "code": "method_conflict", "detail": f"the requirements declare several methods: {sorted(meths)}"})
    for d in docs.values():
        desc = json.dumps(d).lower()
        for m in ("post", "get"):
            if re.search(rf"\bpaid {m}\b|\b{m} (request|only|with)\b", desc) and meths and m.upper() not in meths:
                out.append({"level": "warn", "code": "description_method_conflict",
                            "detail": f"the description says {m.upper()} but the schema declares {sorted(meths)}"})
                break
    if meths and method.upper() not in meths:
        out.append({"level": "info", "code": "probed_other_method", "detail": f"probed with {method}, schema declares {sorted(meths)}"})
    return out


def fetch(url: str, method: str = "GET"):
    req = urllib.request.Request(url, method=method, data=b"{}" if method == "POST" else None,
                                 headers={"User-Agent": "neo-x402-lint/0.1 (unpaid read)", "Accept": "application/json",
                                          "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status, r.read(200_000).decode("utf-8", "replace"), dict(r.headers)
    except urllib.error.HTTPError as e:
        return e.code, e.read(200_000).decode("utf-8", "replace"), dict(e.headers)


def discovery(out_json: str, n: int = 25) -> int:
    with urllib.request.urlopen(urllib.request.Request(DISCOVERY + f"?limit={max(n, 50)}",
                                                       headers={"User-Agent": "neo-x402-lint/0.1"}), timeout=30) as r:
        d = json.loads(r.read().decode())
    items = d.get("items") or d.get("resources") or d.get("data") or (d if isinstance(d, list) else [])
    rows, counts = [], {}
    for it in items[:n]:
        url = it.get("resource") or (it.get("resource") or {}).get("url") if isinstance(it, dict) else None
        if isinstance(url, dict):
            url = url.get("url")
        if not url or not str(url).startswith("https://"):
            continue
        meth = "GET"
        ms = declared_methods(it)
        if ms and "GET" not in ms:
            meth = sorted(ms)[0]
        try:
            st, body, hd = fetch(url, meth)
            f = lint(st, body, hd, url, meth)
        except Exception as e:
            f = [{"level": "error", "code": "unreachable", "detail": type(e).__name__}]
        for x in f:
            counts[x["code"]] = counts.get(x["code"], 0) + 1
        rows.append({"url": url, "method": meth, "errors": sum(x["level"] == "error" for x in f), "findings": f})
    open(out_json, "w").write(json.dumps({"checked": len(rows), "codes": counts, "rows": rows}, indent=1))
    print(f"::notice title=x402 lint::routes={len(rows)} with_errors={sum(r['errors'] > 0 for r in rows)} codes={json.dumps(counts)[:700]}")
    return 0


if __name__ == "__main__":
    a = sys.argv
    if len(a) >= 3 and a[1] == "--discovery":
        sys.exit(discovery(a[2], int(a[3]) if len(a) > 3 else 25))
    if len(a) >= 2 and a[1].startswith("https://"):
        st, body, hd = fetch(a[1], a[2] if len(a) > 2 else "GET")
        res = lint(st, body, hd, a[1], a[2] if len(a) > 2 else "GET")
        print(json.dumps(res, indent=1))
        sys.exit(1 if any(x["level"] == "error" for x in res) else 0)
    print(__doc__)
    sys.exit(2)
