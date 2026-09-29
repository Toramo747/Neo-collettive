from __future__ import annotations

import base64
import secrets
from copy import deepcopy
from datetime import datetime, timedelta, timezone

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

DOMAIN_PREFIX="mycelix-handshake-v1"
DEFAULT_TTL_SECONDS=300


def _now(value: datetime|None=None) -> datetime:
    value=value or datetime.now(timezone.utc)
    if value.tzinfo is None:
        value=value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def challenge_message(thread_id: str, nonce: str) -> str:
    return f"{DOMAIN_PREFIX}|{str(thread_id)}|{str(nonce)}"


def _load_key(public_key: str) -> Ed25519PublicKey:
    try:
        key=serialization.load_ssh_public_key(str(public_key or "").encode("utf-8"))
    except Exception as exc:
        raise ValueError("malformed_public_key") from exc
    if not isinstance(key,Ed25519PublicKey):
        raise ValueError("unsupported_public_key_type")
    return key


def create_handshake_challenge(
    store: dict|None,
    *,
    thread_id: str,
    public_key: str,
    ttl_seconds: int=DEFAULT_TTL_SECONDS,
    now: datetime|None=None,
    nonce: str|None=None,
) -> tuple[dict,dict]:
    """Create an in-band, one-time key-possession challenge. No network is used."""
    thread_id=str(thread_id or "").strip()
    if not thread_id:
        raise ValueError("thread_id_required")
    _load_key(public_key)
    current=_now(now)
    ttl=max(30,min(int(ttl_seconds),900))
    token=str(nonce or secrets.token_urlsafe(32))
    out=deepcopy(store if isinstance(store,dict) else {})
    out[thread_id]={
        "thread_id":thread_id,
        "nonce":token,
        "public_key":str(public_key),
        "created_at_utc":current.isoformat(),
        "expires_at_utc":(current+timedelta(seconds=ttl)).isoformat(),
        "used":False,
    }
    return out,{
        "ok":True,
        "status":"CHALLENGE_ISSUED",
        "thread_id":thread_id,
        "nonce":token,
        "message":challenge_message(thread_id,token),
        "expires_at_utc":out[thread_id]["expires_at_utc"],
        "boundary":"Challenge proves only possession of the private key corresponding to the declared public key.",
    }


def verify_handshake_response(
    store: dict|None,
    *,
    thread_id: str,
    nonce: str,
    signature_b64: str,
    now: datetime|None=None,
) -> tuple[dict,dict]:
    """Verify the exact domain-separated challenge and consume it only on success."""
    out=deepcopy(store if isinstance(store,dict) else {})
    row=out.get(str(thread_id or ""))
    if not isinstance(row,dict):
        return out,{"ok":False,"status":"NO_CHALLENGE","reason":"challenge_not_found"}
    if bool(row.get("used")):
        return out,{"ok":False,"status":"REJECTED","reason":"nonce_reused"}
    if str(nonce or "") != str(row.get("nonce") or ""):
        return out,{"ok":False,"status":"REJECTED","reason":"nonce_mismatch"}
    current=_now(now)
    try:
        expires=datetime.fromisoformat(str(row.get("expires_at_utc") or "").replace("Z","+00:00"))
        if expires.tzinfo is None:
            expires=expires.replace(tzinfo=timezone.utc)
    except Exception:
        return out,{"ok":False,"status":"REJECTED","reason":"invalid_expiry"}
    if current > expires:
        return out,{"ok":False,"status":"REJECTED","reason":"nonce_expired"}
    try:
        key=_load_key(str(row.get("public_key") or ""))
        signature=base64.b64decode(str(signature_b64 or ""),validate=True)
        key.verify(signature,challenge_message(str(thread_id),str(nonce)).encode("utf-8"))
    except ValueError as exc:
        reason=str(exc) if str(exc) in {"malformed_public_key","unsupported_public_key_type"} else "malformed_signature"
        return out,{"ok":False,"status":"REJECTED","reason":reason}
    except (InvalidSignature,TypeError):
        return out,{"ok":False,"status":"REJECTED","reason":"invalid_signature_or_domain"}

    row=dict(row)
    row["used"]=True
    row["verified_at_utc"]=current.isoformat()
    out[str(thread_id)]=row
    return out,{
        "ok":True,
        "status":"KEY_POSSESSION_VERIFIED",
        "reason":"valid_ed25519_signature_for_domain_separated_nonce",
        "thread_id":str(thread_id),
        "key_possession_verified":True,
        "admission_changed":False,
        "authorization_changed":False,
        "boundary":"This establishes only possession of the private key corresponding to the declared public key; it does not establish autonomy, independence, reputation, admission, trust, or authorization.",
    }
