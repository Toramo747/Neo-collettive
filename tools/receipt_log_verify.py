"""Check neo's public receipt log, and optionally that one signed receipt is in it.

usage: receipt_log_verify.py <log.jsonl> [<signed_receipt.json>]
Needs only the standard library: each line of the log is one entry
[seq, unix_ts, kind, item_sha256, extra]; h_n = sha256(bytes.fromhex(h_{n-1}) +
canonical_json(entry)), h_0 = 64 zeros.
"""
from __future__ import annotations

import hashlib
import json
import sys


def canonical(v) -> bytes:
    return json.dumps(v, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def main(argv: list[str]) -> int:
    entries = [json.loads(l) for l in open(argv[0], encoding="utf-8") if l.strip()]
    head, heads = "0" * 64, {0: "0" * 64}
    for i, e in enumerate(entries, 1):
        if e[0] != i:
            print(f"BROKEN: expected seq {i}, found {e[0]}")
            return 1
        head = hashlib.sha256(bytes.fromhex(head) + canonical(e)).hexdigest()
        heads[i] = head
    print(f"chain ok: {len(entries)} entries, head {head}")
    if len(argv) > 1:
        rec = json.load(open(argv[1], encoding="utf-8"))
        pos = (rec.get("receipt") or {}).get("log") or {}
        seq = int(pos.get("seq") or 0)
        item = hashlib.sha256(canonical(rec)).hexdigest()
        if not seq or seq > len(entries):
            print("receipt not (yet) in this log")
            return 2
        e = entries[seq - 1]
        if e[3] != item or heads[seq - 1] != pos.get("prev"):
            print(f"MISMATCH at seq {seq}")
            return 3
        later = [x for x in entries[seq:] if x[2] == "correction" and x[4].get("ref") in (str(seq), item)]
        print(f"receipt found at seq {seq}" + (f"; corrected later by seq {later[0][0]}: {later[0][4].get('reason')}" if later else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
