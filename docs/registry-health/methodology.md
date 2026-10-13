# MCP Registry Health methodology

## Scope

MCP Registry Health is a read-only measurement of public entries in the official Model Context Protocol Registry. The census starts from the documented `GET /v0.1/servers` collection and follows the Registry-provided opaque `nextCursor` value until no cursor remains. Cursors are never generated or modified by MYCELIX.

For each Registry name, the dataset retains only the record whose official Registry metadata says both:

- `isLatest: true`
- `status: active`

The snapshot timestamp, page count and raw active/latest metadata needed to reproduce the census are stored with each run.

## Remote and package-only entries

Entries are separated before health classification.

**Remote-verifiable** means that the latest active server record declares at least one HTTPS `streamable-http` remote. The first declared HTTPS `streamable-http` remote is used as the server's measurement target and all declared remote URLs remain in the snapshot.

**Package-only** entries publish packages such as npm, PyPI, Docker or other local/stdio installation artifacts but do not declare a remotely verifiable HTTPS `streamable-http` endpoint. They are counted separately and are never described as dead, down or unreachable.

Other declared remote transports that are not HTTPS `streamable-http` are counted as *remote, transport not verified*. Entries with neither a supported remote nor a package are counted as metadata-only.

## What the verifier does

Every endpoint probe reuses `mcp_endpoint_verifier.py`; MCP Registry Health does not contain a second MCP verifier.

The scanner runs on GitHub Actions, not on the MYCELIX Render production instance. Each endpoint probe is limited to read-only protocol and discovery checks:

1. URL syntax and SSRF validation.
2. DNS resolution, rejecting non-global addresses, localhost, link-local, RFC1918, CGNAT/shared space, IPv6 ULA and known metadata hosts.
3. HTTPS/TLS using the runner's system CA validation.
4. MCP `initialize`.
5. The standard `notifications/initialized` handshake notification when applicable.
6. MCP `tools/list`.
7. Input-schema sanity checks for returned tools.
8. Read-only discovery-document checks.

It never sends `tools/call`, never forwards Authorization, Cookie or caller credentials, never tries alternate credentials after 401/403, and never attempts to bypass access controls.

Responses are size-limited and redirects are revalidated against the same SSRF policy. A maximum of three redirects is followed.

## Scanner identity and pacing

The scanner identifies itself as:

`MYCELIX-RegistryHealth/<VERSION> (+https://neo-collettive.onrender.com/registry-health/about)`

Request-level limits are:

- maximum four concurrent requests globally;
- maximum one concurrent request per host;
- a pause between requests to the same host;
- short connect/read timeouts;
- the same response-size and SSRF limits used by `verify_mcp_endpoint`.

Registry Health calls are tagged `internal_registry_health`. They have separate aggregate telemetry and are excluded from the external `verify_mcp_endpoint` usage metrics used by MYCELIX market evidence.

## Classification versions

Registry Health classifications are explicitly versioned.

**classification_version = 1** is the historical policy used for the 27 September 2026 FINAL sample and the 40 Arena predictions created from it. It required discovery metadata for `OK`.

**classification_version = 2** is current. `OK` means valid MCP `initialize`, valid `tools/list`, valid returned input schemas, and no MCP or verifier error. `discovery_present` is independent metadata and does not affect the category.

Historical raw probe observations are immutable. New classification policies are represented by derived views calculated from those persisted probes rather than by rewriting historical observations.

Every future Registry Health scan writes both classification views from the same persisted probes: v2 is the current view and v1 is the compatibility view. The v1 compatibility view is retained for as long as at least one external Arena prediction with `classification_version = 1` remains open. Historical v1 predictions are evaluated against the later scan's v1 view; new predictions use v2.

## Categories

Each remotely verifiable server receives exactly one final category.

### OK

Under v2, `initialize` succeeds, `tools/list` succeeds, every returned input schema passes structural sanity checks, and no MCP or verifier error is recorded. Under historical v1, discovery presence was also required.

### OK_WITH_ISSUES

The endpoint responds as MCP and `initialize` succeeds, but a non-fatal MCP/verifier issue remains, such as a failed `tools/list`, invalid input schema, or verifier warning. Missing discovery alone is not an issue in v2.

