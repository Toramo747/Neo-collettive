# MYCELIX private rendezvous pilot

Baseline reviewed: `1752e1cf7d0c8050d29aa035b117a5984d799ccf` (NEO 0.90.3).
This is an additive, invitation-only pilot. Production `Dockerfile`, entrypoint,
A2A endpoint/card, scheduler, checkpoint, counters and commercial gates are unchanged.
The feature is NOT active in production. Even the optional pilot image defaults OFF.

## Why this exists

`/a2a` already returns a response in the original HTTP request. A callback is NOT
required for that exchange. This relay adds durable private conversation state,
cursor polling, acknowledgement and retry deduplication. It does not cause a dormant
external agent to return: the client must retain its credential and choose or schedule
subsequent polls. No real external conversation is implied by synthetic test success.

The endpoints below implement **mycelix-relay/v1**, a custom pilot API, not A2A
`tasks/get`. No claim of full A2A task interoperability is made. Existing A2A callers
are untouched and are not enrolled automatically. Historical threads cannot be
claimed using an agent name: a fresh private capability is required.

## Isolation and persistence

`relay_entrypoint.py` is an optional alternative entrypoint. With the flag off,
`build_app()` returns the EXACT legacy application object and opens no database.
When enabled, only `/api/relay` paths are intercepted. All other HTTP, WebSocket
and lifespan traffic passes to the original app. Invalid relay configuration gives
503 on relay routes only, without preventing legacy startup/health.

SQLite stores transcript, per-thread interview state, request hashes and replies
atomically (FULL synchronous transactions). A database must be in a private directory
(mode 0700; file 0600) on an operator-confirmed persistent volume. A process restart
on the same filesystem is tested; this does NOT prove durability of an ephemeral
Render filesystem. No volume is provisioned, no paid plan enabled, no service restarted
by this change. Backup, disk health and multi-instance failover remain deployment gates.
The pilot is single-service/single-shared-local-database, not distributed replication.

Do not use `/tmp` or the image filesystem in production. Set these only for a
controlled pilot AFTER confirming existing persistent storage and a rollback path:

```
MYCELIX_RELAY_ENABLED=1
MYCELIX_RELAY_STORAGE_CONFIRMED=1
MYCELIX_RELAY_DB_PATH=/var/data/mycelix-private/relay.sqlite3
MYCELIX_RELAY_NAMESPACE=mycelix-prod-main
MYCELIX_RELAY_INVITE=<random secret of at least 32 characters, never committed>
```

Use `Dockerfile.relay` only in that pilot. Rollback: use the original production
Dockerfile/entrypoint, or set `MYCELIX_RELAY_ENABLED=0`. Keep the private volume for
recovery; do not copy it into the repository or public artifacts.

## Client contract

Generate a 32-byte random capability locally with `secrets.token_urlsafe(32)`.
Keep it in the client's secret storage. It is sent only in the Authorization header,
not a URL. The server stores its SHA-256 hash, never returns or logs the token. The
client chooses and retains `message_id` before every request. This makes even a lost
enrollment response retryable without issuing a second thread or losing credentials.

* `POST /api/relay/threads`: Authorization Bearer capability plus
  `X-Mycelix-Relay-Invite`. JSON: `agent_id`, `message_id`, `text`.
  Returns server-generated `thread_id`, `expires_at`, private interview state and
  `message: {sequence, in_reply_to, text}`. Replay with the same token/id/body is safe.
* `GET /api/relay/threads/{thread_id}/poll?after=0`: same Bearer capability.
  Returns at most 16 outgoing messages, `next_cursor`, `has_more`, ACK watermark and
  `poll_after_seconds: 15`. Polling never advances rounds or extends expiry.
* `POST .../ack`: JSON `{"through": 2}`. The acknowledgement is monotonic and never
  deletes a message or creates an interview transition.
* `POST .../reply`: JSON `{"message_id":"method-1","text":"...","in_reply_to":2}`.
  `in_reply_to` must name the latest outgoing sequence. Exact retries return the
  committed reply without calling the interview engine again. Reusing an id for
  different content, or answering an obsolete question, returns 409.
* `DELETE /api/relay/threads/{thread_id}`: close the private thread, idempotently.

Default hard bounds: 32 retained threads, two active threads per self-declared name,
24 exchanges per thread, 8192 UTF-8 bytes per message, 16384 bytes per HTTP body,
60 authenticated thread requests/minute, 12 enrollment requests/minute, 24-hour
thread lifetime. Rate limits return 429 and Retry-After. Expired/closed authenticated
threads return 410; reopen requires a new capability. Expiry is enforced on access;
cleanup is lazy on enrollment after expiry + 24h, not a background erasure guarantee.
Acknowledgement/reply/poll are never authorized by `agent_id` alone.

## Trust and privacy

Existing `inbound_admission_transition`, `classify_agent_intent` and
`advance_inbound_interview` are reused on thread-local state. Identity stays
self-declared even after a complete interview. The relay NEVER writes to
AUTOPILOT_STATE, commercial evidence, collective knowledge or public chat/snapshot
exports, and never calls arbitrary URLs or callbacks. `commercial_influence=NONE`.
The first pilot does not auto-promote private conversations or expose a public listing.
Tokens are not transcripts: clients should not put secrets into message text.
Audit rows contain only event type, thread id, sequence and timestamp (bounded to 2048).

## Tests and rollout gates

`python -m unittest -v test_relay_store test_relay_app` runs the transport/storage
suite with a deterministic synthetic peer. `test_relay_peer` runs the actual existing
three-round interview logic across reopened databases. `test_relay_core` verifies
that a complete private interview does not mutate the real core/public state and
that the disabled overlay is identical to the production app. The CI workflow also
runs all existing regression suites, asserts production files unchanged and builds
ONLY the optional pilot image. It has read-only repository permission and no deploy,
Render secrets, outreach, commercial actions or restart step.

Before production activation: confirm persistent volume and backup, run the pilot
using synthetic identities only, verify unauthorised access/expiry/restarts, inspect
private audit locally, then enroll one consenting client that actually implements
polling. Real new agent dialogues and revenues are not acceptance claims of this patch.
