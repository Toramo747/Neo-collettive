#!/usr/bin/env python3
"""Anchors for neo's receipt log outside our own control (22/10, Andrea's OK).

An anchor is a small JSON statement, docs/receipts-log/anchors/<date>.json:

  {"v": 1, "date_utc": ..., "log_count": n, "log_head": "<chain head>",
   "repo": "<public repo URL>", "repo_commit": "<main commit SHA>"}

Its SHA-256 is timestamped with OpenTimestamps (anchored in a Bitcoin block by the
public calendars, free). The commit SHA covers the whole public git history at that
moment, so the anchor fixes both the receipt log and the repository.

  make   <out_dir>                 write today's statement (reads head.json and git)
  verify <anchor.json> [log.jsonl] check: the .ots file commits to the statement, its
                                   Bitcoin attestation matches the block's Merkle root
                                   (read from a public block explorer), and log_head is
                                   the chain head after log_count entries of log.jsonl.

What it proves: the statement existed no later than that Bitcoin block. It does not
prove a receipt's verdict is right, and it cannot show anything about entries added
after the anchor until the next one.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REPO_URL = "https://github.com/Toramo747/Neo-collettive"
EXPLORER = "https://blockstream.info/api"


def canonical(obj) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def make(out_dir: str) -> int:
    head = json.loads((ROOT / "docs" / "receipts-log" / "head.json").read_text())
    commit = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"], capture_output=True,
                            text=True, check=True).stdout.strip()
    now = datetime.now(timezone.utc)
    stmt = {"v": 1, "date_utc": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "log_count": int(head["count"]),
            "log_head": head["head"], "repo": REPO_URL, "repo_commit": commit}
    # 29/10 (mcp-ledger): the day's Merkle root of MCP contract digests, when today's read exists, so the root is
    # named in the timestamped statement itself and not only reachable through the commit.
    ledger = ROOT / "data" / "mcp-ledger" / "days" / f"{now.strftime('%Y-%m-%d')}.root.json"
    if ledger.exists():
        try:
            lj = json.loads(ledger.read_text())
            stmt["mcp_ledger"] = {"date": lj["date"], "root": lj["root"], "rows": int(lj["rows"])}
        except Exception:  # noqa: BLE001
            pass
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"{now.strftime('%Y-%m-%d')}.json"
    path.write_bytes(canonical(stmt) + b"\n")
    print(f"::notice title=receipt log anchor::statement {path.name} log_count={stmt['log_count']} "
          f"sha256={hashlib.sha256(path.read_bytes()).hexdigest()[:16]}")
    print(path)
    return 0


def _get(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "neo-anchor-verify/1"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode()


def verify(anchor: str, log_path: str = "") -> int:
    from opentimestamps.core.notary import BitcoinBlockHeaderAttestation, PendingAttestation
    from opentimestamps.core.serialize import StreamDeserializationContext
    from opentimestamps.core.timestamp import DetachedTimestampFile

    a = Path(anchor)
    data = a.read_bytes()
    with open(str(a) + ".ots", "rb") as fd:
        dts = DetachedTimestampFile.deserialize(StreamDeserializationContext(fd))
    ok = True
    if dts.file_digest != hashlib.sha256(data).digest():
        print("FAIL: the .ots file does not commit to this statement")
        return 1
    btc = [(msg, att) for msg, att in dts.timestamp.all_attestations() if isinstance(att, BitcoinBlockHeaderAttestation)]
    pending = [att for _, att in dts.timestamp.all_attestations() if isinstance(att, PendingAttestation)]
    if not btc:
        print(f"PENDING: no Bitcoin attestation yet ({len(pending)} calendar(s) waiting); run `ots upgrade` later")
        ok = False
    for msg, att in btc:
        block_hash = _get(f"{EXPLORER}/block-height/{att.height}").strip()
        merkle = json.loads(_get(f"{EXPLORER}/block/{block_hash}"))["merkle_root"]
        if msg[::-1].hex() == merkle:
            t = json.loads(_get(f"{EXPLORER}/block/{block_hash}"))["timestamp"]
            print(f"OK: Bitcoin block {att.height} ({datetime.fromtimestamp(t, timezone.utc):%Y-%m-%d %H:%M} UTC) "
                  f"commits to this statement")
        else:
            print(f"FAIL: block {att.height} Merkle root does not match")
            ok = False
    stmt = json.loads(data)
    if log_path:
        sys.path.insert(0, str(ROOT))
        import receipt_log as rl
        entries = [json.loads(l) for l in Path(log_path).read_text().splitlines() if l.strip()]
        chk = rl.verify_chain(entries[: stmt["log_count"]])
        same = chk["ok"] and chk["head"] == stmt["log_head"]
        print(("OK" if same else "FAIL") + f": chain head after {stmt['log_count']} entries "
              + ("matches" if same else "does not match") + " the anchored head")
        ok = ok and same
    return 0 if ok else 1


def main(argv: list[str]) -> int:
    if len(argv) >= 3 and argv[1] == "make":
        return make(argv[2])
    if len(argv) >= 3 and argv[1] == "verify":
        return verify(argv[2], argv[3] if len(argv) > 3 else "")
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
