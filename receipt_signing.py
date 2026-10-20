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


def sign_receipt(result: dict, key, log: dict | None = None) -> dict:
    obj = dict(result)
    obj.pop("signature", None)
    obj["receipt"] = {
        "v": 1,
        "tool": "verify_quote",
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
        public_key = Ed25519PublicKey.from_public_bytes(base64.b64decode(public_key_b64, validate=True))
        public_key.verify(signature, canonical_json(payload))
        return True
    except (InvalidSignature, ValueError, TypeError, KeyError, binascii.Error, UnicodeError):
        return False
