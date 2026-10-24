# SPDX-License-Identifier: BUSL-1.1
"""The paid microservice catalog (draft, 24/10). One entry per service: price, description, input check, runner.

Every result is signed with neo's receipt key and its fingerprint appended to the public receipt log, like the free
verify_quote. Runners never call another paid service and never spend: the only money is what buyers pay us.
Add a service = add one entry here + its Bazaar discovery block in x402_bazaar.json.
"""
from __future__ import annotations

import asyncio
import importlib.util
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import hashlib

import mcp_audit
import mcp_endpoint_verifier as ev
import prompt_injection_scan
import quote_verifier
import receipt_log

ROOT = Path(__file__).resolve().parent
BAZAAR = json.loads((ROOT / "x402_bazaar.json").read_text())
DEADLINE = 45.0
NO_CHARGE = ("verification_deadline_exceeded", "rate_limited", "internal_")


def _tool(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "tools" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _https(v) -> bool:
    return isinstance(v, str) and v.startswith("https://") and len(v) <= 2048


# --- validators (bad input is refused before any payment is looked at) ----------------------------------------
def v_quote(b):
    if not _https(b.get("url")):
        return "url must be https"
    q = str(b.get("quote") or "").strip()
    return None if 3 <= len(q.split()) and len(q) <= quote_verifier.MAX_QUOTE_CHARS else "quote must be 3+ words, at most 600 chars"


def v_mcp(b):
    return None if _https(b.get("url")) or str(b.get("registry_name") or "").strip() else "url (https) or registry_name required"


def v_lint(b):
    if not _https(b.get("url")):
        return "url must be https"
    return None if str(b.get("method") or "GET").upper() in ("GET", "POST") else "method must be GET or POST"


def v_stamp(b):
    if not re.fullmatch(r"[0-9a-f]{64}", str(b.get("sha256") or "")):
        return "sha256 must be 64 lowercase hex"
    return None if len(str(b.get("note") or "")) <= 200 else "note at most 200 chars"


def v_witness(b):
    e = b.get("entries")
    if not isinstance(e, list) or not e or len(e) > 5000:
        return "entries must be a list of 1..5000 rows"
    sh = b.get("start_head")
    return None if sh is None or re.fullmatch(r"[0-9a-f]{64}", str(sh)) else "start_head must be 64 lowercase hex"


def v_delivery(b):
    if not isinstance(b.get("receipt"), dict):
        return "receipt must be an object"
    return None if isinstance(b.get("seller_public_key_b64"), str) else "seller_public_key_b64 required"


def v_scan(b):
    t, u = b.get("text"), b.get("url")
    if (t is None) == (u is None):
        return "give exactly one of text or url"
    if t is not None:
        return None if isinstance(t, str) and 0 < len(t) <= prompt_injection_scan.MAX_CHARS else "text must be 1..200000 chars"
    return None if _https(u) else "url must be https"


CITE_MAX = 8
CITE_RE = re.compile(r"[\"“]([^\"”]{15,600})[\"”][^\n]{0,200}?(https://[^\s)\]>\"']+)")


def extract_citations(answer: str) -> list[dict]:
    """Quoted sentence followed (within 200 chars, same line) by an https link: the common way agents cite."""
    out = []
    for m in CITE_RE.finditer(str(answer or "")):
        out.append({"quote": m.group(1).strip(), "url": m.group(2).rstrip(".,;")})
    return out[:CITE_MAX]


def v_cite(b):
    cits = b.get("citations")
    if cits is None:
        cits = extract_citations(b.get("answer") or "")
        if not cits:
            return "no citations: pass citations [{url, quote}] or an answer with \"quoted sentence\" followed by its https link"
    if not isinstance(cits, list) or not 1 <= len(cits) <= CITE_MAX:
        return f"citations must be a list of 1..{CITE_MAX}"
    for c in cits:
        if not isinstance(c, dict) or v_quote(c):
            return "each citation needs an https url and a quote of 3+ words"
    return None


# --- runners --------------------------------------------------------------------------------------------------
async def r_quote(b, caller):
    try:
        return await asyncio.wait_for(quote_verifier.verify_quote(b["url"], b["quote"], caller), timeout=DEADLINE)
    except asyncio.TimeoutError:
        return {"ok": False, "error": "verification_deadline_exceeded"}


async def r_mcp(b, caller, version="x402"):
    try:
        return await asyncio.wait_for(ev.verify_endpoint(url=b.get("url") or None, registry_name=b.get("registry_name") or None,
                                                         caller=caller, client_version=version), timeout=DEADLINE)
    except asyncio.TimeoutError:
        return {"ok": False, "error": "verification_deadline_exceeded"}


async def _fetch_402(url: str, method: str) -> tuple[int, str, dict]:
    """One unpaid request, same SSRF checks and IP pinning as verify_quote; redirects are not followed."""
    import httpx
    target = await ev.validate_public_https(url)
    headers = {"User-Agent": "neo-x402-lint/0.1 (unpaid read)", "Accept": "application/json", "Content-Type": "application/json"}
    pinned, pinned_headers, ext = ev.pin_to_resolved_ip(url, target, headers)
    async with httpx.AsyncClient(timeout=20, follow_redirects=False, trust_env=False) as c:
        async with c.stream(method, pinned, headers=pinned_headers, extensions=ext, content=b"{}" if method == "POST" else None) as r:
            total, chunks = 0, []
            async for ch in r.aiter_bytes():
                total += len(ch)
                if total > 200_000:
                    break
                chunks.append(ch)
            return r.status_code, b"".join(chunks).decode("utf-8", "replace"), dict(r.headers)


async def r_lint(b, caller):
    lint = _tool("x402_lint")
    method = str(b.get("method") or "GET").upper()
    try:
        st, body, hd = await asyncio.wait_for(_fetch_402(b["url"], method), timeout=DEADLINE)
    except asyncio.TimeoutError:
        return {"ok": False, "error": "verification_deadline_exceeded"}
    except ev.VerificationError as e:
        return {"ok": True, "url": b["url"], "method": method, "findings": [{"level": "error", "code": "unreachable", "detail": str(e.args[0] if e.args else e)}], "errors": 1}
    f = lint.lint(st, body, hd, b["url"], method)
    return {"ok": True, "url": b["url"], "method": method, "http_status": st, "findings": f,
            "errors": sum(x["level"] == "error" for x in f)}


async def r_stamp(b, caller):
    return {"ok": True, "sha256": b["sha256"], "note": str(b.get("note") or "")[:200],
            "received_at_utc": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "anchoring": "the receipt's log entry is anchored daily (OpenTimestamps on Bitcoin, Software Heritage)"}


async def r_witness(b, caller):
    chk = receipt_log.verify_chain(b["entries"], start_head=b.get("start_head") or receipt_log.GENESIS,
                                   start_seq=int(b["entries"][0][0]) - 1 if isinstance(b["entries"][0], list) and isinstance(b["entries"][0][0], int) else 0)
    return {"ok": bool(chk["ok"]), "log": str(b.get("log") or "")[:80], "size": chk["count"], "head": chk["head"],
            "error": chk["error"], "rule": "h_n = sha256(bytes.fromhex(h_{n-1}) + canonical_json(entry)), h_0 = 64 zeros"}


async def r_delivery(b, caller):
    dr = _tool("delivery_receipt")
    res = dr.verify(b["receipt"], b["seller_public_key_b64"], b.get("buyer_body_sha256"), b.get("hop_public_keys") or {})
    return {"ok": True, "verdict": res}


async def r_scan(b, caller):
    if b.get("text") is not None:
        return {**prompt_injection_scan.scan(b["text"]), "source": "text"}
    try:
        page = await asyncio.wait_for(quote_verifier._fetch(b["url"]), timeout=DEADLINE)
    except asyncio.TimeoutError:
        return {"ok": False, "error": "verification_deadline_exceeded"}
    except ev.VerificationError as e:
        return {"ok": True, "source": "url", "url": b["url"], "unreachable": str(e.args[0] if e.args else e), "risk_score": None, "level": "unknown", "findings": []}
    return {**prompt_injection_scan.scan(page["text"]), "source": "url", "url": b["url"], "final_url": page["final_url"]}


async def r_cite(b, caller):
    cits = b.get("citations") or extract_citations(b.get("answer") or "")
    rows = []
    for c in cits[:CITE_MAX]:  # sequential: one bucket per payer, same limits as the free tool
        r = await r_quote({"url": c["url"], "quote": c["quote"]}, caller + "#cite")
        rows.append({"url": c["url"], "quote": c["quote"][:200], "outcome": r.get("outcome"), "error": r.get("error")})
    counts = {}
    for r in rows:
        k = r["outcome"] or "error"
        counts[k] = counts.get(k, 0) + 1
    ok = counts.get("verbatim", 0)
    return {"ok": True, "checked": len(rows), "verbatim": ok, "counts": counts, "citations": rows,
            "summary": f"{ok} of {len(rows)} quotes found word for word on their pages",
            "note": "not_found means the words are not on that page, not that the claim is false; who wrote it is still yours to judge."}


LAST_FP: dict[str, str] = {}  # url -> last audited tool fingerprint (in memory; resets on deploy, the signed reports keep it)


async def r_audit(b, caller, version="x402"):
    try:
        v = await asyncio.wait_for(ev.verify_endpoint(url=b["url"], caller=caller, client_version=version, full_tools=True), timeout=DEADLINE)
    except asyncio.TimeoutError:
        return {"ok": False, "error": "verification_deadline_exceeded"}
    if v.get("ok") is False and str(v.get("error") or "").startswith("rate_limited"):
        return {"ok": False, "error": v["error"]}
    prev = b.get("previous_fingerprint") or LAST_FP.get(b["url"])
    rep = mcp_audit.audit(v, prev)
    if rep.get("tools_fingerprint"):
        if len(LAST_FP) > 2000:
            LAST_FP.clear()
        LAST_FP[b["url"]] = rep["tools_fingerprint"]
    return rep


def v_audit(b):
    if not _https(b.get("url")):
        return "url must be https"
    pf = b.get("previous_fingerprint")
    return None if pf is None or re.fullmatch(r"[0-9a-f]{64}", str(pf)) else "previous_fingerprint must be 64 lowercase hex"


def v_proof(b):
    return None if _https(b.get("url")) else "url must be https"


async def r_proof(b, caller):
    try:
        page = await asyncio.wait_for(quote_verifier._fetch(b["url"]), timeout=DEADLINE)
    except asyncio.TimeoutError:
        return {"ok": False, "error": "verification_deadline_exceeded"}
    except ev.VerificationError as e:
        return {"ok": True, "url": b["url"], "fetched": False, "reason": str(e.args[0] if e.args else e)}
    text = page["text"]
    raw = text.encode("utf-8")
    return {"ok": True, "url": b["url"], "fetched": True, "final_url": page["final_url"], "http_status": page["status"],
            "fetched_at_utc": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "content_sha256": hashlib.sha256(raw).hexdigest(), "content_bytes": len(raw),
            "hash_of": "the page text as fetched (UTF-8, first 2 MB), returned in full below up to 200 kB",
            "content": text[:200_000], "content_truncated": len(text) > 200_000,
            "anchoring": "this signed receipt's log entry is anchored daily (OpenTimestamps on Bitcoin, Software Heritage)"}


SERVICES: dict[str, dict[str, Any]] = {
    "mcp-audit": {"price_usd": 2.00, "tool": "mcp_audit", "validate": v_audit, "run": r_audit,
                  "tags": ["mcp", "security", "tool-poisoning", "audit"],
                  "description": "Security audit of a public MCP server before you connect: tool poisoning (hidden instructions in tool descriptions and schemas), shadowing, risky capabilities, annotation mismatches, transport errors, and a tool fingerprint to catch silent changes. Reads initialize + tools/list only. Signed, logged report."},
    "proof-of-publication": {"price_usd": 0.50, "tool": "proof_of_publication", "validate": v_proof, "run": r_proof,
                             "tags": ["evidence", "proof", "timestamp", "archive"],
                             "description": "Signed evidence that a public page said this at this time: sha256 of the fetched text, the text itself, final URL and status, logged in a public append-only log anchored daily on Bitcoin and Software Heritage."},
    "injection-scan": {"price_usd": 0.01, "tool": "injection_scan", "validate": v_scan, "run": r_scan,
                       "tags": ["security", "prompt-injection", "agents", "safety"],
                       "description": "Scan text or a public page for prompt injection before your agent reads it: overrides, fake roles, exfiltration, tool abuse, payment asks, invisible Unicode/HTML-hidden instructions, base64. Rule-based evidence, signed and logged."},
    "citation-check": {"price_usd": 0.05, "tool": "citation_check", "validate": v_cite, "run": r_cite,
                       "tags": ["citations", "fact-check", "hallucination", "research"],
                       "description": "Check every citation in an answer (up to 8 quote+link pairs, or extracted from the text): which quotes are really on their pages. One signed, logged report."},
    "verify-quote": {"price_usd": 0.01, "tool": "verify_quote", "validate": v_quote, "run": r_quote,
                     "tags": ["verification", "quotes", "citations", "fact-check"],
                     "description": "Is this exact sentence on this public page? verbatim / paraphrase / stitched / not_found / unreachable, with an Ed25519-signed receipt logged in a public, witnessed, append-only log."},
    "mcp-check": {"price_usd": 0.01, "tool": "verify_mcp_endpoint", "validate": v_mcp, "run": r_mcp,
                  "tags": ["mcp", "monitoring", "verification"],
                  "description": "Read-only check of a public MCP endpoint: DNS/SSRF safety, TLS, initialize, tools/list sanity, latency. Never calls remote tools. Signed, logged result."},
    "x402-lint": {"price_usd": 0.01, "tool": "x402_lint", "validate": v_lint, "run": r_lint,
                  "tags": ["x402", "payments", "lint", "sellers"],
                  "description": "Lint a seller's unpaid 402: body vs PAYMENT-REQUIRED header fields, EIP-55 checksums, method conflicts. One unpaid read, never pays. Signed, logged result."},
    "timestamp": {"price_usd": 0.01, "tool": "timestamp", "validate": v_stamp, "run": r_stamp,
                  "tags": ["timestamp", "proof", "notary", "hash"],
                  "description": "Prove you had this sha256 at this time: signed receipt with its position in neo's public log, anchored daily on Bitcoin (OpenTimestamps) and Software Heritage."},
    "log-witness": {"price_usd": 0.01, "tool": "log_witness", "validate": v_witness, "run": r_witness,
                    "tags": ["transparency-log", "witness", "hash-chain"],
                    "description": "Recompute a hash-chained log ([seq, ts, kind, item, extra] rows, up to 5000) and get its size and head, signed and logged: a third-party witness line."},
    "delivery-receipt-verify": {"price_usd": 0.01, "tool": "delivery_receipt_verify", "validate": v_delivery, "run": r_delivery,
                                "tags": ["x402", "receipts", "disputes", "verification"],
                                "description": "Verify an x402 delivery receipt (v0.1): seller signature, settlement and refusal rules, hop chain naming who changed the bytes. Signed, logged verdict."},
}
for _k, _s in SERVICES.items():
    _s["bazaar"] = BAZAAR.get(_k)
    _s["service_name"] = "neo " + _k
    _s["no_charge_errors"] = NO_CHARGE


def catalog(base_url: str) -> dict:
    return {"payment": "x402 (USDC on Base), pay per call", "services": [
        {"name": k, "url": f"{base_url}/x402/{k}", "method": "POST", "price_usd": s["price_usd"], "description": s["description"]}
        for k, s in SERVICES.items()]}


def openapi(base_url: str) -> dict:
    """24/10: OpenAPI 3.1 discovery document for the paid routes (x402scan spec: x-payment-info + a 402 response
    on each paid operation; Circle's Agent Marketplace asks for an OpenAPI spec). Built from SERVICES and the
    Bazaar blocks, so prices and schemas cannot drift from what the routes enforce."""
    paths = {}
    for k, s in SERVICES.items():
        info = (s.get("bazaar") or {}).get("info") or {}
        body_schema = ((((s.get("bazaar") or {}).get("schema") or {}).get("properties") or {}).get("input") or {}) \
            .get("properties", {}).get("body") or {"type": "object"}
        body_schema = {"type": "object", **body_schema}
        example_in = (info.get("input") or {}).get("body")
        example_out = (info.get("output") or {}).get("example")
        price = f"{s['price_usd']:.2f}"
        paths[f"/x402/{k}"] = {"post": {
            "operationId": k.replace("-", "_"),
            "summary": s["description"].split(":")[0].split(".")[0][:120],
            "description": s["description"],
            "tags": s.get("tags", [])[:5],
            "x-payment-info": {"price": {"mode": "fixed", "currency": "USD", "amount": price},
                               "protocols": [{"x402": {"network": "eip155:8453", "asset": "USDC", "scheme": "exact"}}]},
            "requestBody": {"required": True, "content": {"application/json": {
                "schema": body_schema, **({"example": example_in} if example_in is not None else {})}}},
            "responses": {
                "200": {"description": "Result, signed by neo (Ed25519) and appended to neo's public receipt log. "
                                       "PAYMENT-RESPONSE header carries the settlement.",
                        "content": {"application/json": {"schema": {"type": "object"},
                                                         **({"example": example_out} if example_out is not None else {})}}},
                "400": {"description": "Invalid input with a payment attached: refused before the payment is verified, nothing is charged."},
                "402": {"description": f"Payment required: {price} USDC on Base (x402 v2, exact scheme). "
                                       "Requirements in the PAYMENT-REQUIRED header (v2) and in the body (v1)."},
                "503": {"description": "Our side failed after verification: not settled, nothing is charged."}}}}
    return {"openapi": "3.1.0",
            "info": {"title": "neo verification microservices (x402)", "version": "2026-10-24",
                     "description": "Pay-per-call verification tools for agents: MCP server audits, prompt-injection scans, "
                                    "citation and quote checks, timestamps and proofs of publication, log witnessing, "
                                    "x402 delivery receipts. Every result is signed and logged; receipts verify offline. "
                                    "No account, no API key: pay per call with x402 (USDC on Base).",
                     "x-guidance": "POST JSON to the route without payment to get the x402 terms (402, PAYMENT-REQUIRED "
                                   "header). Retry with the signed payment in PAYMENT-SIGNATURE (v2) or X-PAYMENT (v1). "
                                   "Invalid input with a payment is refused before the payment is verified, and a failure "
                                   "on our side is not settled: you are charged only for a delivered result. Results carry "
                                   "an Ed25519 signature and a position in neo's public receipt log (GET /receipts/log)."},
            "servers": [{"url": base_url}],
            "paths": paths}


def well_known(base_url: str) -> dict:
    """/.well-known/x402 fan-out (x402scan compatibility)."""
    return {"version": 1, "resources": [f"{base_url}/x402/{k}" for k in SERVICES]}