### AUTH_REQUIRED

The endpoint responds with HTTP 401 or 403 during initialization. No credential is supplied and no authentication bypass is attempted. This category is not treated as downtime.

### SERVER_ERROR

The endpoint returns a 5xx response during initialization.

### NOT_MCP

The endpoint is reachable over HTTP(S), but the initialization response cannot be validated as an MCP server and is not better explained by an authentication or 5xx response.

### UNREACHABLE

The GitHub Actions runner cannot establish a usable public connection because of DNS, TLS/transport, connection or timeout failure, or the endpoint is rejected by the verifier's network-safety policy.

### INTERMITTENT

This is a final two-probe category. If the first and second probe produce different categories, the final result is `INTERMITTENT` and both observations remain in the dataset.

## Two-probe rule

A server classified `OK` or `AUTH_REQUIRED` on the first probe is final after that probe.

Every other remote result is probed a second time no earlier than six hours after the first scan began. The second phase refuses to run before the stored `second_probe_not_before_utc` timestamp.

If both probes agree, that category is the final category. If they disagree, the final category is `INTERMITTENT`. Both timestamps and both compact probe records are retained.

## Collected fields

For each remotely verifiable server the public dataset contains, where available:

- Registry name and version;
- declared remote URL;
- final/provisional category;
- negotiated MCP protocol version;
- number of tools;
- valid and invalid input-schema counts;
- discovery-document presence;
- TLS validation result;
- aggregate observed request latency;
- timestamps of probe one and probe two;
- anonymous per-host request counts for the scan.

Response bodies, credentials, cookies, personal identifiers and caller IP addresses are not stored.

## Known limitations

The report is a measurement from GitHub-hosted Actions runners. A server reported `UNREACHABLE` may be reachable from another network, region or allow-listed environment.

An `AUTH_REQUIRED` result says only that anonymous access was not accepted; it does not evaluate the authenticated service.

Latency is observational and is not a benchmark of application performance. Future scans persist `initialize`, `tools/list`, and discovery-request latencies separately; the primary reported latency is `initialize` median and p90.

The 27 September 2026 FINAL dataset predates this split. Its stored `total_observed_latency_ms` is a legacy aggregate and contains a double count of `initialize` (HTTP plus initialize). It remains unchanged for reproducibility and must not be interpreted as initialize latency.

The persisted FINAL probes do not contain enough raw timing fields to reconstruct `initialize` latency: across the persisted probes there is no `initialize_latency_ms`, no `checks.initialize.latency_ms`, no persisted `tools/list` timing, and no per-discovery timing. Therefore no reconstructed initialize baseline is published for 27 September 2026. The first valid initialize-latency comparison is the replay of the same sample on 4 October 2026 versus the replay of the same sample on 11 October 2026, using the new separately persisted initialize timings.

Only the Registry-declared HTTPS `streamable-http` target is measured. Package-only, stdio and unsupported remote transports require a different testing model and are deliberately excluded from remote-health categories.

Discovery presence is independent metadata in v2 and does not declassify an otherwise healthy MCP endpoint.

The scan does not evaluate tool correctness, business logic, authorization quality, data safety, or what a tool would do if called. Tools are never invoked.

## Opt-out

The repository file `data/registry-health/opt-out.txt` accepts one exact Registry server name or exact HTTPS remote URL per line. Matching entries are omitted from endpoint probing in future scans.

A server owner can request an opt-out or correction through the public contact channels of the `Toramo747/Neo-collettive` repository, identifying the Registry name, the affected endpoint and enough public evidence to verify ownership or the correction. A pull request that adds the exact identifier to the opt-out file is also suitable.

Opted-out entries remain part of the aggregate Registry census when they are present in the official Registry, but they are not probed and are excluded from health-category percentages.

## Corrections

Corrections are evidence-based. When a Registry owner supplies a corrected public endpoint or points to a Registry record that changed, MYCELIX uses the current official Registry record in the next scan. Historical datasets are not silently rewritten; a material correction can be documented alongside the affected snapshot.

## Data license

The files under `data/registry-health/` are licensed CC BY 4.0 with attribution to Andrea Gava / MYCELIX. See `LICENSE-DATA`. The source code remains under its existing BUSL-1.1 terms.
