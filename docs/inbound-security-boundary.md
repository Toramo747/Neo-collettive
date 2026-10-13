# Inbound non-execution boundary

Baseline: commit `30aeb80` at 2026-09-28T07:07:09Z.

## External ingress map

| Ingress | Code entry | Boundary before external effect | Promotion rule |
|---|---|---|---|
| A2A `POST /a2a` | `a2a_endpoint` | inbound content is handled as untrusted data; security classifier may suppress obvious abuse, but safety does not depend on classifier keywords | `_record_inbound_agent_message` can only call `stage_inbound_claim`; it cannot write `knowledge_ledger` or `hypothesis_queue` |
| MCP `POST /mcp*` `tools/call` | `_InboundTrafficASGI` | server-side `explicit_review_authorized` check before MCP dispatch; reviewed calls are rate-limited per caller | no unreviewed tool execution is reachable |
| Effectful public HTTP APIs | `_ExplicitReviewASGI.guarded_methods` | method/path allow-list requires server-side review token before handler dispatch | blocked response declares fetch/execution/install/ledger/hypothesis all false |
| Runtime callback/webhook `POST /api/runtime/snapshot-published` | `_ExplicitReviewASGI` | same explicit-review boundary before webhook handler | no unreviewed state mutation or downstream effect |
| Passive public GET/read APIs and pages | Starlette route table | no user-provided URL/code is promoted into an external action; they expose local/read-only projections | no ledger or hypothesis promotion path |

Guarded HTTP methods are: `GET /api/discover`, `GET /api/collective`,
`GET /api/director/run`, `POST /api/market/run-cycles`, `GET /api/heartbeat`,
`POST /api/runtime/snapshot-published`, `POST /api/trust/evaluate`,
`POST /venture`, `GET|POST /api/venture/audit`, and
`POST /api/venture/measurement`.

The end-to-end regression file is `test_inbound_e2e.py`. Its malicious sample is
intentionally obfuscated and does not rely on classifier keywords. Tests assert no
network client is created, no ledger entry is added, and no hypothesis is created.

## Outbound SSRF policy

Untrusted or configurable network targets use `mcp_endpoint_verifier` as the shared
network boundary.

* HTTPS only, standard port 443, no URL userinfo.
* Hostnames ending in `.local` or `.internal` are rejected, including Render-style internal names.
* DNS is resolved before the request. Any non-global IPv4/IPv6 result blocks the target.
  This covers loopback, RFC1918, link-local/metadata addresses such as
  `169.254.169.254`, carrier-grade NAT, IPv6 ULA/link-local, multicast and reserved ranges.
* Redirects are manual and every target is DNS-validated again.
* Maximum redirects: 3.
* Connect timeout: 5 s; read/write timeout: 8 s.
* Maximum response body: 256 KiB.
* `verify_mcp_endpoint` has per-caller and global rate limits. Reviewed MCP
  `tools/call` requests are also rate-limited per caller before dispatch.
* The bounded request primitive is reused for dynamic A2A peer calls, MCP inspection
  and evidence revalidation. Configurable Jarvis targets are DNS-validated before use.

## Telemetry baseline

Historical events are retained. During summarization, any event still classified
`real_contact` with timestamp before `2026-09-28T07:07:09Z` (commit `30aeb80`)
is reclassified as `legacy_unattributable`.

`legacy_unattributable` is excluded from official `real_contact` counters but the
original category and reason are preserved in the event. Known self traffic is
reclassified first, so known internal activity remains `self_traffic` rather than legacy.

The official contact count therefore begins at commit `30aeb80`.
