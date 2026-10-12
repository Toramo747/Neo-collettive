# Free MCP verifier test (started 2026-10-12)

Decision (Andrea, 2026-10-12): before building any paid API, test whether
anyone uses OXIBAY's MCP verification for free.

Finding that triggered it: `verify_mcp_endpoint` and `oxibay_doctor` were
already listed in the official MCP Registry, but gated (admin only). Crawlers
called `initialize`/`tools/list` (~86 times in the last buffer) and nobody
external could call a tool: the listing was a shop window with a locked door.

Change:
- both tools are `public_network`: callable without a key, 10 calls per origin
  per hour, 500 per day globally, plus the verifier's own per-minute limits;
- outbound connections are pinned to the IP that passed the SSRF check, with TLS
  verified against the real hostname (closes DNS rebinding before going public);
- usage is counted per tool (calls, hashed origins, traffic category), admin and
  self traffic excluded; the 6-hourly private monitor logs the aggregates.

Rule fixed now, before results: after 4 weeks, a paid tier is worth building
only if at least **10 distinct external origins** called a tool and at least
**3 of them came back on a different day**. Fewer means no demand at this
price (zero); the result is kept either way.

## Security review before opening (2026-10-12)

Andrea asked for a second security pass before deploy. Found and fixed:

1. **Spoofable rate-limit key** (high): limits and usage were keyed on the
   Origin/Referer headers or the first X-Forwarded-For hop, all chosen by the
   caller, so one client could dodge the per-origin limit and fake "distinct
   users". Now keyed on the edge header (CF-Connecting-IP / True-Client-IP),
   else the last X-Forwarded-For hop, else the socket peer.
2. **DNS rebinding** (high once public): connections pinned to the IP that
   passed the SSRF check; TLS verified against the hostname.
3. **IPv6 translation ranges** (medium): NAT64 `64:ff9b::/96`, `64:ff9b:1::/48`,
   IPv4-compatible `::/96` and private IPv4 embedded in 6to4/Teredo/mapped
   addresses are blocked (Python reports some of them as global).
4. **Cross-user leak** (medium): every verification returned the list of
   domains other callers had checked. Tool output now carries totals only; the
   in-memory domain table is capped at 500.
5. **Slow-drip hold** (medium): only per-read timeouts existed; a public call
   now has an overall 45 s deadline.
6. **Internal DNS oracle** (low): blocked addresses are no longer echoed in errors.
7. Rate-limit table pruned to stay bounded.

Unchanged and verified: HTTPS on port 443 only, no userinfo, redirects
re-validated per hop, 256 KB response cap, no credentials forwarded, never
calls remote tools, results never written to the knowledge ledger or
hypothesis queue, other network tools remain admin-only.

## Go-live (2026-10-12, authorized by Andrea)

Deployed as 0.99.55 and republished in the official MCP Registry ("Free,
no-key, read-only MCP endpoint verification and diagnostics."). External smoke
from a GitHub runner: anonymous `initialize` 200, anonymous `verify_mcp_endpoint`
200 (live, all checks present, no other callers' domains in the output),
anonymous gated tool 403, 11th call in the hour 429.
**Baseline correction:** the two smoke runs came from 2 runner IPs; subtract
2 origins and their 22 calls when applying the 4-week rule.
