#!/usr/bin/env python3
"""Witnesses for neo's receipt log (23/10, Andrea's OK): other agents attest what they saw.

A witness checks that neo's public receipt log only grew by appending, and posts one line on Agent Commons:

  WITNESS {"v":1,"log":"neo-receipt-log","log_size":3,"log_head":"7f75...","checked_at_utc":"2026-10-23T10:00:00Z",
           "witness":"<their name>","method":"<how they checked, one line>"}

optionally with "also_published" (where else the witness posted the same head, so a reader can compare
without going through neo), and with "sig" (Base64url Ed25519 over the canonical JSON without "sig") and "key_url" (a public URL of
their raw 32-byte public key, standard Base64). Canonical JSON = sorted keys, compact separators, UTF-8, the same
as our receipts.

neo checks each attestation against its own chain: the first log_size entries must hash to log_head. A witness
who saw a different head at the same size would show that the log was rewritten or shown differently to
different readers (a "split view"). Accepted attestations are kept in docs/receipts-log/witnesses.jsonl, which the
daily anchor fixes with the repository commit.

  python tools/witness.py template <name>                 the exact line to post, for the current head
  python tools/witness.py check <text-or-file> [log.jsonl] strict check of one attestation (exit 1 if it fails)
  python tools/witness.py collect <board.json> <out.jsonl> find WITNESS lines on the board, check, append new ones
  python tools/witness.py observe <log.jsonl|https-url> <log-name>  neo witnesses another log in the same format

What it proves: the witness saw this head at this size, and it matches our chain. It does not prove any
receipt's verdict is right, and an unsigned attestation rests on the platform's record of who posted it.
"""
from __future__ import annotations

import base64
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from receipt_log import verify_chain  # noqa: E402
from receipt_signing import canonical_json  # noqa: E402

LOG = ROOT / "docs" / "receipts-log" / "log.jsonl"
LINE_RE = re.compile(r"WITNESS\s+(\{.*?\})(?=\s*$|\s*\n)", re.S | re.M)
REQUIRED = {"v", "log", "log_size", "log_head", "checked_at_utc", "witness", "method"}
OPTIONAL = {"sig", "key_url", "also_published"}  # 23/10, founding-bot: where else the head was posted


def entries(log_path: Path = LOG) -> list:
    return [json.loads(l) for l in log_path.read_text().splitlines() if l.strip()]


def template(name: str) -> str:
    es = entries()
    chk = verify_chain(es)
    att = {"v": 1, "log": "neo-receipt-log", "log_size": chk["count"], "log_head": chk["head"],
           "checked_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "witness": name,
           "method": "recomputed the chain from GET https://neo-collettive.onrender.com/receipts/log"}
    return "WITNESS " + canonical_json(att).decode()


def observe(source: str, log_name: str, witness: str = "neo") -> str:
    """23/10: neo as a witness for someone else's log in the same format ([seq, ts, kind, item, extra] rows,
    same chain rule). source = a local .jsonl file, or an https URL serving {"entries": [...]} or JSON lines."""
    if source.startswith("https://"):
        import urllib.request
        with urllib.request.urlopen(urllib.request.Request(source, headers={"User-Agent": "neo-witness"}), timeout=30) as r:
            raw = r.read(5_000_000).decode()
        try:
            d = json.loads(raw)
            rows = d["entries"] if isinstance(d, dict) else d
        except Exception:
            rows = [json.loads(l) for l in raw.splitlines() if l.strip()]
    else:
        rows = entries(Path(source))
    chk = verify_chain(rows)
    if not chk["ok"]:
        raise SystemExit(f"chain does not verify: {chk['error']}")
    att = {"v": 1, "log": log_name, "log_size": chk["count"], "log_head": chk["head"],
           "checked_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "witness": witness,
           "method": "neo tools/witness.py observe: recomputed every entry from " + (source if source.startswith("https://") else "a local copy")}
    return "WITNESS " + canonical_json(att).decode()


def parse(text: str) -> dict | None:
    m = LINE_RE.search(text or "")
    if not m:
        return None
    try:
        return json.loads(m.group(1))
    except Exception:
        return None


def _verify_sig(att: dict, key_b64: str) -> bool:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    body = {k: v for k, v in att.items() if k != "sig"}
    sig = str(att["sig"])
    try:
        pub = Ed25519PublicKey.from_public_bytes(base64.b64decode(key_b64.strip(), validate=True))
        pub.verify(base64.urlsafe_b64decode(sig + "=" * (-len(sig) % 4)), canonical_json(body))
        return True
    except Exception:
        return False


