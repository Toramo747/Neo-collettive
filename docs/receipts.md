# Signed verify_quote receipts

With a valid signing key configured, every result returned by the public MCP
`verify_quote` tool carries an Ed25519 signature, including `unreachable`,
validation errors such as `quote_too_short`, and verification timeouts.
The quote-checking rules are unchanged. Without a valid key the tool still works,
returning `signed: false` without `receipt` or `signature`; discovery reports
`receipt_signing: null`.

## Format

All original result fields are retained. Two fields are added:

```json
{
  "receipt": {
    "v": 1,
    "tool": "verify_quote",
    "issuer": "neo (OSIXBAY)",
    "key_id": "neo-receipt-<first 16 hex characters of SHA-256(raw public key)>",
    "issued_at_utc": "2026-10-18T05:00:00+00:00",
    "alg": "Ed25519",
    "canonical": "json-sorted-compact-utf8"
  },
  "signature": "<Base64url Ed25519 signature without padding>"
}
```

The example above shows only the additional fields, not a complete signed result.
The signature covers the **entire result with receipt included**, excluding only
the top-level `signature` field. Canonical bytes are exactly:

```python
json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
```

Read the public key from neo's HTTPS discovery document at
<https://neo-collettive.onrender.com/.well-known/agent-card.json>:
`receipt_signing.public_key_b64` is standard Base64 of the raw 32-byte public key.
`receipt_signing.key_id` identifies the signing key. Signature encoding is
Base64url, unlike the public key encoding.

## Verify in ten lines of Python

Install `cryptography`. Put the complete tool result in `receipt.json` and the
HTTPS discovery document in `agent-card.json`, obtained directly from neo.
A failure raises an exception; success prints `verified`.

```python
import base64, json
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
obj = json.load(open("receipt.json", encoding="utf-8"))
card = json.load(open("agent-card.json", encoding="utf-8"))["receipt_signing"]
sig = obj.pop("signature")
assert obj["receipt"]["key_id"] == card["key_id"]
raw = json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
pub = Ed25519PublicKey.from_public_bytes(base64.b64decode(card["public_key_b64"], validate=True))
pub.verify(base64.urlsafe_b64decode(sig + "=" * (-len(sig) % 4)), raw)
print("verified")
```

For a reusable boolean verifier, copy `verify_receipt` and `canonical_json` with
their imports from `receipt_signing.py`. They do not need the private key or neo's
server code. Verify the original result before transforming any fields.

## What the signature does and does not guarantee

A valid signature proves that the holder of neo's signing key issued these exact
result fields and that they have not been modified. Attribution depends on getting
the public key directly from neo over authenticated HTTPS, or trusting a previously
pinned public key, rather than trusting a key supplied by whoever relays a receipt.

It does **not** prove the quoted statement is true, establish who authored the
source page, or guarantee the page has not changed since the check. `not_found`
does **not** mean false. The timestamp is an issuer assertion, not an independent
time authority; a signed receipt can be replayed. Check its age for your use case.
If keys rotate, retain trusted historical public keys to verify old receipts;
the discovery document exposes only the currently configured key.

## Operator setup

Only Andrea generates the production seed locally and configures
`NEO_RECEIPT_SIGNING_KEY` in Render: exactly 64 hexadecimal characters representing
32 random bytes. Never put the seed in chat, GitHub, repository files or logs.
The service loads the key once at startup. Missing or malformed configuration
silently disables signing; it never logs the seed. Merge and deploy require
Andrea's explicit approval. No new runtime dependency is needed: `cryptography`
is already in `requirements.lock`.

## Reproducible quote-checking behavior

The [verify_quote v1 conformance vector](conformance/VERIFY_QUOTE_V1.json) pins a
synthetic test page to an exact public Git commit and records its SHA-256 and
computed expectations. The [specification](verify-quote-spec.md) explains the
current rules and their limits. Run `verify-quote-conformance.yml` to compare
eleven offline cases and at most six live results, including receipt signature
verification. A valid signature and a matching conformance result are separate
checks; neither establishes that the quoted statement is true.
