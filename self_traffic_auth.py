from __future__ import annotations

import argparse
import hashlib
import hmac
import os
import time
from urllib.parse import urlparse

MAX_SKEW_SECONDS = 300

def make_self_traffic_proof(secret: str, path: str, *, timestamp: int | None = None) -> str:
    secret=str(secret or "")
    path=str(path or "/")
    ts=int(time.time() if timestamp is None else timestamp)
    if not secret:
        raise ValueError("self-traffic secret is not configured")
    message=f"{ts}\n{path}".encode("utf-8")
    signature=hmac.new(secret.encode("utf-8"),message,hashlib.sha256).hexdigest()
    return f"{ts}:{signature}"

def verify_self_traffic_proof(secret: str, path: str, proof: str, *, now: int | None = None, max_skew_seconds: int = MAX_SKEW_SECONDS) -> dict:
    secret=str(secret or "")
    proof=str(proof or "").strip()
    path=str(path or "/")
    if not secret:
        return {"valid":False,"reason":"secret_unconfigured"}
    if ":" not in proof:
        return {"valid":False,"reason":"proof_missing_or_malformed"}
    ts_text,signature=proof.split(":",1)
    try:
        ts=int(ts_text)
    except Exception:
        return {"valid":False,"reason":"timestamp_invalid"}
    current=int(time.time() if now is None else now)
    if abs(current-ts)>int(max_skew_seconds):
        return {"valid":False,"reason":"proof_expired"}
    message=f"{ts}\n{path}".encode("utf-8")
    expected=hmac.new(secret.encode("utf-8"),message,hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature,expected):
        return {"valid":False,"reason":"signature_invalid"}
    return {"valid":True,"reason":"hmac_sha256_verified","timestamp":ts}

def _cli() -> int:
    parser=argparse.ArgumentParser()
    sub=parser.add_subparsers(dest="command",required=True)
    sign=sub.add_parser("sign-url")
    sign.add_argument("url")
    sign.add_argument("--marker",default="")
    args=parser.parse_args()
    if args.command=="sign-url":
        parsed=urlparse(args.url)
        path=parsed.path or "/"
        secret=os.getenv("NEO_HEARTBEAT_TOKEN") or os.getenv("HEARTBEAT_TOKEN") or ""
        print(make_self_traffic_proof(secret,path))
        return 0
    return 2

if __name__=="__main__":
    raise SystemExit(_cli())
