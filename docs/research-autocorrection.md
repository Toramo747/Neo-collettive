# OXIBAY: self-correction feedback loop (shadow-only)

This adds four **experimental parameters** to a self-correction layer without changing the nine existing production/Arena search genes or classification rules.

1. `rejection_feedback` selects which documented rejection cause to target: no buyer voice, irrelevant results, unknown commercial family, or no demand tags.
2. `exploration_rate` (0.1–0.5) limits a deterministic choice of alternative query frames/term order in the bounded shadow gamete generator.
3. `novelty_penalty` (0–0.4) penalizes proposed strategies that increase duplicate-hit ratios versus a matched baseline; it never rewards search volume alone.
4. `temporal_robustness` (0–0.5) discounts unstable gains across evaluation windows without weakening the strict gate.

### Recorded historical failure, not evidence of progress

The training fixture is an exact anonymous aggregate transcription from GitHub Actions 37892131295 artifact 11599155139. All three held-out historical windows, May–July 2026, had **identical valid discussion-thread counts for baseline and evolved**. The observed evolved rejection totals are 17 no-buyer-voice, 16 irrelevant, 13 unknown-family and 5 no-demand-tags. The engine uses only these totals to prioritize **which hypotheses to try**, not to fit a tested model or claim a discovered gain.

The shadow generator emits 8 unique, bounded variants using *actual legacy search-gene values* accepted by `clamp_genome`. `build_queries` confirms a 16-query budget for every candidate. The parameter changes affect only isolated draft variants: **no main changes, no in-memory arena mutation, no production scoring, no gate threshold changes, no private datasets, no paid models/APIs or external calls**.

### Tests, separation and promotion

The CI tests aggregate integrity, deterministic unique gamete generation, source/query budgets, synthetic positive and negative outcomes, rejection of May–July leakage, no promotion and source-code isolation. The reported candidate scores are `null`; all variants are **unvalidated**, even when synthetic tests demonstrate that the evaluation code can recognize a fictitious improvement.

The `evaluate_external` adapter may process only new aggregate windows, and applies lower-bound sample size, complete provider success, stable precision, duplicate penalty and temporal robustness. Its strongest verdict is `SHADOW_REVIEW_CANDIDATE_NOT_VALIDATED`, **never automatic promotion**. At least three genuinely independent, preregistered external validations plus blind human review remain necessary before proposing production changes.

Run without network:

    python experiments/research-autocorrection/engine.py
    python -m unittest -v test_research_autocorrection

Next experiment (a separate, preregistered draft PR): compare selected gametes against an equal-budget baseline on unseen source/time/topic slices and independent human-reviewed buyer-demand cases. Keep all negative results, do not use these training months as independent validation.
