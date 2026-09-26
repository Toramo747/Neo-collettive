# neo-dialect/1.0

## Scope

**neo-dialect/1.0** is a message-format dialect carried **over standard A2A**. It does not replace A2A transport, discovery, authentication, task handling, or error handling.

This specification defines message structure only. It does not instruct a peer how to behave, which goals to pursue, which tools to use, or how to change its internal policy.

- Version: `neo-dialect/1.0`
- Transport compatibility: standard A2A
- Canonical specification URL: `/neo-dialect/1.0`
- JSON Schemas: `schemas/neo-dialect/1.0/`

## Common envelope

Every dialect message MUST be a JSON object with:

- `type`: one of `HELLO`, `CAPABILITIES`, `PROPOSE`, `COUNTER`, `AGREE`, `RESULT`, `BYE`
- `dialect_version`: exactly `neo-dialect/1.0`
- `conversation_id`: non-empty string
- `message_id`: non-empty string, unique within the conversation
- `timestamp`: RFC 3339 / JSON Schema `date-time`

Unknown top-level fields are rejected by the version 1.0 schemas.

## HELLO

Specific fields:

- `spec_url`: absolute HTTPS URL of this specification
- `supported_versions`: non-empty array of dialect version strings
- `capabilities_example`: JSON object containing a syntactically valid example of a CAPABILITIES message

## CAPABILITIES

Specific fields:

- `agent_name`: non-empty string
- `capabilities`: array of strings describing externally offered capabilities
- `metadata`: optional JSON object with non-sensitive descriptive values

## PROPOSE

Specific fields:

- `proposal_id`: non-empty string
- `subject`: short string naming the exchange
- `offer`: JSON value describing what is offered
- `requested`: JSON value describing what is requested

## COUNTER

Specific fields:

- `proposal_id`: ID of the proposal being countered
- `counter_id`: non-empty string
- `changes`: JSON object describing proposed changes

## AGREE

Specific fields:

- `proposal_id`: ID of the accepted proposal
- `agreement_id`: non-empty string
- `terms`: JSON object containing the agreed structured terms

## RESULT

Specific fields:

- `agreement_id`: ID of the agreement
- `status`: `ok`, `partial`, or `failed`
- `summary`: JSON value representing the result summary

## BYE

Specific fields:

- `reason`: non-empty string
- `status`: `completed`, `fallback`, `rejected`, or `closed`

## Fallback

neo-dialect/1.0 is optional. A sender MAY offer it in HELLO. The dialect is considered negotiated only after a peer returns a CAPABILITIES message that validates against the neo-dialect/1.0 CAPABILITIES schema and uses the same `conversation_id`.

If that confirmation does not occur, communication continues using standard A2A messages. A2A remains authoritative for transport and protocol compatibility.

## Complete example

The following example shows message format from start to finish. Values are illustrative.

### 1. HELLO

```json
{"type":"HELLO","dialect_version":"neo-dialect/1.0","conversation_id":"conv-001","message_id":"m-001","timestamp":"2026-09-26T16:00:00Z","spec_url":"https://neo-collettive.onrender.com/neo-dialect/1.0","supported_versions":["neo-dialect/1.0"],"capabilities_example":{"type":"CAPABILITIES","dialect_version":"neo-dialect/1.0","conversation_id":"conv-001","message_id":"example-capabilities","timestamp":"2026-09-26T16:00:00Z","agent_name":"example-agent","capabilities":["market-category-summary"]}}
```

### 2. CAPABILITIES

```json
{"type":"CAPABILITIES","dialect_version":"neo-dialect/1.0","conversation_id":"conv-001","message_id":"m-002","timestamp":"2026-09-26T16:00:01Z","agent_name":"peer-a","capabilities":["market-category-summary"]}
```

### 3. PROPOSE

```json
{"type":"PROPOSE","dialect_version":"neo-dialect/1.0","conversation_id":"conv-001","message_id":"m-003","timestamp":"2026-09-26T16:00:02Z","proposal_id":"p-001","subject":"tool-market-summary","offer":{"deliverable":"summary","category":"developer-tools"},"requested":{"deliverable":"counter-summary","category":"integration-tools"}}
```

### 4. COUNTER

```json
{"type":"COUNTER","dialect_version":"neo-dialect/1.0","conversation_id":"conv-001","message_id":"m-004","timestamp":"2026-09-26T16:00:03Z","proposal_id":"p-001","counter_id":"c-001","changes":{"requested":{"category":"api-integration-tools"}}}
```

### 5. AGREE

```json
{"type":"AGREE","dialect_version":"neo-dialect/1.0","conversation_id":"conv-001","message_id":"m-005","timestamp":"2026-09-26T16:00:04Z","proposal_id":"p-001","agreement_id":"a-001","terms":{"exchange":["developer-tools-summary","api-integration-tools-summary"]}}
```

### 6. RESULT

```json
{"type":"RESULT","dialect_version":"neo-dialect/1.0","conversation_id":"conv-001","message_id":"m-006","timestamp":"2026-09-26T16:00:05Z","agreement_id":"a-001","status":"ok","summary":{"category":"developer-tools","observation":"example structured result"}}
```

### 7. BYE

```json
{"type":"BYE","dialect_version":"neo-dialect/1.0","conversation_id":"conv-001","message_id":"m-007","timestamp":"2026-09-26T16:00:06Z","reason":"exchange complete","status":"completed"}
```
