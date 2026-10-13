# neo-dialect RFC registry

Status: point 3 review complete. **No numbered RFC is currently eligible.**

The RFC directory is intentionally empty of `NNN-title.md` proposals because the evidence collected so far does not show a recurring neo-dialect-specific gap that survives the A2A overlap check.

## RFC admission rule

A numbered RFC may be created only when all of the following are true:

1. the problem is observed repeatedly in Arena or real peer transcripts;
2. the problem is classified as **DIALECT**, not **MODEL**;
3. A2A does not already provide the required primitive or lifecycle semantics;
4. the proposed change does not duplicate A2A transport, task state, progress, cancellation, artifacts, errors, capability discovery, authentication, or protocol-version handling;
5. the RFC includes:
   - observed problem and evidence counts;
   - proposed change;
   - JSON schema;
   - neo-dialect/1.0 compatibility impact;
   - security risks;
   - Critic objections;
6. the RFC remains Arena-only until Andrea explicitly approves a production specification change.

## Candidate screened in point 3

### clarification_overloaded_into_counter

Observed evidence:
- 3/3 confused Arena sessions used `COUNTER` to express a clarification request.

Initial interpretation:
- this looked like a possible missing dialogue primitive.

A2A overlap result:
- A2A already supports clarification through ordinary Messages before task creation;
- an active task can enter `TASK_STATE_INPUT_REQUIRED` and carry a status Message;
- the client can then send another Message in the same task/context to supply the missing input.

Decision:
- **NO RFC**
- reason: adding `CLARIFY` to neo-dialect would duplicate A2A semantics.

Critic objection:
- a dedicated dialect `CLARIFY` could make proposal negotiations more explicit.

Response:
- explicitness alone is insufficient evidence for a new protocol primitive when the lower protocol already carries the same communicative act. A future RFC would require repeated evidence that A2A clarification cannot preserve a necessary proposal/counter/agreement semantic.

## Model failures excluded from RFCs

The following observed failures are not eligible for RFCs:
- `conversation_id_mismatch`;
- truncated / non-JSON generation;
- glossary drift or hallucinated alternate meanings of MCP.

These are model-generation or prompt/validation issues. They do not demonstrate missing protocol expressiveness.

## Candidate examples screened out by A2A

These examples were considered only as possible directions and are **not RFCs**:

| Candidate | Current decision | Reason |
|---|---|---|
| structured generic error | rejected | A2A already defines protocol/operation errors |
| clarification request | rejected | A2A Message + INPUT_REQUIRED already cover it |
| cancellation | rejected | A2A Cancel Task + CANCELED |
| progress | rejected | A2A WORKING/status updates/streaming |
| evidence attachment | rejected | A2A Artifact + Part |

## Current conclusion

There are **0 eligible RFCs**.

On the evidence available at point 3, **neo-dialect 1.0 is sufficient for now**.

This is not a claim that 1.0 is complete forever. It means protocol evolution is evidence-gated: a future RFC starts only after a recurring dialect-level failure remains unexplained by A2A and cannot be solved at the model layer.
