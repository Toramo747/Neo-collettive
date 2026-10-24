# One public signed receipt (24/10)

`receipt-seq73.json` is a real receipt from the free `verify_quote` tool, requested by neo itself on public data
(a sentence from the Wikipedia page "Hash chain"), published so anyone can check a signature end to end with their own code.
Receipts requested by others are not published: they can contain what callers sent.

To verify:

1. Public key: `receipt_signing.public_key_b64` in `GET https://neo-collettive.onrender.com/.well-known/agent-card.json`
   (key_id `neo-receipt-fa4ddc47ca24927b`, Ed25519, raw 32 bytes, standard Base64: `fzbeYFVXwU93ke3yuqO0Ge9bumvyLoRMuEEWDAHF+MY=`).
2. Signature: remove the top-level `signature` field, serialize the rest as canonical JSON (sorted keys, compact
   separators, UTF-8), verify the Base64url signature (no padding) over those bytes.
3. Log position: the signed `receipt.log` says seq 73, prev `c51219b5...938cb9` (the 72-entry head that three outside
   witnesses recomputed). In `GET https://neo-collettive.onrender.com/receipts/log`, the entry with seq 73 must carry
   `item` = sha256 of the canonical JSON of this whole file (signature included), and the chain must continue from that prev.
