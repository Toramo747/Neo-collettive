# SPDX-License-Identifier: BUSL-1.1
"""Pay-per-call microservices over x402 (draft, 24/10, Andrea's OK to prepare; not enabled until he sets the env).

Buyers pay in USDC on Base, straight to OSIXBAY's address; payment is verified and settled through Coinbase's
CDP facilitator. Flow per call (x402 v2, with a v1 body for older clients):

  1. no payment header        -> 402 with PAYMENT-REQUIRED (base64 JSON, v2) and a v1 JSON body
  2. PAYMENT-SIGNATURE / X-PAYMENT present
       -> the accepted requirements must equal ours exactly (scheme, network, asset, amount, payTo)
       -> facilitator /verify (no money moves)
       -> run the service (the result is computed but not released yet)
       -> facilitator /settle
       -> settled: 200 with the result and PAYMENT-RESPONSE; not settled: 402, result withheld, nothing charged

Enabled only when X402_PAY_TO, CDP_API_KEY_ID and CDP_API_KEY_SECRET are all set (Render env, set by Andrea).
Otherwise every paid route answers 503 x402_not_enabled. The key secret is read from the environment, used to sign
short-lived JWTs, and never logged or returned.
"""
from __future__ import annotations

import base64
import json
import os
import random
import re
import time
from typing import Any, Awaitable, Callable

USDC_BASE = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"
NETWORK = "eip155:8453"
FACILITATOR_HOST = "api.cdp.coinbase.com"
FACILITATOR_ROUTE = "/platform/v2/x402"
MAX_TIMEOUT_SECONDS = 120


# --- counters (public aggregates only: no payer, no amount per call) -------------------------------------------
METRICS: dict[str, int] = {"asked_to_pay": 0, "bad_input": 0, "wrong_terms": 0, "payment_invalid": 0,
                           "our_failure_not_charged": 0, "failed_result_not_charged": 0, "client_gone_not_charged": 0,
                           "settle_uncertain_delivered": 0, "settle_failed": 0, "paid_and_served": 0, "facilitator_http_error": 0}


BY_SERVICE: dict[str, dict[str, int]] = {}  # 24/10: the same counters per service, to see what is asked for


def _count(k: str, service: dict | None = None) -> None:
    METRICS[k] = METRICS.get(k, 0) + 1
    name = str((service or {}).get("service_name") or "")
    if name:
        d = BY_SERVICE.setdefault(name, {})
        d[k] = d.get(k, 0) + 1


# --- configuration -------------------------------------------------------------------------------------------
def config(env: dict | None = None) -> dict | None:
    e = os.environ if env is None else env
    pay_to = str(e.get("X402_PAY_TO") or "").strip()
    key_id = str(e.get("CDP_API_KEY_ID") or "").strip()
    secret = str(e.get("CDP_API_KEY_SECRET") or "").strip()
    if not (re.fullmatch(r"0x[0-9a-fA-F]{40}", pay_to) and key_id and secret):
        return None
    return {"pay_to": pay_to, "key_id": key_id, "secret": secret}


def usd_to_units(usd: float) -> str:
    return str(int(round(usd * 1_000_000)))  # USDC has 6 decimals


# --- 402 -----------------------------------------------------------------------------------------------------
def requirements(price_usd: float, pay_to: str) -> dict:
    return {"scheme": "exact", "network": NETWORK, "asset": USDC_BASE, "amount": usd_to_units(price_usd),
            "payTo": pay_to, "maxTimeoutSeconds": MAX_TIMEOUT_SECONDS, "extra": {"name": "USD Coin", "version": "2"}}


def payment_required(service: dict, url: str, pay_to: str, error: str = "payment required") -> tuple[dict, dict]:
    """Returns (headers, v1 body). The v2 object goes in PAYMENT-REQUIRED; the body repeats it in v1 form."""
    req = requirements(service["price_usd"], pay_to)
    resource = {"url": url, "description": service["description"], "mimeType": "application/json",
                "serviceName": service.get("service_name", "neo")[:32], "tags": service.get("tags", [])[:5]}
    v2 = {"x402Version": 2, "error": error, "resource": resource, "accepts": [req]}
    if service.get("bazaar"):
        v2["extensions"] = {"bazaar": service["bazaar"]}
    v1 = {"x402Version": 1, "error": error, "accepts": [{
        "scheme": "exact", "network": "base", "maxAmountRequired": req["amount"], "resource": url,
        "description": service["description"], "mimeType": "application/json", "payTo": pay_to,
        "maxTimeoutSeconds": MAX_TIMEOUT_SECONDS, "asset": USDC_BASE, "extra": req["extra"]}]}
    hdr = {"PAYMENT-REQUIRED": base64.b64encode(json.dumps(v2, separators=(",", ":")).encode()).decode()}
    return hdr, v1


