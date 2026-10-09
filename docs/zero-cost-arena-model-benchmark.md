# OXIBAY — Zero-cost local-model Arena benchmark

This is an **isolated, synthetic-only** comparison, not commercial evidence and not a production model promotion.

## Model candidates

Baseline: `qwen2.5:0.5b-instruct`. Challengers: `qwen3.5:4b-q4_K_M` and `qwen3.5:9b-q4_K_M` (exact Ollama tags must be checked before pulling; use only officially available downloadable tags). Models are downloaded only by an explicit human action.

The runner itself **never pulls a model** and makes requests only to `http://127.0.0.1:11434/api/{tags,generate}` when invoked with `--execute`. It has no API keys, billing integrations or remote endpoint configuration.

## Use

Install and run Ollama in an environment that is already free to you. Verify available model tags at https://ollama.com/library/qwen3.5 before pulling. If a tag differs, amend the allowlist in a reviewed PR, **do not silently substitute a different model**.

```bash
python -m unittest -v test_arena_free_model_benchmark
python arena_free_model_benchmark.py
ollama list
# Only after confirming sufficient free compute/storage and correct available model tags:
ollama pull qwen2.5:0.5b-instruct
ollama pull qwen3.5:4b-q4_K_M
ollama pull qwen3.5:9b-q4_K_M
python arena_free_model_benchmark.py --execute --out /tmp/oxibay-synthetic-model-results.json
```

If a model is unavailable/not installed or the time limit is exceeded, the result is `SKIPPED` or `INCOMPLETE`, never success. No model is ranked without all 12 cases completed.

## Public or free GPU notebook

The script may run in Kaggle/Colab **only if** their genuinely free GPU is currently allocated and the notebook session allows model downloads. The script does not open, allocate or bill for such a session. Do not supply payment details, enable paid credits or request paid inference endpoints. When free resources are exhausted, stop. Run the same command in notebook terminals with the repository files present and Ollama listening locally. A notebook cannot run the benchmark without downloading model weights, which is a separate, explicit user action.

## Measurement

12 openly synthetic decision cases cover commercial evidence hygiene, quality of external-agent proposals, query experimentation, unsupported LLM claims, warp physics feasibility and prompt-injection resistance. Equal prompt, fixed seed and temperature, strict JSON, source-ID hallucination checks, response latency and explicit abstention. **The cases are an initial engineering smoke benchmark, not an independent unseen holdout.** Accuracy is a strict exact decision match, not a claim about autonomous reasoning, truth or market utility.

No real external search, no customer documents, no secrets, no private control cases, no production state writes and no commercial gate changes. Scientific performance and economic utility require additional independent evidence before any manual model promotion.

The prior gamete pack is in draft PR #223; this is an independent experiment and does not imply merge or deployment.
