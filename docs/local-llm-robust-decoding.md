# Robust decoding for local LLMs (option 1, no retraining)

Authorized by Andrea on 2026-10-11 ("Ok la 1").

**Problem.** In the local LLM comparison, qwen2.5 0.5b produced schema-valid JSON in about half of the messages. The invalid outputs were repetition loops cut off by `num_predict`, so the JSON object never closed.

**Change** (`local_llm_decoding.py`):
- `repeat_penalty` 1.18 over the last 256 tokens, plus `top_p` 0.9.
- `num_predict` 512 instead of 360.
- `maxLength` 400 on every unbounded string in the JSON schema, so the constrained grammar cannot emit an endless string.
- One retry at temperature 0 with a "JSON only, short strings" instruction.

**A/B.** `arena_local_llm_compare.py --decoding both` (the default) runs the same scenarios with baseline and robust decoding. `models` keeps the baseline results; `robust_models` and `decoding_ab` hold the comparison.

**Preregistered rule (per model).** Robust decoding is adopted if its schema-valid rate is at least 0.25 above the baseline and its average quality score is not lower. One run decides only for that run; adoption in other arenas needs the rule to hold on 2 of 3 runs.

**Scope.** The compare arena and the proposal call of the LLM-guided search use the robust options. `arena_local_llm_probe.py` is unchanged because it is in the Render deploy path filter. No production influence, no cost, gate unchanged.
