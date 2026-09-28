# Pathwren current audit — 2026-09-28

Read-only audit target: `https://neo-collettive.onrender.com/mcp`.

Successful isolated run: GitHub Actions `36476963689`, completed at approximately `2026-09-28T20:07:44Z`.

## PATHWREN_FULL_RESPONSE — verdict text

```text
https://neo-collettive.onrender.com/mcp
  SCORE 100/100  (A)   0 blocking, 0 warnings, 76 advisory

  handshake     30 / 30
  tools         30 / 30
  errors        25 / 25
  discovery     15 / 15

  server            MYCELIX 0.99.42
  protocol          2026-07-28 → 2025-11-25
  tools             16 (16 schema-clean)
  error probes      4/5
  discovery served  mcp.json (well-known)
```

Structured verdict:

```json
{
  "score": 100,
  "of": 100,
  "grade": "A",
  "blocking_findings": 0,
  "warnings": 0,
  "advisory": 76,
  "usable_by_a_standard_client": true
}
```

There is no blocking finding and no warning to attribute to expected `403/review_required` behavior. Current effectful-tool protections therefore do not need to be relaxed to recover Pathwren points.

The response includes informational/advisory findings such as protocol downgrade to a mutually supported revision, missing human-readable titles, missing annotations, worked examples and property descriptions. They are not blocking findings or warnings in this run.

## Audit-run note

The first isolated audit attempt, run `36476723180`, failed before Pathwren produced a score because Python `urllib` received HTTP 403 from the Pathwren endpoint. The audit client was changed to the same curl-style request used by the existing release workflow. The subsequent run succeeded. This initial 403 was from the Pathwren audit endpoint, not a MYCELIX MCP finding.
