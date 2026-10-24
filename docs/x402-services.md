# Paid microservices over x402 (draft, not enabled)

Routes: `GET /x402` lists them; each service is `POST /x402/<name>` with a JSON body. Price: 0.01 USDC on Base per
call (citation-check 0.05, proof-of-publication 0.50, mcp-audit 2.00), paid to OSIXBAY's address through Coinbase's CDP facilitator. Every result is signed with neo's receipt key,
covers the settlement (tx), and is logged in the public receipt log like the free verify_quote.

| service | what it does |
|---|---|
| mcp-audit (2.00) | security audit of an MCP server: tool poisoning, shadowing, risky capabilities, fingerprint |
| proof-of-publication (0.50) | signed, anchored evidence that a page said this at this time |
| injection-scan | prompt-injection evidence in text or a public page, before an agent reads it |
| citation-check (0.05) | every quote+link citation in an answer, checked on its page, one report |
| verify-quote | is this exact sentence on this public page |
| mcp-check | read-only check of a public MCP endpoint |
| x402-lint | lint a seller's unpaid 402 (never pays) |
| timestamp | prove you had this sha256 at this time (daily anchoring) |
| log-witness | recompute a hash-chained log, signed size and head |
| delivery-receipt-verify | verify an x402 delivery receipt v0.1 |

Rules: bad input is refused (400) before any payment is looked at; a payment for other terms is refused without
calling the facilitator; the result is released only after settlement succeeds; our own failures (deadline, rate
limit) are not settled. The free tools on the MCP server stay free and unchanged.

Off until three Render variables are set by Andrea: `X402_PAY_TO`, `CDP_API_KEY_ID`, `CDP_API_KEY_SECRET`.
Until then every paid route answers 503 `x402_not_enabled`.

## Also as MCP tools (24/10)

On neo's MCP server (`/mcp`): `paid_mcp_audit`, `paid_injection_scan`, `paid_citation_check`,
`paid_proof_of_publication`, `paid_timestamp`. x402 MCP binding: call without payment and the result is
`isError` with the 402 object in `structuredContent`; retry with the signed payment in `_meta["x402/payment"]`;
the settlement comes back in `_meta["x402/payment-response"]`. Same prices, same rules, same signed and logged
results. The free tools (verify_quote, verify_mcp_endpoint, ...) are unchanged.
