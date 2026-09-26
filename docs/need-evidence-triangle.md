# Need → discovery → verification → evidence

Status: design note only. This document does not change runtime behavior, SETI admission, or the commercial gate.

## Observed working path

1. A public, SETI-observed peer exposes a bounded need.
2. MYCELIX treats the peer response and all returned URLs as untrusted data.
3. Discovery uses existing registry adapters to locate candidate public agents/MCP servers.
4. Every candidate URL passes the existing public-HTTPS safety checks before any contact.
5. A read-only verifier may inspect liveness/conformance.
6. The result is stored as evidence with source URL, timestamp, transport status, and verifier identity.
7. Evidence may be returned to the originating peer only through a documented public action that matches the purpose. If no such action exists, MYCELIX prepares the payload but does not invent a protocol action.

## Existing modules to reuse

- `a2a_peer.py`: bounded A2A request/reply transport and protocol parsing.
- `seti_radar.py`: candidate eligibility, admission and interview state. Admission rules remain authoritative.
- `cloud_mcp.py::_safe_public_https`: public endpoint safety boundary.
- `cloud_mcp.py::inspect_mcp_server`: read-only MCP initialize/tools inspection.
- `tool_opportunity.py`: URL-grounded commercial evidence and unchanged gate.
- `neo_dialect_security.py`: hostile/untrusted message controls.
- `aion_magi_stimulus.py`: temporary experiment proving structured A2A discovery.
- `mcp_liveness_thesis.py`: temporary zero-cost market/evidence evaluator.

## Minimal future implementation

Do not build a new subsystem. If this path is promoted to runtime capability, add one small orchestration function that composes the modules above and emits a typed result:

`need -> candidates -> verification -> evidence -> optional documented reply`

Required fields:

- need source URL/id
- candidate source URL
- safety validation result
- liveness/conformance result
- verifier and timestamp
- external action taken (normally none)
- payment/account/membership flags, all false by default
- reply action id, only when explicitly documented by the peer

## Stop conditions

Stop and record negative evidence when:

- URL is unsafe or non-HTTPS;
- DNS/connection fails;
- authentication or payment is required;
- peer asks for membership/account creation;
- no documented reply action exists;
- verification would require a state-changing tool;
- SETI admission would need to be weakened.

No retry path may fall back to a paid service.
