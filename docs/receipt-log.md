# neo's receipt log (transparency log)

Every signed `verify_quote` receipt neo issues (since v0.99.69) is also recorded in an
append-only public hash chain. The log holds **fingerprints only** (SHA-256 of the signed
receipt), never quotes or URLs.

- Live tail: `GET https://neo-collettive.onrender.com/receipts/log?after=<seq>`
- Full archive: [`docs/receipts-log/log.jsonl`](receipts-log/log.jsonl), updated every 2 hours,
  with the current head in [`docs/receipts-log/head.json`](receipts-log/head.json).

## Format

Each entry is `[seq, unix_ts, kind, item_sha256, extra]`, `kind` is `receipt`, `correction` or `note`.
The chain hash is `h_n = sha256(bytes.fromhex(h_{n-1}) + canonical_json(entry))`, `h_0` = 64 zeros,
canonical JSON = sorted keys, compact separators, UTF-8 (the same as the receipts).

Each signed receipt carries `receipt.log = {"seq": n, "prev": h_{n-1}}` inside the signed part,
so the receipt itself says where it must appear. To check one receipt:

```
python tools/receipt_log_verify.py docs/receipts-log/log.jsonl my_receipt.json
```

## Mistakes are corrected by appending, never by editing

A wrong verdict stays in the log. A `correction` entry is appended with
`extra = {"ref": <seq or item hash>, "reason": ..., "version": ...}`. Removing or changing any
past entry changes every later hash, so anyone holding an older head can see it.

## What it does not prove

The log proves which receipts neo issued and in what order, and that none was silently removed
afterwards. It does not prove a quoted claim is true, and a missing entry before v0.99.69 means
nothing: receipts issued earlier (v0.99.65–v0.99.68) were not logged.

## Anchors outside our control (since 22/10)

Once a day `receipt-log-anchor.yml` writes a small statement to
[`docs/receipts-log/anchors/`](receipts-log/anchors/): the date, the log count and head, and the
commit SHA of this repository's `main` (which fixes the whole public git history at that moment).

- The statement is timestamped with **OpenTimestamps**: the public calendars put its SHA-256
  into a Bitcoin block (free; a few hours later `ots upgrade` completes the proof in the `.ots`
  file next to it). Anyone can check it without trusting neo or any company.
- The workflow also asks **Software Heritage** to archive this repository, so a later rewrite
  of the history would differ from an independent copy (`anchors/software-heritage.jsonl`).

To check an anchor:

```
pip install opentimestamps-client
python tools/receipt_log_anchor.py verify docs/receipts-log/anchors/<date>.json docs/receipts-log/log.jsonl
```

It checks that the `.ots` proof commits to the statement, that its Bitcoin attestation matches
the block's Merkle root (read from a public block explorer), and that the anchored head is the
chain head after that many entries. An anchor proves the statement existed no later than that
block; it says nothing about entries added after it until the next anchor.
