# neo-dialect A/B decision

Status: **BLOCKED / NOT_MEANINGFUL_YET**.

Reviewed: 2026-09-27.

## Requested comparison

Point 5 originally requested an Arena A/B comparison of:

- neo-dialect/1.0
- neo-dialect/1.1-draft

using the same scenarios:
- collaborativo
- scettico
- confuso
- ostile

and the same local-model/rules boundary.

The intended metrics were:
- valid messages;
- loops;
- fallback count;
- turns to agreement;
- sessions reaching RESULT;
- injection blocks.

## Why the A/B test is blocked

There is currently no `neo-dialect/1.1-draft`.

Point 3 admitted **0 RFCs** and point 4 concluded **NO_DRAFT_NEEDED**. Therefore there is no semantic delta to compare against 1.0.

Running two copies of 1.0 under different version labels would not be an A/B protocol experiment. It would measure stochastic model/runtime variation and could falsely attribute noise to a protocol change.

## Current baseline retained

The existing point 1-bis study remains the valid 1.0 baseline:

- 12/12 sessions completed through BYE;
- 57 model attempts;
- 52 structurally valid model messages;
- 5 invalid model messages;
- 5 deterministic fallbacks;
- 0 automatic glossary errors in the recorded summary;
- recurring dialect observation: `clarification_overloaded_into_counter` in 3/3 confused sessions;
- A2A overlap review later screened that observation out as an RFC candidate.

The raw baseline remains in `data/arena/neo-dialect-failure-study.json`.

## A/B activation gate

The A/B study may run only after all of these are true:

1. at least one numbered RFC is admitted;
2. Andrea explicitly approves that RFC for Arena experimentation;
3. a real `neo-dialect/1.1-draft` exists with a schema/runtime behavior different from 1.0;
4. the delta has a falsifiable hypothesis;
5. the comparison uses the same scenario corpus, model, glossary, structured-output mode and deterministic guard for both arms;
6. both arms remain zero-cost, Arena-only, score weight 0.0, no external contact and no production influence.

## Future A/B measurement contract

When the activation gate is satisfied, the study should compare both arms with the same deterministic scenario seeds and report at minimum:

| Metric | Meaning |
|---|---|
| valid_message_rate | accepted structured messages / model attempts |
| fallback_rate | deterministic fallbacks / model attempts |
| loop_count | repeated negotiation cycles beyond the expected flow |
| turns_to_agreement | dialect turns required before AGREE, when agreement occurs |
| result_completion_rate | sessions reaching RESULT |
| bye_completion_rate | sessions reaching BYE |
| injection_blocks | rule-guard rejections for instruction-like content |
| protocol_specific_failures | failures attributable to the tested semantic delta |

A result must not count as improvement merely because the model produced different wording. The measured change must be attributable to the RFC-defined semantic delta.

## Critic position

The Critic should reject an A/B conclusion if:
- the two protocol arms are semantically identical;
- the test changes the model, prompt, scenario mix or guard between arms;
- sample failures are model-generation errors unrelated to the RFC;
- an apparent benefit duplicates an A2A primitive;
- security becomes weaker even if completion metrics improve.

## Current decision

**Do not run the A/B experiment now.**

There is no experimental protocol arm to test.

Point 5 is complete as a blocked decision and becomes runnable automatically only after a future approved RFC produces a real Arena-only draft.
