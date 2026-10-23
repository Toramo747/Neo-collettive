#!/usr/bin/env python3
"""x402 delivery receipt v0 (draft, 23/10): what a paid call asked, sent and settled, signed and logged.

Spec: docs/spec/X402-DELIVERY-RECEIPT-v0.md (fields from skitter's review of two real cases, 23/10).
This module is the reference: build a receipt (seller), add a hop (relay), verify (anyone).

  python tools/delivery_receipt.py verify <receipt.json> <seller_pub_b64> [buyer_body_file] [hop_name=pub_b64 ...]
  python tools/delivery_receipt.py example <out.json>     a signed example with one relay, for reviewers

Verification never trusts free text: every finding is a comparison of hashes, times or signatures.
"""
from __future__ import annotations

import base64
import hashlib
import json
import re
import sys
from datetime import datetime
from pathlib import Path

OUTCOMES = ("delivered", "refused", "served_not_settled")
REFUSALS = ("payment_invalid", "payment_expired", "upstream_failed", "rate_limited", "policy")
REQUIRED = {"v", "type", "seller", "buyer_request_id", "route", "request_sha256", "payment_required", "payment",
            "outcome", "refusal_code", "times", "response_sha256", "log"}
HEX64 = re.compile(r"[0-9a-f]{64}")


def canonical_json(obj) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _sign(key, obj) -> str:
    return base64.urlsafe_b64encode(key.sign(canonical_json(obj))).rstrip(b"=").decode()


def _ok(pub_b64: str, obj, sig: str) -> bool:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    try:
        Ed25519PublicKey.from_public_bytes(base64.b64decode(pub_b64, validate=True)).verify(
            base64.urlsafe_b64decode(sig + "=" * (-len(sig) % 4)), canonical_json(obj))
        return True
    except Exception:
        return False


def seller_body(r: dict) -> dict:
    """What the seller signs: everything except its own signature and the hops relays add later."""
    return {k: v for k, v in r.items() if k not in ("signature", "hops")}


def sign_seller(receipt: dict, key) -> dict:
    r = dict(receipt)
    r.pop("hops", None)
    r["signature"] = _sign(key, seller_body(r))
    r["hops"] = []
    return r


def add_hop(receipt: dict, name: str, key, received: bytes, forwarded: bytes, at_utc: str) -> dict:
    r = json.loads(json.dumps(receipt))
    hop = {"name": name, "receipt_sha256": sha(canonical_json(seller_body(receipt) | {"signature": receipt["signature"]})),
           "received_sha256": sha(received), "forwarded_sha256": sha(forwarded), "at_utc": at_utc}
    hop["signature"] = _sign(key, hop)
    r["hops"].append(hop)
    return r


def _t(s):
    return datetime.fromisoformat(str(s).replace("Z", "+00:00"))


def verify(r: dict, seller_pub: str, buyer_body_sha256: str | None = None, hop_pubs: dict | None = None) -> dict:
    """Returns {"ok": bool, "fails": [...], "notes": [...], "changed_by": hop name or None}."""
    fails, notes = [], []
    keys = set(r)
    if not REQUIRED <= keys:
        fails.append(f"missing fields: {sorted(REQUIRED - keys)}")
        return {"ok": False, "fails": fails, "notes": notes, "changed_by": None}
    if r.get("v") != 0 or r.get("type") != "x402-delivery-receipt":
        fails.append("v must be 0 and type x402-delivery-receipt")
    if not _ok(seller_pub, seller_body(r), str(r.get("signature") or "")):
        fails.append("seller signature does not verify with the published key")
    for path, val in (("request_sha256", r["request_sha256"]), ("response_sha256", r["response_sha256"]),
                      ("payment_required.body_sha256", (r["payment_required"] or {}).get("body_sha256")),
                      ("payment_required.header_sha256", (r["payment_required"] or {}).get("header_sha256"))):
        if not HEX64.fullmatch(str(val or "")):
            fails.append(f"{path} must be 64 lowercase hex")
    pr = r["payment_required"] or {}
    if pr.get("body_x402_version") != pr.get("header_x402_version"):
        notes.append(f"payment requirements disagree: body v{pr.get('body_x402_version')} vs header v{pr.get('header_x402_version')}")
    out, code, pay, t = r["outcome"], r["refusal_code"], r["payment"] or {}, r["times"] or {}
    if out not in OUTCOMES:
        fails.append(f"outcome must be one of {OUTCOMES}")
    if out == "refused":
        if code not in REFUSALS:
            fails.append(f"a refusal needs a code from {REFUSALS}")
        if pay.get("tx"):
            fails.append("a refused call cannot carry a settlement tx")
    elif code is not None:
        fails.append("refusal_code must be null unless outcome is refused")
    if out == "delivered" and not re.fullmatch(r"0x[0-9a-fA-F]{64}", str(pay.get("tx") or "")):
        fails.append("delivered needs the settlement tx")
    try:
        sent = _t(t["response_sent_utc"])
        if out == "delivered":
            seen = _t(t["settlement_seen_utc"])
            gap = (seen - sent).total_seconds()
            notes.append(f"response left {abs(gap):.1f} s {'before' if gap > 0 else 'after'} the seller saw settlement")
    except Exception:
        fails.append("times need response_sent_utc (and settlement_seen_utc when delivered), ISO 8601 UTC")
    # hops: the chain of hashes from the seller's response to what the buyer holds
    prev, changed = r["response_sha256"], None
    for i, h in enumerate(r.get("hops") or []):
        body = {k: v for k, v in h.items() if k != "signature"}
        pub = (hop_pubs or {}).get(h.get("name"))
        if pub and not _ok(pub, body, str(h.get("signature") or "")):
            fails.append(f"hop {i} ({h.get('name')}): signature does not verify")
        elif not pub:
            notes.append(f"hop {i} ({h.get('name')}): no published key given, signature not checked")
        if h.get("received_sha256") != prev:
            fails.append(f"hop {i} ({h.get('name')}) received bytes that differ from what the previous hop sent")
        if h.get("forwarded_sha256") != h.get("received_sha256") and changed is None:
            changed = h.get("name")
            notes.append(f"hop {i} ({h.get('name')}) changed the bytes and says so")
        prev = h.get("forwarded_sha256")
    if buyer_body_sha256 is not None and buyer_body_sha256 != prev:
        fails.append("the buyer's bytes differ from what the last signed hop sent: the change is unattributed")
    return {"ok": not fails, "fails": fails, "notes": notes, "changed_by": changed}


