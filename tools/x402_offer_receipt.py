# SPDX-License-Identifier: BUSL-1.1
"""Verifier for the official x402 "Offer and Receipt" extension (27/10, Andrea's plan).

Spec: coinbase/x402 specs/extensions/extension-offer-and-receipt.md. Both formats:
  - eip712: payload + 65-byte secp256k1 signature; domain {name: "x402 offer"|"x402 receipt", version: "1", chainId: 1};
    the signer address is recovered (pure Python, no extra dependency) and compared with what should have signed.
  - jws: compact string; alg EdDSA (Ed25519), ES256K (secp256k1) or ES256 (P-256); kid is a DID URL. did:jwk and
    did:key (Ed25519) resolve offline; did:web needs the caller to pass a fetched DID document (the service fetches it).
It separates three things the spec separates: is the signature valid, is the signer authorized for resourceUrl, and do
the signed fields match the terms or the payment they are checked against. It never decides that a service is honest.
"""
from __future__ import annotations

import base64
import hashlib
import importlib.util
import json
import re
import time
from pathlib import Path
from urllib.parse import urlparse

_spec = importlib.util.spec_from_file_location("x402_lint", Path(__file__).with_name("x402_lint.py"))
_lint = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_lint)
keccak256 = _lint.keccak256

# --- secp256k1 (recovery only; signatures are checked against a recovered address) ---------------------------
P = 2**256 - 2**32 - 977
N = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141
G = (0x79BE667EF9DCBBAC55A06295CE870B07029BFCDB2DCE28D959F2815B16F81798,
     0x483ADA7726A3C4655DA4FBFC0E1108A8FD17B448A68554199C47D08FFB10D4B8)


def _add(a, b):
    if a is None:
        return b
    if b is None:
        return a
    if a[0] == b[0] and (a[1] + b[1]) % P == 0:
        return None
    if a == b:
        lam = 3 * a[0] * a[0] * pow(2 * a[1], -1, P) % P
    else:
        lam = (b[1] - a[1]) * pow(b[0] - a[0], -1, P) % P
    x = (lam * lam - a[0] - b[0]) % P
    return (x, (lam * (a[0] - x) - a[1]) % P)


def _mul(k, pt):
    out = None
    while k:
        if k & 1:
            out = _add(out, pt)
        pt = _add(pt, pt)
        k >>= 1
    return out


