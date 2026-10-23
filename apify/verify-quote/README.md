# Verify Quote: is this exact sentence on this page?

Give it a public link and an exact sentence. It tells you whether the sentence is really on that page, and
hands you a receipt signed by neo that anyone can check later.

**Outcomes**
- `verbatim`: the sentence is on the page, word for word
- `paraphrase`: most of the words are there, but not as one sentence
- `stitched`: the "quote" glues together pieces from different parts of the page
- `not_found`: these words are not on the page. That is **not** a verdict on whether the claim is false; a faithful rewording also reads `not_found`
- `unreachable`: the page could not be fetched (no login, no JavaScript rendering)

**What you get for each item**
- the outcome, the matched segments and context, the page's final URL, HTTP status and size;
- `receipt`: the full result signed with Ed25519 over canonical JSON (sorted keys, compact, UTF-8). The public
  key is in neo's agent card: https://neo-collettive.onrender.com/.well-known/agent-card.json;
- `signature_verified`: this Actor already checked the signature for you;
- `log_seq`: the receipt's position in neo's public, append-only receipt log
  (https://neo-collettive.onrender.com/receipts/log). The log is hash-chained, anchored daily on Bitcoin
  (OpenTimestamps) and Software Heritage, and checked by independent witnesses, so a receipt cannot be quietly
  backdated or replaced.

**Pricing:** one event per item that returns a signed outcome. Bad input, rate limits and server errors are not
charged.

**What it does not prove:** that the sentence is true, who wrote it, or that the page will still say it
tomorrow. It checks the words on the page at the moment of the check.

**Free alternative, stated plainly:** the same check is free on neo's MCP server
(https://neo-collettive.onrender.com/mcp, tool `verify_quote`, no key). This Actor is for people who want it
inside Apify: batch input, datasets, scheduling, integrations and billing in one place.

**Input**
```json
{"items": [{"url": "https://example.org/post", "quote": "the exact sentence you want to check"}]}
```
Up to 50 items per run, about 7 seconds each (neo allows 10 checks a minute per caller; the Actor stays under it).
