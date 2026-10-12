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
