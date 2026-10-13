# MCP Registry Health Sample Report — 2026-09-27

**Draft — not published externally.**

**SAMPLE ONLY — 663 Registry remotes. These results describe only the sampled servers and must not be interpreted or published as statistics for the entire MCP Registry.**

## Sample definition

- Scope: **SAMPLE**
- Sample size: **663**
- Recorded random seed: **2140928784970561546**
- Remote population visible in the Registry snapshot: **21603**
- Sampling method: randomized order with the recorded seed; observations stop at the configured time budget.

## Sample remote-health categories

| Category | Count | Share of sampled remotes |
|---|---:|---:|
| OK | 220 | 33.2% |
| OK_WITH_ISSUES | 205 | 30.9% |
| AUTH_REQUIRED | 161 | 24.3% |
| SERVER_ERROR | 12 | 1.8% |
| NOT_MCP | 33 | 5.0% |
| UNREACHABLE | 23 | 3.5% |
| INTERMITTENT | 9 | 1.4% |

## Protocol and conformance observations

- Negotiated protocol versions: `2025-11-25`: 221, `2025-03-26`: 145, `2025-06-18`: 50, `2024-11-05`: 14, `2026-07-28`: 3
- Invalid tool input schemas observed: **0**
- Discovery document present: **260/663 (39.2%)**
- TLS-validation failures: **23**
- Aggregate observed latency: median **4527.25 ms**, p90 **7978.36 ms**

## Key findings

- Within this 663-server sample, 220 were classified OK and 161 required authentication.
- Discovery metadata was observed for 260 of 663 sampled remotes (39.2%).
- The sample observed 0 invalid tool input schemas and 23 TLS-validation failures.
- Observed sample latency had a median of 4527.25 ms and p90 of 7978.36 ms across 648 samples.

## Methodology and data

- [Methodology](../registry-health/methodology.md)
- [JSON dataset](../../data/registry-health/2026-09-27/registry-health.json)
- [CSV dataset](../../data/registry-health/2026-09-27/registry-health.csv)
- [Registry snapshot](../../data/registry-health/2026-09-27/registry-snapshot.json)

Dataset license: CC BY 4.0, attribution to Andrea Gava / MYCELIX. Code remains under its existing BUSL-1.1 license.