def example() -> tuple[dict, dict]:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    def pair():
        k = Ed25519PrivateKey.generate()
        return k, base64.b64encode(k.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)).decode()
    sk, spub = pair()
    rk, rpub = pair()
    resp = b'{"symbol":"BTCUSDT","funding":"0.0001","token":"abc"}'
    redacted = b'{"symbol":"BTCUSDT","funding":"0.0001","token":"[redacted]"}'
    r = {"v": 0, "type": "x402-delivery-receipt",
         "seller": {"name": "example-seller", "key_id": "ed25519:example", "key_url": "https://seller.example/.well-known/agent-card.json"},
         "buyer_request_id": "buyer-req-0001",
         "route": {"method": "GET", "url": "https://seller.example/api/funding?symbol=BTCUSDT"},
         "request_sha256": sha(b"GET /api/funding?symbol=BTCUSDT"),
         "payment_required": {"body_sha256": sha(b"{402 body}"), "header_sha256": sha(b"PAYMENT-REQUIRED header"),
                              "body_x402_version": 2, "header_x402_version": 2},
         "payment": {"network": "eip155:8453", "asset": "0x833589fCD6eDb6E08f4c7C32D4F71b54bdA02913",
                     "amount": "2000", "pay_to": "0x" + "a" * 40, "payer": "0x" + "b" * 40, "tx": "0x" + "c" * 64},
         "outcome": "delivered", "refusal_code": None,
         "times": {"response_sent_utc": "2026-10-23T10:12:17.622Z", "settlement_seen_utc": "2026-10-23T10:12:21.000Z",
                   "settlement_block_time_utc": "2026-10-23T10:12:21Z"},
         "response_sha256": sha(resp), "log": {"name": "example-seller-receipts", "seq": 42, "prev": "0" * 64}}
    r = sign_seller(r, sk)
    r = add_hop(r, "example-relay", rk, resp, redacted, "2026-10-23T10:12:22Z")
    return r, {"seller_pub": spub, "hop_pubs": {"example-relay": rpub}, "buyer_body_sha256": sha(redacted)}


if __name__ == "__main__":
    a = sys.argv
    if len(a) == 3 and a[1] == "example":
        r, keys = example()
        Path(a[2]).write_text(json.dumps({"receipt": r, "keys": keys}, indent=1))
        print(json.dumps(verify(r, keys["seller_pub"], keys["buyer_body_sha256"], keys["hop_pubs"]), indent=1))
        sys.exit(0)
    if len(a) >= 4 and a[1] == "verify":
        r = json.loads(Path(a[2]).read_text())
        body = sha(Path(a[4]).read_bytes()) if len(a) > 4 and "=" not in a[4] else None
        hops = dict(x.split("=", 1) for x in a[4:] if "=" in x)
        res = verify(r, a[3], body, hops)
        print(json.dumps(res, indent=1))
        sys.exit(0 if res["ok"] else 1)
    print(__doc__)
    sys.exit(2)
