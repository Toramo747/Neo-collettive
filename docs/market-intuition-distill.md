# Distilling the deep mind into the small mind (preregistered 2026-10-12)

Requested by Andrea: bring forward the Kaggle training of the small model. The
small arena mind (qwen2.5 3B) lumps unrelated needs and over-claims; the deep
mind (qwen2.5 14B on a free Kaggle T4) judges better but runs only every ~6 h.

## Data
1. **Harvest:** one bulk pass of the arena's own retrieval and need-sentence
   filter over seed, focus and learned terms (≈500 HN queries) → up to 2,200
   candidate sentences, one per person (people stored only as hashes).
2. **Teacher labels:** the 14B judges every candidate with the arena's exact
   judge prompt (batches of 6, 4 in parallel) → real_need, problem, would_pay.
3. **Split by person:** 20 % of people held out; never used for training.

## Training
LoRA on qwen2.5 3B (Unsloth, Kaggle T4), same batch prompt and JSON format the
arena uses at inference; exported to GGUF q4 for Ollama.

## Decision rule (fixed now, before any training)
On the held-out people, against the teacher's real_need labels:
1. tuned-3B F1 (real_need = true) ≥ base-3B F1 + 0.10, **and**
2. tuned-3B false-positive rate (says real, teacher says not) ≤ base-3B's, **and**
3. Andrea spot-checks 20 held-out sentences the tuned model marks as real:
   at least 15 must be real needs to him.
All three → the tuned model replaces the small mind. Otherwise the result is
recorded as negative and the base model stays. The ceiling is the teacher:
distillation cannot be better than the 14B, and inherits its biases.

## Result (2026-10-12/13): NOT adopted

Data: 1,198 sentences labeled by the 14B in 15 minutes of GPU (4 parallel
requests); 959 for training (640 batch examples), 239 held out by person.
Training: 20 minutes on a Kaggle T4, final average loss 1.33, GGUF q4_k_m 1.8 GB.

| held-out vs 14B teacher | base 3B | distilled 3B |
|---|---:|---:|
| F1 (real need) | 0.616 | 0.621 |
| precision | 0.527 | 0.621 |
| recall | 0.742 | 0.621 |
| false-positive rate | 0.254 | **0.145** |
| agreement | 0.745 | 0.791 |
| valid JSON | 97.1 % | 100 % |

Rule: F1 gain ≥ 0.10 **failed** (+0.005); false-positive rate not higher
passed. Machine verdict: not adopted; the base model stays. The student trades
recall for precision (43 % fewer false needs), which may matter for the arena,
but changing the rule after seeing the result is not allowed: any new attempt
needs a new preregistration.


## v2 — preregistered 2026-10-16 (Andrea), before any v2 data

Why a second attempt: v1 cut false needs by 43 % (FPR 0.254 → 0.145) but lost
recall (0.742 → 0.621) and missed the F1 rule. That hypothesis came from v1's
result, so v2 must test it on **people never seen before**.

Changes: fresh harvest (same pipeline); v1's 1,198 labeled sentences are reused
**for training only**; the v2 held-out set contains only people absent from all
v1 data. Same teacher (14B), student, prompt, training recipe.

Decision rule (fixed now): on the fresh held-out people, against the teacher,
1. student false-positive rate ≤ 0.6 × base-3B's (≥ 40 % fewer false needs), **and**
2. student recall ≥ base recall − 0.10 (keeps real needs), **and**
3. student F1 ≥ base F1 − 0.02 (overall not worse), **and**
4. Andrea spot-checks 20 held-out sentences the student marks real: ≥ 15 real.
All four → the student replaces the small mind. Otherwise negative, recorded,
and no v3 on the same idea without new evidence. Applying v2 to v1's numbers
would fail rule 2 (0.621 < 0.642).

### v2 result — 2026-10-16

Harvest 2,207 candidates; train 2,719 sentences (831 reused from v1); held-out
319 sentences from people absent from v1. Training: 47 min, loss 1.08.

| held-out (n=319) | base-3B | student |
|---|---|---|
| F1 | 0.528 | 0.580 |
| precision | 0.471 | 0.571 |
| recall | 0.600 | 0.589 |
| false-positive rate | 0.286 | **0.188** |
| agreement | 0.680 | 0.746 |
| valid JSON | 99.7 % | 98.4 % |

1. FPR ≤ 0.6 × base (≤ 0.171): **failed** (0.188, −34 % instead of −40 %).
2. recall ≥ base − 0.10 (≥ 0.500): passed.
3. F1 ≥ base − 0.02 (≥ 0.508): passed (+0.052).
4. Andrea spot-check: not run (machine rule already failed).

Machine verdict: **not adopted**; the base model stays. The student is better
on every metric except valid JSON, and the v1 direction (fewer false needs,
recall kept) is confirmed on new people, but the preregistered 40 % cut was not
reached. Per the rule: negative, recorded, no v3 on the same idea without new
evidence. Any change to the threshold is Andrea's decision, not a re-run.