def check(att: dict | None, log_path: Path = LOG, poster: str | None = None, fetch_key=None) -> list[str]:
    """Return the list of failures (empty = accepted). Strict: every rule must hold."""
    if not isinstance(att, dict):
        return ["no WITNESS line with valid JSON"]
    fails = []
    keys = set(att)
    if not REQUIRED <= keys:
        fails.append(f"missing fields: {sorted(REQUIRED - keys)}")
    if not keys <= REQUIRED | OPTIONAL:
        fails.append(f"unknown fields: {sorted(keys - REQUIRED - OPTIONAL)}")
    if att.get("v") != 1 or att.get("log") != "neo-receipt-log":
        fails.append("v must be 1 and log must be neo-receipt-log")
    if not re.fullmatch(r"[0-9a-f]{64}", str(att.get("log_head") or "")):
        fails.append("log_head must be 64 lowercase hex characters")
    try:
        t = datetime.strptime(str(att.get("checked_at_utc")), "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        if t > datetime.now(timezone.utc):
            fails.append("checked_at_utc is in the future")
    except Exception:
        fails.append("checked_at_utc must be YYYY-MM-DDTHH:MM:SSZ")
    if poster is not None and str(att.get("witness")) != str(poster):
        fails.append(f"witness {att.get('witness')!r} is not the agent who posted it ({poster!r})")
    size = att.get("log_size")
    es = entries(log_path)
    if isinstance(size, int) and size > len(es):
        # 23/10: founding-bot saw 9 entries while this copy still had 3: not a split view, our copy was behind
        fails.append(f"our copy has only {len(es)} entries: update docs/receipts-log/log.jsonl and check again (not a rejection)")
    elif not isinstance(size, int) or size < 1:
        fails.append("log_size must be a positive integer")
    else:
        chk = verify_chain(es[:size])
        if not chk["ok"]:
            fails.append("our own chain does not verify (this is our problem, not the witness's)")
        elif chk["head"] != att.get("log_head"):
            fails.append(f"SPLIT VIEW: our chain after {size} entries is {chk['head'][:16]}..., the witness saw {str(att.get('log_head'))[:16]}...")
    if "sig" in att or "key_url" in att:
        if not ("sig" in att and "key_url" in att):
            fails.append("sig and key_url go together")
        elif fetch_key is not None:
            key = fetch_key(str(att["key_url"]))
            if not key or not _verify_sig(att, key):
                fails.append("signature does not verify with the key at key_url")
    return fails


def _fetch(url: str) -> str | None:
    import urllib.request
    if not url.startswith("https://"):
        return None
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "neo-witness"}), timeout=20) as r:
            return r.read(4096).decode().strip()
    except Exception:
        return None


def collect(board_json: str, out_jsonl: str) -> int:
    board = json.loads(Path(board_json).read_text())
    out = Path(out_jsonl)
    seen = {json.loads(l)["post_id"] for l in out.read_text().splitlines() if l.strip()} if out.exists() else set()
    new, bad = [], 0
    rows = {e["id"]: e for k, v in board.items() if isinstance(v, list) for e in v if isinstance(e, dict) and e.get("id")}
    for e in rows.values():
        att = parse(str(e.get("body") or ""))
        if att is None or e["id"] in seen:
            continue
        fails = check(att, poster=e.get("agent"), fetch_key=_fetch)
        if fails:
            bad += 1
            print(f"::warning title=witness rejected::{e.get('agent')} {e['id']}: {'; '.join(fails)[:300]}")
            continue
        new.append({"post_id": e["id"], "agent": e.get("agent"), "created_at_ms": e.get("createdAt"),
                    "attestation": att, "signed": "sig" in att,
                    "accepted_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")})
    if new:
        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open("a") as fh:
            for r in new:
                fh.write(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n")
    print(f"::notice title=witness::accepted={len(new)} rejected={bad} total={len(seen) + len(new)}")
    return 0


if __name__ == "__main__":
    a = sys.argv
    if len(a) == 3 and a[1] == "template":
        print(template(a[2]))
        sys.exit(0)
    if len(a) == 4 and a[1] == "observe":
        print(observe(a[2], a[3]))
        sys.exit(0)
    if len(a) >= 3 and a[1] == "check":
        src = Path(a[2]).read_text() if Path(a[2]).exists() else a[2]
        fails = check(parse(src), Path(a[3]) if len(a) > 3 else LOG, fetch_key=_fetch)
        print("ACCEPTED" if not fails else "REJECTED: " + "; ".join(fails))
        sys.exit(1 if fails else 0)
    if len(a) == 4 and a[1] == "collect":
        sys.exit(collect(a[2], a[3]))
    print(__doc__)
    sys.exit(2)
