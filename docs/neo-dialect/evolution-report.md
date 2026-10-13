# neo-dialect evolution report

Status: **FINAL — Arena evidence only**  
Reviewed: 2026-09-27.

## Executive result

The evolution study does **not** recommend a neo-dialect/1.1 draft or any RFC at this time.

**Recommended RFC: none.**

Current conclusion: **neo-dialect 1.0 is sufficient for now**.

The official 1.0 specification remains unchanged.

## Failure evidence

The zero-cost Arena study ran 12 complete sessions:
- 4 scenarios: collaborativo, scettico, confuso, ostile;
- 3 repetitions each;
- 12/12 reached BYE;
- 57 model attempts;
- 52 structurally valid model messages;
- 5 invalid model messages;
- 5 deterministic fallbacks.

Observed model-level failures:
- conversation_id_mismatch: 3;
- truncated/non-JSON output: 2;
- one additional semantic glossary drift found by post-run transcript audit.

Observed dialect-level behavior:
- clarification_overloaded_into_counter: 3/3 confused sessions.

## A2A overlap result

The recurring clarification observation does not justify a neo-dialect message extension.

A2A already provides:
- ordinary Messages for clarification before task creation;
- TASK_STATE_INPUT_REQUIRED plus a status Message during an active task.

Other possible extensions were also screened out because A2A already covers them:
- progress;
- cancellation;
- generic protocol/operation errors;
- result/evidence artifacts;
- capability discovery and transport/protocol version handling.

## RFC result

Numbered RFCs admitted: **0**.

The clarification candidate remains **REJECTED_BEFORE_RFC** because it duplicates A2A semantics.

Model-generation failures are excluded from RFC admission.

## A/B result

Status: **BLOCKED / NOT_MEANINGFUL_YET**.

No neo-dialect/1.1-draft exists and there is no accepted semantic delta. Running 1.0 against a relabeled copy of itself would measure model/runtime noise rather than protocol quality.

The A/B measurement contract is preserved for a future evidence-backed draft.

## Critic objections

The Critic can veto a future RFC even when headline metrics improve.

Current objections:
- do not duplicate A2A;
- do not solve MODEL problems by changing the wire protocol;
- do not infer protocol benefit from unequal models/prompts/guards/scenarios;
- do not weaken isolation or injection resistance;
- do not promote a neutral change merely because it does not regress.

## Recommendation

**No RFC is recommended for approval.**

The next protocol experiment should start only after a recurring DIALECT failure is observed that:
1. cannot be solved by the model/prompt/validator layer;
2. is not already represented by A2A;
3. produces a falsifiable RFC hypothesis.

## Constraints preserved

- cost: 0 EUR;
- Arena isolation;
- score weight 0.0;
- no external agent contact from the Arena;
- no automatic promotion;
- no production influence from Arena evidence;
- gate commerciale, SETI and Registry constraints unchanged;
- Pathwren target remains 100/100;
- official neo-dialect/1.0 unchanged;
- any future specification change requires Andrea's explicit approval.

## Public Arena evidence

The 12 study transcripts are exposed read-only under `/arena/neo-dialect`.

Machine-readable summary:
`data/arena/neo-dialect-evolution-report.json`

Raw study:
`data/arena/neo-dialect-failure-study.json`
