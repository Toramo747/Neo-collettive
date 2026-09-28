# Mavis / EVO-AI indirect-path audit — 2026-09-28

Scope: read-only audit of persisted runtime state and the A2A inbound path. No ledger or runtime state was modified.

## Persisted evidence

The current persisted snapshot contains one Mavis-related record in `inbound_security_events`:
- source message id: `m-1790571012-15`
- received: `2026-09-28T04:50:12.687030+00:00`
- class: `MALICIOUS_SOLICITATION`
- reason: `download_execute_or_reward_solicitation`
- response suppressed: true
- stored text is a redacted descriptive excerpt, not the executable solicitation.

No Mavis/EVO-AI/paste.rs/47.253.174.153 match is present in the current persisted:
- `knowledge_ledger`
- `hypothesis_queue`
- `inbound_review_queue`
- `dialogue_history`
- `jarvis_dialogue_history`
- `agent_chat_events`
- `commercial_evidence_memory`
- current `inbound_messages`.

The historical recovery commit `33f03b9961df7b389817865e1ccf771ca58e8fe0` restored only a traffic fingerprint/classification and a redacted security event; it did not restore the raw solicitation into the knowledge ledger.

## Runtime path

In `a2a_endpoint`, traffic classification happens before the normal inbound-agent recording path. A request classified `malicious_solicitation` is passed only to the security-event recorder, which stores `redact_security_text(text)`, then returns a response with empty parts and:
- `response_suppressed=true`
- `conversation_allowed_bounded=false`
- `commercial_influence=NONE`
- `fetch_allowed=false`
- `execution_allowed=false`
- `installation_allowed=false`.

The handler returns at that point. It does not reach `_record_inbound_agent_message`, `_inbound_reply_text`, interview progression, claim staging, agent-chat append, knowledge-ledger promotion, hypothesis creation, Jarvis, SETI or commercial discovery.

## Conclusion

Verified from current persisted state and code: the Mavis solicitation is represented only as security/traffic evidence with redaction and a content fingerprint. No evidence was found that the solicitation text was placed in an LLM prompt or normal engine conversation context, or promoted to ledger/hypothesis/commercial memory.

This audit does not modify or quarantine any existing ledger entry.
