"""Apify Actor: Verify Quote (trial, 23/10, Andrea's OK).

For each {url, quote} it asks neo's public MCP server (verify_quote, the same free tool agents use on Agent
Commons) and returns the outcome with neo's Ed25519-signed receipt. The Actor checks the signature itself
against the key in neo's agent card before charging, and charges one "quote-verified" event per item that
got a signed outcome. Errors (bad input, rate limit, server down) are not charged.

No secret is used or needed here: the signing key stays on neo's server; the Actor only reads public data.
"""
from __future__ import annotations

import base64
import json
import re
import urllib.request

ORIGIN = "https://neo-collettive.onrender.com"
MAX_ITEMS = 50
EVENT = "quote-verified"
PACE_SECONDS = 6.5  # neo allows 10 calls a minute per caller: stay under it instead of hitting the limit


def canonical_json(obj) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def verify_receipt(obj: dict, public_key_b64: str) -> bool:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    try:
        payload = dict(obj)
        sig = payload.pop("signature")
        if not isinstance(sig, str) or not re.fullmatch(r"[A-Za-z0-9_-]{86}", sig):
            return False
        key = Ed25519PublicKey.from_public_bytes(base64.b64decode(public_key_b64, validate=True))
        key.verify(base64.urlsafe_b64decode(sig + "=="), canonical_json(payload))
        return True
    except Exception:
        return False


def http(url: str, body: dict | None = None, timeout: int = 90) -> str:
    req = urllib.request.Request(url, data=json.dumps(body).encode() if body is not None else None,
                                 method="POST" if body is not None else "GET",
                                 headers={"Content-Type": "application/json", "User-Agent": "neo-verify-quote-apify/0.1",
                                          "Accept": "application/json, text/event-stream"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def mcp_result(raw: str) -> dict:
    m = re.search(r"^data: (.*)$", raw, re.M)
    d = json.loads(m.group(1) if m else raw)
    if "error" in d:
        return {"ok": False, "error": "mcp_protocol_error"}
    res = d.get("result") or {}
    sc = res.get("structuredContent")
    if isinstance(sc, dict) and sc:
        return sc
    for c in res.get("content") or []:
        try:
            return json.loads(c.get("text") or "{}")
        except Exception:
            pass
    return {"ok": False, "error": "empty_result"}


def check_items(items: list, call, public_key_b64: str) -> list[dict]:
    """Pure core (tested): call(url, quote) -> neo's result. Returns one row per item, with 'charge'."""
    rows = []
    for it in (items or [])[:MAX_ITEMS]:
        url, quote = str((it or {}).get("url") or "").strip(), str((it or {}).get("quote") or "").strip()
        if not url.startswith("https://") or len(quote.split()) < 3:
            rows.append({"url": url, "quote": quote, "error": "need an https url and a quote of at least 3 words",
                         "charge": False})
            continue
        try:
            r = call(url, quote)
        except Exception as e:
            rows.append({"url": url, "quote": quote, "error": f"neo unreachable: {type(e).__name__}", "charge": False})
            continue
        signed = bool(r.get("signature")) and verify_receipt(r, public_key_b64)
        rows.append({"url": url, "quote": quote, "outcome": r.get("outcome"), "error": r.get("error"),
                     "signature_verified": signed, "log_seq": ((r.get("receipt") or {}).get("log") or {}).get("seq"),
                     "receipt": r, "charge": bool(signed and r.get("outcome"))})
    return rows


async def main() -> None:
    from apify import Actor
    async with Actor:
        inp = await Actor.get_input() or {}
        card = json.loads(http(ORIGIN + "/.well-known/agent-card.json"))
        pub = (card.get("receipt_signing") or {}).get("public_key_b64", "")
        http(ORIGIN + "/mcp", {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
            "protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "verify-quote-apify", "version": "0.1"}}})
        n = {"id": 1}

        def call(url: str, quote: str) -> dict:
            import time
            for attempt in (1, 2):
                time.sleep(PACE_SECONDS if n["id"] > 1 else 0)
                n["id"] += 1
                r = mcp_result(http(ORIGIN + "/mcp", {"jsonrpc": "2.0", "id": n["id"], "method": "tools/call",
                                                      "params": {"name": "verify_quote", "arguments": {"url": url, "quote": quote}}}))
                if not str(r.get("error") or "").startswith("rate_limited") or attempt == 2:
                    return r
                time.sleep(30)  # one retry after the window clears; never more
            return r

        for row in check_items(inp.get("items") or [], call, pub):
            charge = row.pop("charge")
            await Actor.push_data(row)
            if charge:
                await Actor.charge(event_name=EVENT)


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
