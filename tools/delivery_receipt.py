#!/usr/bin/env python3
"""x402 delivery receipt v0.1 (draft, 23/10; v0.1 adds skitter's second review: settlement kind, charged, payee/facilitator check, seller_unavailable, test vectors): what a paid call asked, sent and settled, signed and logged.

Spec: docs/spec/X402-DELIVERY-RECEIPT-v0.md (fields from skitter's review of two real cases, 23/10).
This module is the reference: build a receipt (seller), add a hop (relay), verify (anyone).

  python tools/delivery_receipt.py verify <receipt.json> <seller_pub_b64> [buyer_body_file] [hop_name=pub_b64 ...]
  python tools/delivery_receipt.py example <out.json>     a signed example with one relay, for reviewers
  python tools/delivery_receipt.py vectors <out.json>     the published test vectors (fixed public test key)

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
REFUSALS = ("payment_invalid", "payment_expired", "upstream_failed", "rate_limited", "policy", "seller_unavailable")
SETTLEMENTS = ("onchain", "internal", "none")  # v0.1 (skitter): say "no chain leg" in a field, not by omission
REQUIRED = {"v", "type", "seller", "buyer_request_id", "route", "request_sha256", "payment_required", "payment",
            "outcome", "refusal_code", "charged", "settlement", "times", "response_sha256", "log"}
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
        raw = base64.urlsafe_b64decode(sig + "=" * (-len(sig) % 4))
        # 24/10 (skitter, BREAK 3): one accepted encoding per signature; the spare bits of the last character
        # would otherwise give several valid strings for one signature (and several receipt hashes)
        if len(raw) != 64 or base64.urlsafe_b64encode(raw).rstrip(b"=").decode() != sig:
            return False
        Ed25519PublicKey.from_public_bytes(base64.b64decode(pub_b64, validate=True)).verify(raw, canonical_json(obj))
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


def check_transfer(r: dict, transfer: dict) -> list[str]:
    """v0.1: compare the receipt with the USDC Transfer log read from the chain by the verifier itself:
    to must be the payee the seller asked for in its 402; from must be the payer seen or the named facilitator."""
    pay = r.get("payment") or {}
    fails = []
    if str(transfer.get("to", "")).lower() != str(pay.get("pay_to_requested", "")).lower():
        fails.append("Transfer.to is not the payTo the seller signed")
    if str(transfer.get("from", "")).lower() not in {str(pay.get("payer_seen", "")).lower(), str(pay.get("facilitator_wallet", "")).lower()}:
        fails.append("Transfer.from is neither the payer seen nor the named facilitator wallet")
    if str(transfer.get("amount")) != str(pay.get("amount")):
        fails.append("Transfer amount differs from the signed amount")
    return fails


def _t(s):
    return datetime.fromisoformat(str(s).replace("Z", "+00:00"))


def verify(r: dict, seller_pub: str, buyer_body_sha256: str | None = None, hop_pubs: dict | None = None) -> dict:
    """Returns {"ok": bool, "fails": [...], "notes": [...], "changed_by": hop name or None}."""
    fails, notes = [], []
    keys = set(r)
    if not REQUIRED <= keys:
        fails.append(f"missing fields: {sorted(REQUIRED - keys)}")
        return {"ok": False, "fails": fails, "notes": notes, "changed_by": None}
    if r.get("v") != "0.1" or r.get("type") != "x402-delivery-receipt":
        fails.append('v must be "0.1" and type x402-delivery-receipt')
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
    st, charged = r["settlement"] or {}, r["charged"]
    if not isinstance(charged, bool):
        fails.append("charged must be true or false, also on refusals")
    if st.get("kind") not in SETTLEMENTS:
        fails.append(f"settlement.kind must be one of {SETTLEMENTS}")
    if st.get("kind") == "onchain" and not re.fullmatch(r"0x[0-9a-fA-F]{64}", str(pay.get("tx") or "")):
        fails.append("an onchain settlement needs the tx")
    if st.get("kind") != "onchain" and pay.get("tx"):
        fails.append("a tx is only allowed with an onchain settlement")
    if st.get("kind") == "internal" and not st.get("cost_carried_by"):
        fails.append("an internal settlement must name who carried the cost")
    if st.get("kind") == "none" and charged is True:
        fails.append("charged with no settlement at all")
    if st.get("kind") == "onchain" and pay.get("tx") and charged is False:
        fails.append("charged false contradicts an onchain settlement with a tx")  # 24/10, skitter BREAK 1
    if out == "served_not_settled" and charged is True:
        fails.append("served_not_settled cannot be charged")
    if out == "delivered" and st.get("kind") == "none":
        fails.append("delivered needs a settlement (onchain or internal)")
    if out == "refused" and charged is True:
        notes.append("refused but charged: the seller signs that money moved for a refused call")
    if st.get("kind") == "onchain":
        for f in ("pay_to_requested", "facilitator"):
            if not pay.get(f):
                fails.append(f"payment.{f} is required for an onchain settlement (the verifier checks the Transfer log against it)")
    try:
        sent = _t(t["response_sent_utc"])
        if out == "delivered":
            seen = _t(t["settlement_seen_utc"])
            gap = (seen - sent).total_seconds()
            notes.append(f"response left {abs(gap):.1f} s {'before' if gap > 0 else 'after'} the seller saw settlement")
    except Exception:
        fails.append("times need response_sent_utc (and settlement_seen_utc when delivered), ISO 8601 UTC")
    # hops: the chain of hashes from the seller's response to what the buyer holds
    prev, changed, unverified_change = r["response_sha256"], None, None
    this_receipt = sha(canonical_json(seller_body(r) | {"signature": r.get("signature")}))
    for i, h in enumerate(r.get("hops") or []):
        body = {k: v for k, v in h.items() if k != "signature"}
        pub = (hop_pubs or {}).get(h.get("name"))
        signed_ok = bool(pub) and _ok(pub, body, str(h.get("signature") or ""))
        if pub and not signed_ok:
            fails.append(f"hop {i} ({h.get('name')}): signature does not verify")
        elif not pub:
            notes.append(f"hop {i} ({h.get('name')}): no published key given, signature not checked")
        if h.get("receipt_sha256") != this_receipt:  # 24/10, skitter BREAK 2: a signed hop cannot move between receipts
            fails.append(f"hop {i} ({h.get('name')}) was signed for a different receipt")
        if h.get("received_sha256") != prev:
            fails.append(f"hop {i} ({h.get('name')}) received bytes that differ from what the previous hop sent")
        if h.get("forwarded_sha256") != h.get("received_sha256") and changed is None and unverified_change is None:
            if signed_ok:
                changed = h.get("name")
                notes.append(f"hop {i} ({h.get('name')}) changed the bytes and says so")
            else:  # 24/10, skitter: never blame a name whose signature nobody checked
                unverified_change = h.get("name")
                notes.append(f"hop {i} claims to be {h.get('name')!r} and changed the bytes, but its signature was not checked")
        prev = h.get("forwarded_sha256")
    if buyer_body_sha256 is not None and buyer_body_sha256 != prev:
        fails.append("the buyer's bytes differ from what the last signed hop sent: the change is unattributed")
    asset = str(pay.get("asset") or "")
    if re.fullmatch(r"0x[0-9a-fA-F]{40}", asset) and asset[2:] not in (asset[2:].lower(), asset[2:].upper()):
        try:
            import importlib.util as _u
            _s = _u.spec_from_file_location("x402_lint", Path(__file__).with_name("x402_lint.py"))
            _m = _u.module_from_spec(_s)
            _s.loader.exec_module(_m)
            if _m.checksum(asset) != asset:  # 24/10, skitter: a note, compared case-insensitively, not a fail
                notes.append(f"payment.asset fails EIP-55 (checksum spelling {_m.checksum(asset)}); addresses compare case-insensitively")
        except Exception:  # 25/10, skitter: never stay silent when the check could not run
            notes.append("payment.asset uses mixed case but its EIP-55 spelling was not checked (x402_lint.py not available)")
    return {"ok": not fails, "fails": fails, "notes": notes, "changed_by": changed, "changed_by_unverified": unverified_change}


_B64URL = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"


def _non_canonical(sig: str) -> str:
    """Same 64 bytes, different spelling: set one of the 4 padding bits of the last char (25/10, skitter:
    the old fallback to "A" changed real bits for signatures ending in Q, g or w)."""
    i = _B64URL.index(sig[-1])
    return sig[:-1] + _B64URL[(i & ~0xF) | ((i & 0xF) ^ 1)]


def vectors() -> dict:
    """v0.1 (skitter): test vectors a seller can check its own output against before going live."""
    import copy
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    good, keys = example()
    # rebuild with a fixed, published TEST key so the vectors are reproducible (never use it for real receipts)
    sk = Ed25519PrivateKey.from_private_bytes(hashlib.sha256(b"x402-delivery-receipt-v0.1 test key, public, do not use").digest())
    spub = base64.b64encode(sk.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)).decode()
    base = seller_body(good)
    plain = sign_seller(dict(base), sk)
    refusal = dict(base, outcome="refused", refusal_code="seller_unavailable", charged=False, settlement={"kind": "none"},
                   payment=dict(base["payment"], tx=None), response_sha256=sha(b'{"error":"service_unavailable"}'),
                   times={"response_sent_utc": "2026-10-23T10:12:17.622Z"})
    refusal = sign_seller(refusal, sk)
    hop = add_hop(plain, "example-relay", sk, b'{"symbol":"BTCUSDT","funding":"0.0001","token":"abc"}',
                  b'{"symbol":"BTCUSDT","funding":"0.0001","token":"[redacted]"}', "2026-10-23T10:12:22Z")
    return {"test_key_public_b64": spub, "note": "hop signed with the same test key, for brevity",
            "vectors": [
                {"name": "good-delivered", "receipt": plain, "expect": {"ok": True, "changed_by": None}},
                {"name": "hop-changed-bytes", "receipt": hop, "hop_pubs": {"example-relay": spub},
                 "buyer_body_sha256": sha(b'{"symbol":"BTCUSDT","funding":"0.0001","token":"[redacted]"}'),
                 "expect": {"ok": True, "changed_by": "example-relay"}},
                {"name": "refused-not-charged", "receipt": refusal, "expect": {"ok": True, "changed_by": None}},
                {"name": "tampered-amount", "receipt": copy.deepcopy(plain) | {"payment": dict(plain["payment"], amount="1")},
                 "expect": {"ok": False}},
                # 24/10: skitter's three BREAKs and his asset-spelling suggestion, kept as regression vectors
                {"name": "charged-false-with-onchain-tx", "receipt": sign_seller(dict(base, charged=False), sk), "expect": {"ok": False}},
                {"name": "hop-signed-for-another-receipt", "receipt": dict(copy.deepcopy(plain), hops=add_hop(
                    sign_seller(dict(base, buyer_request_id="some-other-request"), sk), "example-relay", sk,
                    b'{"symbol":"BTCUSDT","funding":"0.0001","token":"abc"}', b'{"symbol":"BTCUSDT","funding":"0.0001","token":"abc"}',
                    "2026-10-23T10:12:22Z")["hops"]), "hop_pubs": {"example-relay": spub}, "expect": {"ok": False}},
                {"name": "non-canonical-signature", "receipt": dict(plain, signature=_non_canonical(plain["signature"])),
                 "expect": {"ok": False}},
                {"name": "asset-non-checksum-spelling-is-a-note", "receipt": sign_seller(dict(base, payment=dict(
                    base["payment"], asset="0x833589fCD6eDb6E08f4c7C32D4F71b54bdA02913")), sk),
                 "expect": {"ok": True, "note_contains": "fails EIP-55"}}]}


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
    r = {"v": "0.1", "type": "x402-delivery-receipt",
         "seller": {"name": "example-seller", "key_id": "ed25519:example", "key_url": "https://seller.example/.well-known/agent-card.json"},
         "buyer_request_id": "buyer-req-0001",
         "route": {"method": "GET", "url": "https://seller.example/api/funding?symbol=BTCUSDT"},
         "request_sha256": sha(b"GET /api/funding?symbol=BTCUSDT"),
         "payment_required": {"body_sha256": sha(b"{402 body}"), "header_sha256": sha(b"PAYMENT-REQUIRED header"),
                              "body_x402_version": 2, "header_x402_version": 2},
         "payment": {"network": "eip155:8453", "asset": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
                     "amount": "2000", "pay_to_requested": "0x" + "a" * 40, "payer_seen": "0x" + "b" * 40,
                     "facilitator": "example-facilitator", "facilitator_wallet": "0x" + "d" * 40, "tx": "0x" + "c" * 64},
         "outcome": "delivered", "refusal_code": None, "charged": True, "settlement": {"kind": "onchain"},
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
    if len(a) == 3 and a[1] == "vectors":
        Path(a[2]).write_text(json.dumps(vectors(), indent=1) + "\n")
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
