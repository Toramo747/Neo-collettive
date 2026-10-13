# neo-dialect/1.0 failure analysis

Status: Arena evidence only. The official neo-dialect/1.0 specification is unchanged.

## Evidence base

Previous evidence available before this study:
- deterministic Arena sessions: **1**, complete through RESULT/BYE: **1**
- prior local 0.5B messages inspected: **8**
- prior invalid local 0.5B messages: **3**
- prior local 0.5B glossary errors: **2**
- real external LLM peer transcripts: **0**
- SETI neo-dialect probes attempted in the latest snapshot: **0**

New zero-weight study:
- model: **qwen2.5:3b-instruct-q4_K_M**
- Ollama structured-output mode: **format = JSON Schema**
- glossary included in every model prompt
- scenarios: collaborativo, scettico, confuso, ostile
- repetitions: 3 each
- sessions: **12**
- sessions complete through BYE: **12**
- model attempts: **57**
- valid model messages: **52**
- invalid model messages: **5**
- deterministic fallbacks used: **5**
- glossary errors: **0**

| Scenario | Sessions | Complete to BYE | Invalid model messages | Rule fallbacks | Dialect observations |
|---|---:|---:|---:|---:|---:|
| collaborativo | 3 | 3 | 1 | 1 | 0 |
| scettico | 3 | 3 | 1 | 1 | 0 |
| confuso | 3 | 3 | 1 | 1 | 3 |
| ostile | 3 | 3 | 2 | 2 | 0 |

## A. Dialect problems

A dialect problem means the intended communicative act cannot be represented cleanly by the existing 1.0 message set or requires a recurring semantic overload. Model syntax failures do **not** count here.

- **clarification_overloaded_into_counter**: 3 observations.

## B. Model problems

A model problem means the model failed to produce valid structured output, misunderstood the glossary, hallucinated semantics, or otherwise failed despite an adequate 1.0 schema.

- **conversation_id_mismatch**: 3 occurrences.
- **not_json**: 2 occurrences.

Historical 0.5B evidence remains classified as model-level: truncated/non-JSON output and MCP glossary confusion are generation/semantic failures, not evidence that the 1.0 wire format is missing a field.

## Security/hostile behavior

All model text is treated as untrusted. Each model-generated message is checked by the deterministic 1.0 validator and `neo_dialect_security`. Invalid or injection-like output is recorded and replaced only inside the isolated Arena with a deterministic valid fallback so the measurement session can continue to BYE.

No external agent is contacted, score weight is 0.0, production influence is NONE, and no automatic promotion is allowed.

## Interpretation

The study found recurring dialect-level observations. They are evidence candidates only; they do not change neo-dialect/1.0 and do not automatically justify an RFC.

Only observations in section A may be considered as input to a future RFC. Section B must be addressed at the model/prompt/structured-output layer instead.

Raw study data: `data/arena/neo-dialect-failure-study.json`.
