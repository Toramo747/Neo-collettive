#!/usr/bin/env python3
"""Cite a neo receipt on Agent Commons (23/10, Andrea's OK): the citation and its proof in one public post.

Whoever asked neo for a receipt can publish it whole, as one line:

  RECEIPT {...the signed receipt exactly as neo returned it, signature included...}

Anyone can then check it, with no trust in neo beyond its published key:
  1. the Ed25519 signature verifies with neo's public key (agent card, field receipt_signing);
  2. the receipt names its place in the log (receipt.log.seq and .prev), and the log entry at that seq holds
     sha256(canonical JSON of the receipt): the receipt existed when that entry was written;
  3. prev is our chain head just before that entry;
  4. a witness has attested a log size >= seq with a head matching our chain, so the position is not only our word.

  python tools/receipt_cite.py check <text-or-file> [public_key_b64]   strict check, exit 1 on any failure
  python tools/receipt_cite.py collect <board.json> <out.jsonl> [public_key_b64]

What it proves: neo signed this result, and it sits at that position of a log others have seen. It does not
prove the verdict is right, nor who asked (a receipt names no caller yet), nor that the page still says it.
"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from receipt_log import item_hash, verify_chain  # noqa: E402
from receipt_signing import verify_receipt  # noqa: E402

LOG = ROOT / "docs" / "receipts-log" / "log.jsonl"
WITNESSES = ROOT / "docs" / "receipts-log" / "witnesses.jsonl"
CARD = "https://neo-collettive.onrender.com/.well-known/agent-card.json"
MARK = re.compile(r"RECEIPT\s+(?=\{)")


def parse(text: str) -> dict | None:
    m = MARK.search(text or "")
    if not m:
        return None
    try:
        obj, _ = json.JSONDecoder().raw_decode(text[m.end():])
        return obj if isinstance(obj, dict) else None
    except Exception:
        return None


def _jsonl(p: Path) -> list:
    return [json.loads(l) for l in p.read_text().splitlines() if l.strip()] if p.exists() else []


def public_key() -> str:
    import urllib.request
    with urllib.request.urlopen(urllib.request.Request(CARD, headers={"User-Agent": "neo-receipt-cite"}), timeout=20) as r:
        return str((json.loads(r.read().decode()).get("receipt_signing") or {}).get("public_key_b64") or "")


def check(rec: dict | None, key_b64: str, log_path: Path = LOG, witnesses_path: Path = WITNESSES) -> list[str]:
    if not isinstance(rec, dict):
        return ["no RECEIPT line with valid JSON"]
    fails = []
    meta = rec.get("receipt") or {}
    if not verify_receipt(rec, key_b64):
        fails.append("signature does not verify with neo's public key")
    if meta.get("issuer") != "neo (OSIXBAY)" or meta.get("v") != 1:
        fails.append("not a neo receipt (issuer / v)")
    pos = meta.get("log") or {}
    seq, prev = pos.get("seq"), pos.get("prev")
    es = _jsonl(log_path)
    if not isinstance(seq, int) or seq < 1:
        fails.append("the receipt names no log position (older receipts were issued before the log)")
        return fails
    if seq > len(es):
        fails.append(f"our copy has only {len(es)} entries: update docs/receipts-log/log.jsonl and check again (not a rejection)")
        return fails
    entry = es[seq - 1]
    if entry[0] != seq or entry[2] != "receipt":
        fails.append(f"log entry {seq} is not a receipt entry")
    if entry[3] != item_hash(rec):  # production logs sha256 of the signed receipt, signature included
        fails.append(f"log entry {seq} holds a different receipt hash")
    before = verify_chain(es[:seq - 1])
    if before["head"] != prev:
        fails.append(f"receipt.log.prev is not our head after {seq - 1} entries")
    wit = [w for w in _jsonl(witnesses_path) if int(w["attestation"]["log_size"]) >= seq
           and verify_chain(es[:int(w["attestation"]["log_size"])])["head"] == w["attestation"]["log_head"]]
    if not wit:
        fails.append(f"no witness has attested a log size >= {seq} yet (position rests on our word)")
    return fails


def collect(board_json: str, out_jsonl: str, key_b64: str) -> int:
    board = json.loads(Path(board_json).read_text())
    out = Path(out_jsonl)
    seen = {json.loads(l)["post_id"] for l in out.read_text().splitlines() if l.strip()} if out.exists() else set()
    rows = {e["id"]: e for v in board.values() if isinstance(v, list) for e in v if isinstance(e, dict) and e.get("id")}
    new = 0
    for e in rows.values():
        rec = parse(str(e.get("body") or ""))
        if rec is None or e["id"] in seen:
            continue
        fails = check(rec, key_b64)
        print(f"::notice title=receipt cite::{e.get('agent')} {e['id']}: {'OK' if not fails else '; '.join(fails)[:300]}")
        if not fails:
            meta = rec["receipt"]
            with out.open("a") as fh:  # public fingerprints only: no URL, no quote
                fh.write(json.dumps({"post_id": e["id"], "agent": e.get("agent"), "seq": meta["log"]["seq"],
                                     "item_sha256": item_hash(rec), "outcome": rec.get("outcome"),
                                     "accepted_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")},
                                    sort_keys=True) + "\n")
            new += 1
    print(f"::notice title=receipt cite::accepted={new}")
    return 0


if __name__ == "__main__":
    a = sys.argv
    if len(a) >= 3 and a[1] == "check":
        src = Path(a[2]).read_text() if Path(a[2]).exists() else a[2]
        fails = check(parse(src), a[3] if len(a) > 3 else public_key())
        print("ACCEPTED" if not fails else "REJECTED: " + "; ".join(fails))
        sys.exit(1 if fails else 0)
    if len(a) >= 4 and a[1] == "collect":
        sys.exit(collect(a[2], a[3], a[4] if len(a) > 4 else public_key()))
    print(__doc__)
    sys.exit(2)
