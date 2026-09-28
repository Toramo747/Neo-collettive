# Health-check latency audit — 2026-09-28

Scope: observation and proposal only. No health endpoint or public route was changed.

## Observed production samples

Two persisted heartbeat measurements were reviewed.

Earlier capture `2026-09-28T18:41:38.234072+00:00`:
- /health first: 321.15 ms; subsequent: 438.90 ms.
- /mcp initialize first: 381.84 ms; subsequent: 376.53 ms.

Latest capture `2026-09-28T20:09:28.715360+00:00`:
- /health first/cold-start candidate: **782.59 ms**; subsequent: **670.33 ms**.
- /mcp initialize first: **589.42 ms**; subsequent: **595.93 ms**.

The earlier run had a slower warm health sample; the later run had a ~112 ms slower first health sample. MCP initialize stayed essentially flat within each run. This is compatible with ordinary network/scheduler variance plus some possible first-request warm-up, but it does not support attributing the whole health latency to a cold start.

## Application work performed by /health

The current `health()` handler:
1. calls `_record_inbound_traffic(request)`;
2. computes `_runtime_snapshot_freshness()`;
3. returns JSON.

`_runtime_snapshot_freshness()` is in-memory arithmetic only.

`_record_inbound_traffic()`, however, classifies the request, appends/summarizes telemetry and calls `_save_local_state()`. `_save_local_state()` serializes the full state payload and writes it to `STATE_SNAPSHOT_PATH` on local disk.

Therefore the current health endpoint is not a minimal liveness probe. It performs telemetry/state serialization and disk I/O on every health request. The observed curl latency also includes DNS/TLS/network/Render ingress and scheduling time; the persisted samples do not contain server-side timing spans, so the exact contribution of disk serialization versus network cannot be measured from these data alone.

## Deduction

- A cold-start component is possible in the latest run (~112 ms first-vs-warm difference on /health), but it is not stable across runs and is not sufficient to explain the full latency.
- Network/Render ingress is a material baseline candidate because MCP initialize tracks a similar hundreds-of-milliseconds baseline and is nearly flat first-vs-warm.
- Health-specific state persistence is a real avoidable application-side cost, but its exact milliseconds are not currently instrumented.

## Proposed split — REVIEW REQUIRED BEFORE IMPLEMENTATION

Do not apply without explicit review because it would add/alter public health surfaces.

Suggested design:
- **liveness**: a lightweight endpoint such as `/livez` (or a redefined `/health`) returning a constant process-alive response plus version/commit. No inbound telemetry persistence, disk write, network call or dependency check.
- **readiness**: a separate endpoint such as `/readyz` containing runtime-snapshot freshness and any explicitly selected dependency/readiness checks.
- record probe telemetry outside the synchronous liveness path, or only in aggregated/in-memory form if it is required.

Before implementation, measure server-side elapsed time around the existing `_record_inbound_traffic` and state serialization in a non-production test or bounded diagnostic so the optimization has a baseline.
