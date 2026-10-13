# Inbound telemetry and execution safety

Inbound A2A text is untrusted data. It is parsed only to classify, preserve evidence,
and produce a bounded protocol response. `malicious_solicitation` is assigned before
admission, dialect handling, interview advancement, knowledge-ledger promotion, or
agent-chat generation.

For this category the A2A handler:

- stores a redacted security evidence event and the telemetry event;
- returns an empty, suppressed response;
- sets fetch, execution, installation, conversation, and commercial influence to false;
- never forwards the content to Jarvis, SETI, the collective, the knowledge ledger,
  hypothesis generation, market discovery, or endpoint verification.

No inbound field is passed to `subprocess`, `exec`, `eval`, a package manager, or a
network client. Network-capable modules operate only on their own configured URLs or
separately admitted and validated peer coordinates. The malicious-solicitation guard
is deliberately before every such downstream path.

Telemetry events are part of the durable state payload and are union-merged across
local, Render-environment, repository, and recovery candidates. Deduplication uses an
explicit event ID when available, otherwise immutable request metadata. This applies
to crawler probes, self traffic, pending active probes, real contacts, malicious
solicitations, and unknown events.

An anonymous A2A client whose user-agent explicitly identifies a probe, health check,
or liveness check starts as `real_contact_pending`. A second equivalent request from
the same source, with the same normalized content fingerprint, within 60 minutes
reclassifies both requests as `crawler_probe` with reason
`active_a2a_probe_repeated_within_60m`.
