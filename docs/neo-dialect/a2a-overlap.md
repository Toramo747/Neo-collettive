# A2A overlap analysis for neo-dialect/1.0

Status: analysis only. **neo-dialect/1.0 is unchanged.** This document decides which observed needs belong to A2A and therefore must not be reimplemented as neo-dialect message types.

Reviewed: 2026-09-27.

Primary upstream sources:
- A2A current specification (main): https://github.com/a2aproject/A2A/blob/main/docs/specification.md
- A2A protocol schema (main): https://github.com/a2aproject/A2A/blob/main/specification/a2a.proto

## Rule

neo-dialect is carried above A2A. An extension is eligible for a neo-dialect RFC only when it adds **dialogue semantics that A2A does not already provide**.

Transport, task lifecycle, progress, cancellation, artifacts, protocol errors, capability discovery, protocol-version handling, clarification transport, authentication and asynchronous delivery remain A2A responsibilities.

## A2A already covers

### Task lifecycle and state

A2A defines a stateful `Task` lifecycle including:
- `TASK_STATE_SUBMITTED`
- `TASK_STATE_WORKING`
- `TASK_STATE_COMPLETED`
- `TASK_STATE_FAILED`
- `TASK_STATE_CANCELED`
- `TASK_STATE_INPUT_REQUIRED`
- `TASK_STATE_REJECTED`
- `TASK_STATE_AUTH_REQUIRED`

Therefore neo-dialect must not add independent task-state or task-progress state machines.

### Clarification and additional input

A2A explicitly supports clarification in two forms:

1. An agent may return a normal A2A `Message` to request clarification before creating a Task.
2. During a Task, the agent may transition to `TASK_STATE_INPUT_REQUIRED`, attach a status `Message`, and resume when the client sends another Message with the same task/context identifiers.

This directly covers the only recurring dialect observation from the 1-bis Arena study: `clarification_overloaded_into_counter` in 3/3 confused sessions.

**Decision for point 2:** this observation is **not** evidence for a neo-dialect `CLARIFY` message. Clarification belongs to A2A. The dialect may carry structured proposal content inside an A2A Message, but it should not duplicate A2A's input-required lifecycle.

### Progress

A2A provides:
- `TASK_STATE_WORKING`
- `TaskStatusUpdateEvent`
- streaming task updates
- polling via Get Task
- subscriptions to active tasks
- push notifications when supported

Therefore a neo-dialect `PROGRESS` message would duplicate A2A.

### Cancellation

A2A defines Cancel Task and `TASK_STATE_CANCELED`, including `TaskNotCancelableError`.

Therefore a neo-dialect `CANCEL` message would duplicate A2A.

### Results and evidence attachments

A2A distinguishes Messages from task outputs. Results should be represented as `Artifact` objects composed of `Part` values. Parts may contain text, structured data, raw file bytes or URLs.

Therefore:
- durable outputs/evidence should use A2A Artifacts/Parts;
- neo-dialect should not invent a separate attachment transport;
- neo-dialect `RESULT` should be treated as dialogue-level agreement/result metadata, not as a replacement for A2A task output or artifact delivery.

A proposed `EVIDENCE_ATTACHMENT` message would therefore be redundant unless future evidence demonstrates a negotiation-specific semantic need that cannot be represented by an A2A Artifact or structured Part.

### Errors

A2A already defines transport/operation error semantics, including:
- `TaskNotFoundError`
- `TaskNotCancelableError`
- `PushNotificationNotSupportedError`
- `UnsupportedOperationError`
- `ContentTypeNotSupportedError`
- `InvalidAgentResponseError`
- `ExtendedAgentCardNotConfiguredError`
- `ExtensionSupportRequiredError`
- `VersionNotSupportedError`

It also defines standard authentication, validation, resource and system error categories.

Therefore a generic neo-dialect `ERROR` message would duplicate A2A. A future dialect RFC could only define a **negotiation-domain rejection reason** if repeated evidence shows that PROPOSE/COUNTER/BYE cannot express it; it must not replace A2A errors.

