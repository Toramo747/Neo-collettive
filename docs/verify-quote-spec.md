# verify_quote: executable conformance specification, v1

This describes the current `quote_verifier.py`, not an idealized quotation
checker. The pinned [vector](conformance/VERIFY_QUOTE_V1.json) contains eleven
cases with computed results; its public page URL identifies an exact Git commit.
The page has 22 lines and contains only synthetic public examples.

## Text normalization: `norm`

Order matters:

1. Remove complete `script`, `style`, `noscript`, and `template` elements,
   including their contents, case-insensitively and across line breaks.
2. Replace remaining strings matching `<[^>]+>` with spaces, then run
   `html.unescape`. This is regular-expression cleanup, not an HTML parser.
   Entity decoding happens after tag removal; decoded tags are not removed again.
3. Remove backticks. Map `’` and `‘` to ASCII apostrophe, and `“` and `”` to
   ASCII double quote. Replace literal backslash-n with a space and
   backslash-double-quote with a double quote.
4. Lowercase and join whitespace-separated tokens with one ASCII space.
   Real line breaks and repeated spaces therefore collapse too.

Other punctuation is retained. Matching is a substring search on normalized
text; there is no semantic truth check, stemming or word-boundary requirement.

## Cuts: `quote_segments`

Strip surrounding whitespace and double-quote characters (`"`, `“`, `”`).
Split using `\s*(?:\.\.\.+|…)\s*`: a Unicode ellipsis or at least three ASCII
periods, with optional surrounding whitespace. Normalize each part. Discard the
first token of every part after the first and the last token of every part
before the last. This discards boundary tokens **unconditionally**, even when
they are complete words. Keep resulting parts with at least three tokens.
If none survives, fall back to the normalized whole stripped quote if nonempty.
That fallback is not subject to the three-word segment rule.

## `judge(quote, page_text)`

Normalize the page and compute the segments. Find each segment with a substring
search. If the nonempty segment list is entirely found, return `verbatim`,
`segments`, `segments_found`, and `context`. Context starts up to 80 characters
before the first segment's first occurrence and ends 80 characters after that
segment. Segments need not appear in order or at distinct positions.

Otherwise join the segments, normalize again, and enumerate every consecutive
four-token sequence, including repetitions and sequences crossing segment
boundaries. The overlap is the number found as substrings in the page divided
by the total number; it is zero when no sequence exists. Return `paraphrase` if
that **unrounded** share is at least 0.5, otherwise `not_found`. Include
`segments`, `segments_found`, and `four_word_overlap` rounded to two decimals.
`judge` itself neither fetches a URL nor enforces public-tool quote length limits.
A paraphrase label measures this lexical overlap only, not semantic equivalence.

## Public-tool validation, fetching and failures

`verify_quote` coerces the quote to a string and strips surrounding whitespace.
Empty input or fewer than three whitespace-separated words returns
`ok: false, error: quote_too_short`. More than 600 characters after stripping
returns `ok: false, error: quote_too_long, max_chars: 600`. The short-quote check
comes first. Only then is the shared per-caller/global rate limiter consulted;
a limit failure returns `ok: false` and the limiter's error code.

The fetcher:

- accepts only HTTPS, with no username/password and no port other than omitted
  or 443; resolves and validates public addresses, then pins the connection to
  a validated address using `mcp_endpoint_verifier`;
- sends no caller credentials, cookies or JavaScript; `trust_env=False`;
- uses an HTTPX timeout of 15 seconds and allows up to three redirects;
  every target is validated again; redirect codes are 301, 302, 303, 307, 308;
  missing Location or a fourth redirect becomes `too_many_redirects`;
- rejects status codes at least 400 (`http_status`);
- accepts an absent Content-Type, or a lowercased header starting with
  `text/html`, `text/plain`, `application/json`, `application/xhtml` or
  `text/markdown`. These are prefix checks, not an exact MIME allowlist;
- consumes up to a 2 MiB (2,097,152-byte) budget of decoded response chunks.
  The entire first chunk that would exceed the budget is discarded, then
  fetching stops. The judged prefix can consequently be shorter than 2 MiB.
  The reported byte count is capped at 2 MiB and is not necessarily the exact
  length of the prefix actually judged. UTF-8 decoding replaces invalid bytes.

Validation/fetch failures represented by `VerificationError` or HTTPX HTTP
errors return `ok: true, outcome: unreachable` with a reason. They do not mean
the quote is false. Successful fetches add the judge result, public URL/status,
byte count, latency and an explanatory note. The MCP wrapper additionally
applies its overall deadline and returns `verification_deadline_exceeded` on a
timeout. Optional Ed25519 receipts cover these returned results too; see
[receipts](receipts.md). Protocol/authentication/rate rejection outside the tool
wrapper is not a quote verdict.

## Reproduce

```bash
python tools/verify_quote_conformance.py --local
python tools/verify_quote_conformance.py
```

The second command downloads the exact commit-pinned page and checks its SHA-256.
Both compare complete `judge` results with the vector's computed `expected`.
`expected_api` separately records stable tool fields, calculated by actually
calling `verify_quote` with the same page supplied through a mocked fetch.
Thus a two-word case has a real `judge` expectation and a distinct
`quote_too_short` public-tool expectation; neither is guessed.

Manually run `verify-quote-conformance.yml` on this PR's branch before merge.
It verifies all eleven offline cases and exactly six selected live tool calls,
without retries. Each live result must match the relevant offline expectation
and have a valid receipt under the key read directly from neo's HTTPS agent
card. It uses the existing signed smoke header so tests are not counted as real
demand. Annotations contain only counts/statuses. Divergence fails the workflow;
do not rewrite the vector to conceal a live/offline difference.
