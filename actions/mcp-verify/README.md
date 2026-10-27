# neo mcp-verify (GitHub Action)

Read-only check of your own public MCP server on every push, through neo's free, keyless verifier
(DNS/SSRF safety, TLS, `initialize`, `tools/list`, latency). The job fails when the check does not pass.

```yaml
- uses: Toramo747/Neo-collettive/actions/mcp-verify@main
  with:
    url: https://your-server.example.com/mcp
    # fail-on: never   # report only
```

What it does not check: tool descriptions and schemas (tool poisoning), authentication, remote tool calls.
The free result is not signed. A signed, publicly logged audit that covers descriptions and schemas is a paid
x402 service (`POST https://neo-collettive.onrender.com/x402/mcp-audit`, 0.80 USDC); a free signed sample of it
is at `GET https://neo-collettive.onrender.com/x402/mcp-audit/sample`.

Only your server is contacted (one read-only probe from neo), nothing is stored beyond aggregate counters.
