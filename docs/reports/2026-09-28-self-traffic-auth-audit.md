# Self-traffic authentication audit — 2026-09-28

## Verified pre-change behavior

The static header `x-mycelix-self-traffic` had two security-relevant uses:

1. **Telemetry classification** — any non-empty self marker was classified as `self_traffic`.
2. **Heartbeat review bypass** — `_ExplicitReviewASGI` accepted the literal value `github-actions-heartbeat` as sufficient to pass the explicit-review guard for `GET /api/heartbeat`.

It did **not** exempt the heartbeat handler from its caller rate limit. `api_heartbeat` still calls `endpoint_verifier.consume_rate_limit()`.

For MCP `tools/call`, the marker did not bypass the separate effectful-tool review gate.

## Hardening implemented on review branch

Branch: `mycelix-self-traffic-hardening-20260928`.

The proposed implementation uses HMAC-SHA256 with the existing `NEO_HEARTBEAT_TOKEN` secret:
- signed message: `<unix_timestamp>\n<request_path>`
- proof header: `X-MYCELIX-Self-Traffic-Proof: <timestamp>:<hex_hmac>`
- accepted clock skew: ±300 seconds
- constant-time HMAC comparison.

The marker remains descriptive; only a valid proof makes it authenticated self traffic.

Invalid/missing/expired proof:
- does not yield `self_traffic`;
- follows normal external classification;
- records `spoofed_self_marker=true` and a proof-failure reason when a marker was supplied;
- does not bypass the heartbeat review guard.

Rate limiting remains enabled.

Effectful MCP tools remain behind explicit review.

## Tests

Dedicated GitHub Actions run `36477138639` passed **38 tests**.

Security cases include:
- valid signed marker → authenticated self traffic / heartbeat accepted;
- marker without proof → treated as external and heartbeat review rejected;
- proof older than 300 seconds → rejected;
- effectful MCP tool call remains blocked before tool execution;
- invalid MCP requests retain protocol semantics;
- read-only bounded MCP access remains inert with respect to ledger/hypothesis state.

## Historical marker review

Current persisted telemetry contains GitHub-style static markers only in these production windows:
- `github-actions-deploy`, source `57.154.218.73`, curl/8.5.0, around 18:20:51–18:20:54 UTC;
- `github-actions-heartbeat`, source `68.220.58.241`, curl/8.5.0, around 18:21:47–18:21:49 UTC;
- `github-actions-heartbeat`, source `40.81.7.226`, curl/8.5.0, around 18:41:36 UTC.

Those windows coincide with persisted GitHub Actions deploy/heartbeat activity. No persisted static GitHub marker was found outside those action-correlated windows. This is a timing/source correlation, not a retrospective cryptographic proof of origin. No historical event was reclassified.

## Deployment prerequisite

Before merging/deploying, verify that the same non-empty `NEO_HEARTBEAT_TOKEN` value is configured in:
- GitHub Actions Secrets; and
- the Render runtime environment consumed as `HEARTBEAT_TOKEN` / `NEO_HEARTBEAT_TOKEN` by the service.

If the shared secret is absent or mismatched, the new path fails closed and the signed GitHub heartbeat cannot authenticate.