def recover_address(digest: bytes, sig: bytes) -> str | None:
    """Ethereum address that produced a 65-byte r||s||v signature over digest, or None."""
    if len(sig) != 65:
        return None
    r, s, v = int.from_bytes(sig[:32], "big"), int.from_bytes(sig[32:64], "big"), sig[64]
    v = v - 27 if v >= 27 else v
    if v not in (0, 1) or not (0 < r < N and 0 < s < N) or s > N // 2:  # low-s only, like EIP-2
        return None
    y2 = (pow(r, 3, P) + 7) % P
    y = pow(y2, (P + 1) // 4, P)
    if y * y % P != y2:
        return None
    if y % 2 != v:
        y = P - y
    R = (r, y)
    e = int.from_bytes(digest, "big")
    rinv = pow(r, -1, N)
    Q = _add(_mul(s * rinv % N, R), _mul((-e * rinv) % N, G))
    if Q is None:
        return None
    pub = Q[0].to_bytes(32, "big") + Q[1].to_bytes(32, "big")
    return _lint.checksum("0x" + keccak256(pub)[-20:].hex())


# --- EIP-712 (the two canonical schemas, version 1) -----------------------------------------------------------
TYPES = {
    "offer": ("Offer", [("version", "uint256"), ("resourceUrl", "string"), ("scheme", "string"), ("network", "string"),
                        ("asset", "string"), ("payTo", "string"), ("amount", "string"), ("validUntil", "uint256")]),
    "receipt": ("Receipt", [("version", "uint256"), ("network", "string"), ("resourceUrl", "string"), ("payer", "string"),
                            ("issuedAt", "uint256"), ("transaction", "string")]),
}
DOMAIN_NAME = {"offer": "x402 offer", "receipt": "x402 receipt"}


def _enc(t: str, v) -> bytes:
    if t == "string":
        return keccak256(str(v if v is not None else "").encode("utf-8"))
    return int(v or 0).to_bytes(32, "big")  # uint256: absent optional = 0


def eip712_digest(kind: str, payload: dict) -> bytes:
    name, fields = TYPES[kind]
    th = keccak256(f"{name}({','.join(f'{t} {n}' for n, t in fields)})".encode())
    struct = keccak256(th + b"".join(_enc(t, payload.get(n)) for n, t in fields))
    dth = keccak256(b"EIP712Domain(string name,string version,uint256 chainId)")
    dom = keccak256(dth + _enc("string", DOMAIN_NAME[kind]) + _enc("string", "1") + _enc("uint256", 1))
    return keccak256(b"\x19\x01" + dom + struct)


# --- JWS ------------------------------------------------------------------------------------------------------
def _b64u(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


_B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


def _b58decode(s: str) -> bytes:
    n = 0
    for ch in s:
        n = n * 58 + _B58.index(ch)
    raw = n.to_bytes((n.bit_length() + 7) // 8, "big")
    return b"\x00" * (len(s) - len(s.lstrip("1"))) + raw


def jwk_from_kid(kid: str, did_document: dict | None = None) -> tuple[dict | None, str]:
    """(public JWK, how it was found). did:jwk and did:key resolve offline; did:web uses the supplied document."""
    base, _, frag = kid.partition("#")
    if base.startswith("did:jwk:"):
        try:
            return json.loads(_b64u(base[len("did:jwk:"):])), "did:jwk (key inside the kid)"
        except Exception:
            return None, "did:jwk not decodable"
    if base.startswith("did:key:z"):
        try:
            raw = _b58decode(base[len("did:key:z"):])
        except Exception:
            return None, "did:key not decodable"
        if raw[:2] == b"\xed\x01" and len(raw) == 34:
            return {"kty": "OKP", "crv": "Ed25519", "x": base64.urlsafe_b64encode(raw[2:]).rstrip(b"=").decode()}, "did:key (Ed25519)"
        return None, "did:key type not supported (Ed25519 only)"
    if base.startswith("did:web:"):
        if not isinstance(did_document, dict):
            return None, "did:web needs its DID document"
        for vm in did_document.get("verificationMethod") or []:
            vid = str(vm.get("id") or "")
            if vid == kid or (frag and vid in (f"#{frag}", f"{base}#{frag}")):
                if isinstance(vm.get("publicKeyJwk"), dict):
                    return vm["publicKeyJwk"], "did:web document (current state only)"
                mb = str(vm.get("publicKeyMultibase") or "")
                if mb.startswith("z"):
                    raw = _b58decode(mb[1:])
                    raw = raw[2:] if raw[:2] == b"\xed\x01" else raw
                    if len(raw) == 32:
                        return {"kty": "OKP", "crv": "Ed25519", "x": base64.urlsafe_b64encode(raw).rstrip(b"=").decode()}, \
                            "did:web document (current state only)"
        return None, "kid not listed in the did:web document"
    return None, "kid method not supported (did:jwk, did:key, did:web)"


def did_web_url(kid: str) -> str | None:
    """https URL of the DID document for a did:web kid (spec: did-method-web)."""
    base = kid.partition("#")[0]
    if not base.startswith("did:web:"):
        return None
    parts = [p.replace("%3A", ":") for p in base[len("did:web:"):].split(":")]
    host, path = parts[0], parts[1:]
    return f"https://{host}/" + ("/".join(path) + "/did.json" if path else ".well-known/did.json")


def verify_jws(token: str, jwk: dict) -> bool:
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature
    try:
        h, p, s = token.split(".")
        alg = json.loads(_b64u(h)).get("alg")
        data, sig = f"{h}.{p}".encode(), _b64u(s)
        if alg == "EdDSA" and jwk.get("crv") == "Ed25519":
            Ed25519PublicKey.from_public_bytes(_b64u(jwk["x"])).verify(sig, data)
            return True
        curve = {"ES256K": (ec.SECP256K1(), "secp256k1"), "ES256": (ec.SECP256R1(), "P-256")}.get(alg)
        if curve and jwk.get("crv") == curve[1] and len(sig) == 64:
            pub = ec.EllipticCurvePublicNumbers(int.from_bytes(_b64u(jwk["x"]), "big"), int.from_bytes(_b64u(jwk["y"]), "big"),
                                                curve[0]).public_key()
            pub.verify(encode_dss_signature(int.from_bytes(sig[:32], "big"), int.from_bytes(sig[32:], "big")), data,
                       ec.ECDSA(hashes.SHA256()))
            return True
    except (InvalidSignature, ValueError, KeyError, TypeError, json.JSONDecodeError):
        return False
    return False


# --- the verdict ----------------------------------------------------------------------------------------------
OFFER_REQ = ("version", "resourceUrl", "scheme", "network", "asset", "payTo", "amount")
RECEIPT_REQ = ("version", "network", "resourceUrl", "payer", "issuedAt")


def _same_addr(a, b) -> bool:
    return isinstance(a, str) and isinstance(b, str) and a.lower() == b.lower()


def verify(artifact: dict, kind: str, did_document: dict | None = None, accepts: dict | None = None,
           pay_to: str | None = None, transaction: str | None = None, now: int | None = None) -> dict:
    """kind: "offer" or "receipt". accepts: the accepts[] entry an offer should commit to. pay_to: the address that
    should have signed (payTo signing). transaction: the settlement tx a receipt should name."""
    fails, notes = [], []
    now = int(time.time()) if now is None else now
    if kind not in TYPES:
        return {"ok": False, "fails": ["kind must be offer or receipt"], "notes": []}
    fmt = artifact.get("format")
    payload, signer, sig_ok, auth = None, None, False, {"status": "not_established", "how": None}
    if fmt == "eip712":
        payload = artifact.get("payload") if isinstance(artifact.get("payload"), dict) else None
        sig = str(artifact.get("signature") or "")
        if payload is None or not re.fullmatch(r"0x[0-9a-fA-F]{130}", sig):
            fails.append("eip712 needs a payload object and a 0x 65-byte signature")
        else:
            signer = recover_address(eip712_digest(kind, payload), bytes.fromhex(sig[2:]))
            sig_ok = signer is not None
            if not sig_ok:
                fails.append("signature does not recover to an address (malformed or high-s)")
            want = payload.get("payTo") if kind == "offer" else pay_to
            if sig_ok and want and _same_addr(signer, want):
                auth = {"status": "established", "how": "signer is the payTo address (the spec's simplest approach)"}
            elif sig_ok and want:
                notes.append(f"signer {signer} is not the payTo address; authorization needs another binding (did:web, DNS, registry)")
            elif sig_ok:
                notes.append("no payTo given for a receipt: authorization not checked")
    elif fmt == "jws":
        if "payload" in artifact:
            notes.append("jws artifacts must omit 'payload' (spec 3.1.1); it was ignored")
        tok = str(artifact.get("signature") or "")
        try:
            h, p, _ = tok.split(".")
            header, payload = json.loads(_b64u(h)), json.loads(_b64u(p))
        except Exception:
            header, payload = {}, None
            fails.append("signature is not a JWS compact string with JSON header and payload")
        if payload is not None:
            kid = str(header.get("kid") or "")
            if not header.get("alg") or not kid:
                fails.append("JWS header needs alg and kid (spec 3.3)")
            jwk, how = jwk_from_kid(kid, did_document) if kid else (None, "no kid")
            if jwk is None:
                fails.append(f"public key not resolved: {how}")
            else:
                sig_ok = verify_jws(tok, jwk)
                signer = kid
                if not sig_ok:
                    fails.append("JWS signature does not verify with the resolved key")
                elif kid.startswith("did:web:"):
                    host = kid.partition("#")[0][len("did:web:"):].split(":")[0].replace("%3A", ":")
                    if host.lower() == (urlparse(str(payload.get("resourceUrl") or "")).netloc or "").lower():
                        auth = {"status": "established", "how": "did:web on the resourceUrl domain lists this key (current state only)"}
                    else:
                        notes.append("did:web domain differs from the resourceUrl domain: authorization not established")
                else:
                    notes.append(f"key resolved via {how}; nothing ties it to the resourceUrl domain")
    else:
        fails.append("format must be eip712 or jws")
    if payload is not None:
        req = OFFER_REQ if kind == "offer" else RECEIPT_REQ
        missing = [f for f in req if payload.get(f) in (None, "")]
        if missing:
            fails.append("payload misses required fields: " + ", ".join(missing))
        if payload.get("version") not in (1, "1"):
            fails.append("payload version must be 1 (the only defined version)")
        if not re.fullmatch(r"[-a-z0-9]{3,8}:[-_a-zA-Z0-9]{1,64}", str(payload.get("network") or "")):
            fails.append("network must be CAIP-2 (e.g. eip155:8453)")
        if kind == "offer":
            vu = int(payload.get("validUntil") or 0)
            if vu and now > vu:
                notes.append(f"offer expired at {vu} (the server may refuse payment)")
            if isinstance(accepts, dict):
                for f, a in (("scheme", "scheme"), ("network", "network"), ("asset", "asset"), ("payTo", "payTo"),
                             ("amount", "amount")):
                    got, exp = payload.get(f), accepts.get(a) if a != "amount" else (accepts.get("amount") or accepts.get("maxAmountRequired"))
                    if exp is not None and str(got).lower() != str(exp).lower():
                        fails.append(f"signed {f} {got!r} differs from the accepts entry ({exp!r})")
        else:
            tx = str(payload.get("transaction") or "")
            if tx and not re.fullmatch(r"0x[0-9a-fA-F]{64}|[1-9A-HJ-NP-Za-km-z]{43,90}", tx):
                fails.append("transaction is not a transaction hash")
            if transaction and tx and tx.lower() != transaction.lower():
                fails.append("receipt names a different transaction than the settlement given")
            if not tx:
                notes.append("privacy-minimal receipt: no transaction, so the amount cannot be checked on-chain from it")
            ia = int(payload.get("issuedAt") or 0)
            if ia > now + 300:
                fails.append("issuedAt is in the future")
    return {"ok": not fails, "kind": kind, "format": fmt, "signature_valid": sig_ok, "signer": signer,
            "authorization": auth, "payload": payload, "fails": fails, "notes": notes,
            "rule": "signature validity, signer authorization and term matching are reported separately (spec 4.5.1)"}
