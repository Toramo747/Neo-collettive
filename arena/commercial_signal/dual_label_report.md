# Dual-label report — real commercial-signal sample

## Run
- GitHub Actions run ID: `36635413830`
- Head used by the run: `6dda147e3ee647f37fd491e9ba86d7b18bd005ec`
- Started: 2026-09-29T21:45:50Z
- Completed: 2026-09-29T21:52:48Z
- Workflow wall time: 418 s (6m 58s)
- Dual-label inference time: 366.69 s
- Artifact: `arena-dual-label-results`, ID `11065135266`, retention 30 days
- Artifact SHA-256: `1b2ee823ee9d9cbc4642cd5bd3a9ed241c44e172343e348552fe68e6250caf7a`

## Models
- `qwen2.5:3b-instruct` — Qwen family.
- `llama3.2:3b` — Meta Llama family.

The second model was selected because it is a distinct model family from Qwen while remaining close in size and suitable for instruction-following classification on a GitHub-hosted CPU runner. Both were run locally through Ollama; the classifier called only `127.0.0.1:11434`. Temperature was 0 and the fixed seed was 424242.

## Agreement
- Total blind cases: 24
- Raw agreement: 13/24 = **54.17%**
- Usable non-UNCERTAIN agreement: 12/24 = **50.00%**
- Cohen's kappa: **0.3592**
- Usable concordant labels:
  - REAL_DEMAND: 4
  - VENDOR_OR_SELLER: 3
  - NOISE: 5

One raw agreement was `UNCERTAIN/UNCERTAIN` (`real-024`), so it was excluded from `train_real.jsonl`.

## Excluded cases
12 cases were excluded because of disagreement or at least one UNCERTAIN:
`real-019`, `real-014`, `real-006`, `real-001`, `real-008`, `real-013`, `real-009`, `real-024`, `real-015`, `real-010`, `real-017`, `real-012`.

Full per-model labels and short reasons are in `label_disagreements.md`.

## Comparison with prior proposed labels
The prior labels were used only after dual labeling and did not influence either model.

Among the 12 usable concordant cases, one label differs from `label_review_real.md` / the previous proposed labels:
- `real-005`: previous **REAL_DEMAND** -> dual-model **VENDOR_OR_SELLER**.

The dual-model label is retained in `train_real.jsonl`, as required.

## Baseline on concordant cases only
Baseline: existing Arena `production-gate-shaped baseline` proposal, evaluated only on the 12 concordant cases.

- Dataset size: 12
- REAL_DEMAND precision: **0.0000**
- REAL_DEMAND recall: **0.0000**
- Predicted demand: 1
- Vendor false positives: **1/3**
- Vendor false-positive rate: **0.3333**
- Baseline disqualified by its existing vendor-FP threshold: **yes**

This is an Arena proxy evaluation only. It does not change or reproduce the production gate.

## Adequacy decision
**Threshold not met.** Raw model agreement is **54.17%**, below the required 60% floor. The usable set is exactly 12 cases, so it does not violate the separate "fewer than 12" condition, but the failed agreement condition is sufficient to mark this setup inadequate.

Interpretation: the current rubric/model pair should not be treated as reliable replacement ground truth yet. A follow-up decision is required on whether to refine ambiguous rubric boundaries, change one or both local models, or both. No production adoption is implied.

## Invariants
No production gate, `qualified_hits`, Registry FINAL, or `requirements.txt` change is part of this work. No merge was performed.