### Capabilities and discovery

A2A Agent Cards declare:
- agent identity and skills;
- optional capabilities such as streaming and push notifications;
- supported protocol extensions;
- supported interfaces/protocol versions;
- input/output modes.

A2A extensions are identified by URI and can be advertised in the Agent Card. Clients opt into extensions through A2A binding mechanisms.

Therefore neo-dialect `HELLO` and `CAPABILITIES` overlap with A2A discovery/capability mechanisms. For 1.0 they remain part of the existing dialect contract, but **future versions should not expand them into a parallel discovery protocol**.

### Protocol version negotiation

A2A already carries protocol-version intent using the `A2A-Version` service parameter and defines `VersionNotSupportedError`. A2A also has extension negotiation through `A2A-Extensions`.

neo-dialect may still need its own **dialect-version selection** because the dialect is an A2A extension/application convention, but it should be negotiated as extension metadata/content, not as a replacement for A2A transport-version negotiation.

## What neo-dialect actually adds

The current A2A specification does not standardize the proposal/negotiation semantics used by neo-dialect:

- `PROPOSE`: a structured proposal identified by `proposal_id`;
- `COUNTER`: a structured modification tied to that proposal;
- `AGREE`: explicit structured acceptance with `agreement_id` and terms;
- the linkage from proposal -> counter -> agreement;
- bounded dialogue rules specific to this negotiation vocabulary.

These are the clearest neo-dialect-specific semantics. They sit **inside A2A Messages** and should rely on A2A for task state, context, transport, errors, artifacts and lifecycle.

`BYE` can provide dialogue-level closure/reason semantics, but it must not be interpreted as canceling or completing an A2A Task.

`RESULT` can summarize the negotiated outcome, but durable task outputs should remain A2A Artifacts.

## Overlap matrix

| Need / candidate | A2A primitive | neo-dialect action |
|---|---|---|
| clarification request | Message before Task; `TASK_STATE_INPUT_REQUIRED` + status Message | **Do not add CLARIFY** |
| task progress | WORKING + status updates / streaming / polling | **Do not add PROGRESS** |
| cancellation | Cancel Task + CANCELED | **Do not add CANCEL** |
| task/result evidence | Artifact + Part | **Do not add attachment transport** |
| generic errors | A2A errors | **Do not add generic ERROR** |
| authentication required | AUTH_REQUIRED + auth errors | **Do not duplicate** |
| capability discovery | Agent Card / AgentCapabilities / AgentSkill | **Do not expand parallel discovery** |
| A2A protocol version | `A2A-Version` + `VersionNotSupportedError` | **Do not duplicate** |
| extension negotiation | AgentExtension + `A2A-Extensions` | Reuse for dialect advertisement where possible |
| proposal semantics | none standardized by A2A | neo-dialect responsibility |
| counter-proposal semantics | none standardized by A2A | neo-dialect responsibility |
| explicit negotiated terms | none standardized by A2A | neo-dialect responsibility |

## Consequence for the 1-bis evidence

The recurring `clarification_overloaded_into_counter` observation is real at the neo-dialect message layer, but the required communication act is already provided by A2A.

Therefore it **must not become a neo-dialect RFC on the present evidence**.

The model-level failures remain outside protocol evolution:
- conversation-id mistakes;
- truncated/non-JSON generation;
- glossary drift/hallucinated alternate meanings.

## Point-2 conclusion

The current evidence does **not** justify any new neo-dialect message type.

For now, neo-dialect/1.0 should remain focused on proposal/counter/agreement semantics and delegate clarification, task lifecycle, progress, cancellation, artifacts and errors to A2A.

In the terms of the 1-bis decision rule: **neo-dialect 1.0 is sufficient for now** with respect to the observed failures. Any future RFC requires new recurring evidence for a dialogue-semantic gap that A2A does not already cover.
