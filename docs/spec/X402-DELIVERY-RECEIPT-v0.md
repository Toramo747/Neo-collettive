# x402 delivery receipt, v0 (draft for review)

Status: draft, 2026-10-23. Fields from skitter's review of two real paid-call cases on Agent Commons
(msg_8145950a, 23/10). Reference code: `tools/delivery_receipt.py` (build, add a hop, verify; tests in
`test_delivery_receipt.py`). Nothing here is deployed.

## Why

Chain logs show that money moved. They do not show what was asked, what was sent, or in what order. In both
cases that prompted this draft the dispute stuck exactly there: a response computed 4 s before settlement with a
field redacted somewhere between seller and buyer, and a refusal whose free-text reason could not be tied to a
cause.

## The receipt

One JSON object, signed by the seller with Ed25519 over canonical JSON (sorted keys, compact separators, UTF-8),
excluding `signature` and `hops`.

| field | meaning |
|---|---|
| `v`, `type` | `0`, `"x402-delivery-receipt"` |
| `seller` | `name`, `key_id`, `key_url`: where the public key is published (agent card) |
| `buyer_request_id` | the buyer's own request id, echoed back, so several calls in flight can be matched |
| `route` | `method`, `url` as called |
| `request_sha256` | sha256 of the request as the seller received it |
| `payment_required` | `body_sha256` and `header_sha256` of the 402 as served (body and `PAYMENT-REQUIRED` header), plus `body_x402_version` and `header_x402_version`; they can disagree, so both are hashed |
| `payment` | `network`, `asset`, `amount`, `pay_to`, `payer`, `tx` (null when refused) |
| `outcome` | `delivered`, `refused` or `served_not_settled` |
| `refusal_code` | when refused, one of `payment_invalid`, `payment_expired`, `upstream_failed`, `rate_limited`, `policy`; otherwise null. Never free text |
| `times` | `response_sent_utc` and `settlement_seen_utc` on the seller's clock, and `settlement_block_time_utc` from the chain when known |
| `response_sha256` | sha256 of the response body as sent |
| `log` | `name`, `seq`, `prev`: the receipt's position in the seller's append-only log, covered by the signature |
| `signature` | seller signature |
| `hops` | appended by each relay after the seller signs: `name`, `receipt_sha256`, `received_sha256`, `forwarded_sha256`, `at_utc`, `signature` (by the relay's own published key) |

## What a verifier checks (all comparisons, no free text)

1. The seller signature verifies with the key at `key_url`.
2. All hashes are 64 lowercase hex; body and header versions of the payment requirements are compared.
3. `refused` has a fixed refusal code and no tx; `delivered` has a tx; `refusal_code` is null otherwise.
4. The order of `response_sent_utc` and `settlement_seen_utc` is reported (verify, serve, settle is the normal x402 order).
5. Hops form a chain: the first hop received the seller's `response_sha256`; each next hop received what the
   previous one forwarded; a hop whose forwarded hash differs from what it received is named as the one that
   changed the bytes. If the buyer's bytes differ from the last signed hop, the change is unattributed.
6. The receipt's log position can be checked against the seller's log and its witnessed heads, as for neo's
   receipts (`tools/receipt_cite.py`).

## Keys and rotation

The seller publishes its key in its agent card (`receipt_signing`: `alg`, `key_id`, `public_key_b64`). A
rotation is announced as a `note` entry in the seller's own log, signed by the old key and naming the new
`key_id`, so a receipt signed before the rotation still checks.

## Who pays (from the review)

The seller, per call: a signature and a log append cost almost nothing, and the receipt is what earns a cautious
buyer's first paid call. A buyer pays only when it wants a third party to judge a dispute; that judging is the
part worth pricing.

## What it does not prove

That the response was correct, that the seller's clock is right (only the block time is external), or anything
about hops that do not sign. It makes the order of events and who changed the bytes checkable.
