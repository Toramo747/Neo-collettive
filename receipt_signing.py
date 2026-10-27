# SPDX-License-Identifier: BUSL-1.1
"""Portable Ed25519 receipts. No I/O except reading the optional signing env var."""
import base64
import binascii
import hashlib
import json
import os
import re
from datetime import datetime, timezone

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat


def canonical_json(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def load_key():
    """Missing or invalid configuration disables signing without logging secrets."""
    seed = os.environ.get("NEO_RECEIPT_SIGNING_KEY", "")
    if re.fullmatch(r"[0-9a-fA-F]{64}", seed) is None:
        return None
    try:
        return Ed25519PrivateKey.from_private_bytes(bytes.fromhex(seed))
    except ValueError:
        return None


def key_id(pub) -> str:
    raw = pub.public_bytes(Encoding.Raw, PublicFormat.Raw)
    return "neo-receipt-" + hashlib.sha256(raw).hexdigest()[:16]


def public_key_info(key):
    """Only public material, shared by discovery and the receipt signer."""
    if key is None:
        return None
    pub = key.public_key()
    return {
        "alg": "Ed25519",
        "key_id": key_id(pub),
        "public_key_b64": base64.b64encode(pub.public_bytes(Encoding.Raw, PublicFormat.Raw)).decode("ascii"),
        "verify": "remove 'signature', canonical JSON (sorted keys, compact, UTF-8), Ed25519 verify",
    }


def sign_receipt(result: dict, key, log: dict | None = None, tool: str = "verify_quote") -> dict:
    obj = dict(result)
    obj.pop("signature", None)
    obj["receipt"] = {
        "v": 1,
        "tool": tool,
        "issuer": "neo (OSIXBAY)",
        "key_id": key_id(key.public_key()),
        "issued_at_utc": datetime.now(timezone.utc).isoformat(),
        "alg": "Ed25519",
        "canonical": "json-sorted-compact-utf8",
    }
    if log:  # position in the public receipt log (receipt_log.py), covered by the signature
        obj["receipt"]["log"] = {"seq": int(log["seq"]), "prev": str(log["prev"])}
    obj["signature"] = base64.urlsafe_b64encode(key.sign(canonical_json(obj))).rstrip(b"=").decode("ascii")
    return obj


def verify_receipt(obj: dict, public_key_b64: str) -> bool:
    """Copyable verifier; malformed input and invalid signatures return False."""
    try:
        payload = dict(obj)
        encoded = payload.pop("signature")
        if not isinstance(encoded, str) or re.fullmatch(r"[A-Za-z0-9_-]{86}", encoded) is None:
            return False
        signature = base64.b64decode(encoded + "==", altchars=b"-_", validate=True)
        # 24/10 (skitter): one accepted encoding per signature, no spare-bit variants of the last character
        if base64.urlsafe_b64encode(signature).rstrip(b"=").decode("ascii") != encoded:
            return False
        public_key = Ed25519PublicKey.from_public_bytes(base64.b64decode(public_key_b64, validate=True))
        public_key.verify(signature, canonical_json(payload))
        return True
    except (InvalidSignature, ValueError, TypeError, KeyError, binascii.Error, UnicodeError):
        return False


# --- 27/10: the official x402 "Offer and Receipt" extension (JWS, EdDSA) ----------------------------------------
def _b64u(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode("ascii")


def did_web(host: str) -> str:
    """did:web for the service host (spec: signer authorization via a DID document at /.well-known/did.json)."""
    return "did:web:" + host.replace(":", "%3A")


def did_document(key, host: str) -> dict:
    pub = key.public_key()
    raw = pub.public_bytes(Encoding.Raw, PublicFormat.Raw)
    did = did_web(host)
    vm = {"id": f"{did}#{key_id(pub)}", "type": "JsonWebKey2020", "controller": did,
          "publicKeyJwk": {"kty": "OKP", "crv": "Ed25519", "x": _b64u(raw)}}
    return {"@context": ["https://www.w3.org/ns/did/v1", "https://w3id.org/security/suites/jws-2020/v1"], "id": did,
            "verificationMethod": [vm], "assertionMethod": [vm["id"]],
            "service": [{"id": f"{did}#receipt-log", "type": "TransparencyLog",
                         "serviceEndpoint": f"https://{host}/receipts/log"}]}


def offer_receipt_jws(payload: dict, key, host: str) -> str:
    """JWS compact (EdDSA) over an offer or receipt payload, kid = the did:web key URL."""
    header = {"alg": "EdDSA", "kid": f"{did_web(host)}#{key_id(key.public_key())}", "typ": "JWT"}
    signing = _b64u(canonical_json(header)) + "." + _b64u(canonical_json(payload))
    return signing + "." + _b64u(key.sign(signing.encode("ascii")))


def official_offer(key, host: str, resource_url: str, req: dict, valid_until: int = 0) -> dict:
    payload = {"version": 1, "resourceUrl": resource_url, "scheme": req["scheme"], "network": req["network"],
               "asset": req["asset"], "payTo": req["payTo"], "amount": str(req["amount"]), "validUntil": int(valid_until)}
    return {"format": "jws", "acceptIndex": 0, "signature": offer_receipt_jws(payload, key, host)}


def official_receipt(key, host: str, resource_url: str, network: str, payer: str, transaction: str | None,
                     issued_at: int | None = None) -> dict:
    import time as _t
    payload = {"version": 1, "network": network, "resourceUrl": resource_url, "payer": str(payer or ""),
               "issuedAt": int(issued_at if issued_at is not None else _t.time())}
    if transaction:
        payload["transaction"] = str(transaction)
    return {"format": "jws", "signature": offer_receipt_jws(payload, key, host)}
