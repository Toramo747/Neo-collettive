# Health-check latency audit — 2026-09-28

Scope: observation and proposal only. No health endpoint or public route was changed.

## Observed production samples

Persisted heartbeat snapshot captured at `2026-09-28T18:41:38.234072+00:00`:

| endpoint | phase | HTTP | latency |
|---|---|---:|---:|
| /health | first request / cold-start candidate | 200 | 321.15 ms |
| /mcp initialize | first phase, not first HTTP request | 200 | 381.84 ms |
| /health | subsequent sample | 200 | 438.90 ms |
| /mcp initialize | subsequent sample | 200 | 376.53 ms |

The second `/health` sample was slower than the first. This measurement therefore does not support attributing the 321–439 ms range primarily to a cold start.

## Application work performed by /health

The current `health()` handler:
1. calls `_record_inbound_traffic(request)`;
2. computes `_runtime_snapshot_freshness()`;
3. returns JSON.

`_runtime_snapshot_freshness()` is in-memory arithmetic only.

`_record_inbound_traffic()`, however, classifies the request, appends/summarizes telemetry and calls `_save_local_state()`. `_save_local_state()` serializes the full state payload and writes it to `STATE_SNAPSHOT_PATH` on local disk.

Therefore the current health endpoint is not a minimal liveness probe. It performs telemetry/state serialization and disk I/O on every health request. The observed curl latency also includes DNS/TLS/network/Render ingress and scheduling time; the persisted samples do not contain server-side timing spans, so the exact contribution of disk serialization versus network cannot be measured from these data alone.

## Deduction

- Classic cold start is not demonstrated by this sample: the warm health request was ~118 ms slower.
- Network/Render ingress is a material baseline candidate because MCP initialize is in the same ~0.38 s range.
- Health-specific state persistence is a real avoidable application-side cost, but its exact milliseconds are not currently instrumented.

## Proposed split — REVIEW REQUIRED BEFORE IMPLEMENTATION

Do not apply without explicit review because it would add/alter public health surfaces.

Suggested design:
- **liveness**: a lightweight endpoint such as `/livez` (or a redefined `/health`) returning a constant process-alive response plus version/commit. No inbound telemetry persistence, disk write, network call or dependency check.
- **readiness**: a separate endpoint such as `/readyz` containing runtime-snapshot freshness and any explicitly selected dependency/readiness checks.
- record probe telemetry outside the synchronous liveness path, or only in aggregated/in-memory form if it is required.

Before implementation, measure server-side elapsed time around the existing `_record_inbound_traffic` and state serialization in a non-production test or bounded diagnostic so the optimization has a baseline.