def decode_payment(headers: dict) -> tuple[dict | None, int | None]:
    h = {k.lower(): v for k, v in headers.items()}
    raw, ver = (h.get("payment-signature"), 2) if h.get("payment-signature") else (h.get("x-payment"), 1)
    if not raw:
        return None, None
    try:
        return json.loads(base64.b64decode(raw + "=" * (-len(raw) % 4)).decode()), ver
    except Exception:
        return {"_invalid": True}, ver


def accepted_matches(payload: dict, req: dict, version: int) -> str | None:
    """None when the payment is for exactly our requirements; otherwise the reason (never trust the payer's copy)."""
    if not isinstance(payload, dict) or payload.get("_invalid"):
        return "payment_header_unreadable"
    if version == 2:
        acc = payload.get("accepted") or {}
        pairs = (("scheme", acc.get("scheme")), ("network", acc.get("network")), ("asset", str(acc.get("asset", "")).lower()),
                 ("amount", str(acc.get("amount"))), ("payTo", str(acc.get("payTo", "")).lower()))
    else:
        pairs = (("scheme", payload.get("scheme")), ("network", {"base": NETWORK}.get(payload.get("network"), payload.get("network"))))
    want = {"scheme": req["scheme"], "network": req["network"], "asset": req["asset"].lower(), "amount": req["amount"],
            "payTo": req["payTo"].lower()}
    for k, v in pairs:
        if v != want[k]:
            return f"accepted_{k}_differs"
    return None


