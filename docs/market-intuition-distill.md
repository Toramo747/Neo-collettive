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