# --- CDP auth (JWT, EdDSA or ES256), same claims as Coinbase's own SDK ---------------------------------------
def _b64u(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def cdp_jwt(key_id: str, secret: str, method: str, path: str, now: int | None = None) -> str:
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec, ed25519
    from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
    s = secret.replace("\\n", "\n")
    key, alg = None, None
    try:
        k = serialization.load_pem_private_key(s.encode(), password=None)
        if isinstance(k, ec.EllipticCurvePrivateKey):
            key, alg = k, "ES256"
    except Exception:
        pass
    if key is None:
        raw = base64.b64decode(s)
        if len(raw) != 64:
            raise ValueError("CDP key secret must be a PEM EC key or a base64 Ed25519 key")
        key, alg = ed25519.Ed25519PrivateKey.from_private_bytes(raw[:32]), "EdDSA"
    t = int(time.time()) if now is None else now
    header = {"alg": alg, "kid": key_id, "typ": "JWT", "nonce": "".join(random.choices("0123456789", k=16))}
    claims = {"sub": key_id, "iss": "cdp", "nbf": t, "exp": t + 120, "uris": [f"{method} {FACILITATOR_HOST}{path}"]}
    signing = _b64u(json.dumps(header, separators=(",", ":")).encode()) + "." + _b64u(json.dumps(claims, separators=(",", ":")).encode())
    if alg == "EdDSA":
        sig = key.sign(signing.encode())
    else:
        r, s_ = decode_dss_signature(key.sign(signing.encode(), ec.ECDSA(hashes.SHA256())))
        sig = r.to_bytes(32, "big") + s_.to_bytes(32, "big")
    return signing + "." + _b64u(sig)


async def facilitator(cfg: dict, action: str, version: int, payload: dict, req: dict, post=None) -> dict:
    """POST /verify or /settle. `post(url, headers, json)` is injectable for tests; default uses httpx."""
    path = f"{FACILITATOR_ROUTE}/{action}"
    headers = {"Content-Type": "application/json", "Authorization": "Bearer " + cdp_jwt(cfg["key_id"], cfg["secret"], "POST", path)}
    body = {"x402Version": version, "paymentPayload": payload, "paymentRequirements": req}
    if post is None:
        import httpx
        async with httpx.AsyncClient(timeout=30, trust_env=False) as c:
            r = await c.post(f"https://{FACILITATOR_HOST}{path}", headers=headers, json=body)
            status, data = r.status_code, (r.json() if r.content else {})
    else:
        status, data = await post(f"https://{FACILITATOR_HOST}{path}", headers, body)
    if status != 200:
        _count("facilitator_http_error")
        return {"_http": status, "isValid": False, "success": False, "errorReason": f"facilitator_http_{status}"}
    return data


_SUPPORTED_CACHE: dict = {}


async def facilitator_check(cfg: dict | None, get=None) -> dict:
    """Authenticated GET /supported: proves the key works and Base/exact is offered, without moving money.
    Cached 10 minutes. Returns only booleans and public network names, never key material."""
    if cfg is None:
        return {"ok": False, "reason": "not_configured"}
    now = time.time()
    if _SUPPORTED_CACHE.get("at", 0) > now - 600:
        return _SUPPORTED_CACHE["res"]
    path = f"{FACILITATOR_ROUTE}/supported"
    try:
        headers = {"Authorization": "Bearer " + cdp_jwt(cfg["key_id"], cfg["secret"], "GET", path)}
    except Exception:
        res = {"ok": False, "reason": "key_unreadable"}
    else:
        try:
            if get is None:
                import httpx
                async with httpx.AsyncClient(timeout=20, trust_env=False) as c:
                    r = await c.get(f"https://{FACILITATOR_HOST}{path}", headers=headers)
                    status, data = r.status_code, (r.json() if r.content else {})
            else:
                status, data = await get(f"https://{FACILITATOR_HOST}{path}", headers)
            kinds = data.get("kinds") or []
            base_exact = any(k.get("network") == NETWORK and k.get("scheme") == "exact" for k in kinds if isinstance(k, dict))
            res = {"ok": status == 200 and base_exact, "http_status": status, "base_exact_supported": base_exact}
        except Exception as e:
            res = {"ok": False, "reason": type(e).__name__}
    _SUPPORTED_CACHE.update(at=now, res=res)
    return res


# --- the whole flow, framework-free (the Starlette route only adapts request/response) -----------------------
async def handle(service: dict, url: str, headers: dict, body: dict | None, run: Callable[[dict, str], Awaitable[dict]],
                 cfg: dict | None, post=None, is_disconnected: Callable[[], Awaitable[bool]] | None = None) -> tuple[int, dict, dict]:
    """Returns (status, response headers, JSON body).

    25/10 (Andrea: "gli utenti non devono perdere soldi"). The buyer is charged only when they get a result:
    - nothing is settled unless the result is a real one (any ok=false result is free, ours or theirs);
    - nothing is settled if the buyer has already hung up;
    - if the settlement answer is lost (timeout, facilitator HTTP error) the money may have moved, so the result is
      delivered anyway, marked unconfirmed: in doubt, neo gives the result away rather than keep the money;
    - an explicit settlement failure means no money moved: 402, no result."""
    if cfg is None:
        return 503, {}, {"ok": False, "error": "x402_not_enabled"}
    req = requirements(service["price_usd"], cfg["pay_to"])
    payload, version = decode_payment(headers)
    if payload is None:  # 24/10 (x402scan spec): an unpaid probe gets the 402 even with an empty or invalid body
        _count("asked_to_pay", service)
        h, b = payment_required(service, url, cfg["pay_to"])
        return 402, h, b
    if not isinstance(body, dict):
        _count("bad_input", service)
        return 400, {}, {"ok": False, "error": "invalid_json", "charged": False}
    bad = service["validate"](body) if service.get("validate") else None
    if bad:  # bad input is refused before the payment is verified or settled: nothing moves
        _count("bad_input", service)
        return 400, {}, {"ok": False, "error": bad, "charged": False}
    why = accepted_matches(payload, req, version)
    if why:
        _count("wrong_terms", service)
        h, b = payment_required(service, url, cfg["pay_to"], error=why)
        return 402, h, b
    v = await facilitator(cfg, "verify", version, payload, req, post)
    if not v.get("isValid"):
        _count("payment_invalid", service)
        h, b = payment_required(service, url, cfg["pay_to"], error=str(v.get("invalidReason") or v.get("errorReason") or "payment_invalid"))
        return 402, h, b
    try:
        result = await run(body, str(v.get("payer") or "unknown"))  # computed, not released until settlement succeeds
    except Exception as e:  # a crash on our side: nothing is settled
        _count("our_failure_not_charged", service)
        return 503, {}, {"ok": False, "error": f"internal_{type(e).__name__}", "charged": False}
    if not isinstance(result, dict) or result.get("ok") is False:
        ours = str((result or {}).get("error") or "").startswith(tuple(service.get("no_charge_errors", ()))) if isinstance(result, dict) else True
        _count("our_failure_not_charged" if ours else "failed_result_not_charged", service)
        out = result if isinstance(result, dict) else {"ok": False, "error": "internal_bad_result"}
        return (503 if ours else 422), {}, {**out, "charged": False}  # no real result: do not settle
    if is_disconnected is not None:
        try:
            gone = await is_disconnected()
        except Exception:
            gone = False
        if gone:  # the buyer hung up while we worked: they would pay for nothing
            _count("client_gone_not_charged", service)
            return 499, {}, {"ok": False, "error": "client_disconnected", "charged": False}
    try:
        s = await facilitator(cfg, "settle", version, payload, req, post)
    except Exception as e:
        s = {"_http": None, "success": False, "errorReason": f"settle_exception_{type(e).__name__}"}
    if not s.get("success") and ("_http" in s):  # no answer we can trust: the transfer may have happened
        _count("settle_uncertain_delivered", service)
        settle = {"success": None, "status": "unconfirmed", "network": NETWORK, "reason": str(s.get("errorReason"))[:80],
                  "note": "we could not confirm the settlement; the result is delivered anyway"}
        return 200, {}, {**result, "payment": settle}
    if not s.get("success"):
        _count("settle_failed", service)
        h, b = payment_required(service, url, cfg["pay_to"], error=str(s.get("errorReason") or "settlement_failed"))
        return 402, h, {**b, "charged": False}
    _count("paid_and_served", service)
    settle = {"success": True, "transaction": s.get("transaction"), "network": s.get("network") or NETWORK, "payer": s.get("payer")}
    return 200, {"PAYMENT-RESPONSE": base64.b64encode(json.dumps(settle, separators=(",", ":")).encode()).decode()}, \
        {**result, "payment": settle}
