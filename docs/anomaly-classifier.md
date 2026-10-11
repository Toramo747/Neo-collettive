# Anomaly classifier (replaces cue-word counting in the Anomaly Arena)

Authorized by Andrea on 2026-10-11 ("Procedi").

## Why

Counting "tension" and "resolution" words in abstracts made the proton-radius control (an anomaly widely regarded as resolved) score above every real anomaly (0.18 against 0.05 for evolving dark energy), so the arena was declared uncalibrated.

## Data

- **Harvest** (`tools/anomaly_harvest.py`): up to 150 recent arXiv abstracts per topic. The topics are the arena's 8 plus 8 extra, so there are enough "resolved" cases: OPERA superluminal neutrinos, the 750 GeV diphoton excess, BICEP2 B-modes, muon g-2, the reactor antineutrino anomaly, the gallium anomaly, ATOMKI X17 and the cosmic dipole. In total 1,674 abstracts. They are stored only in the private archive.
- **Labels**: 565 abstracts (36 per topic, 25 for X17), labelled by Claude with three classes:
  - `supports_tension`: the paper treats the anomaly as real or persisting, including new-physics explanations premised on it.
  - `resolves`: the paper finds agreement, a null result, or explains the anomaly with standard physics or systematics.
  - `neutral`: neither (methods, instruments, or refuting only one proposed explanation).
- Distribution: 240 supports, 76 resolves, 249 neutral. The labels are stored only in the private archive.

## Preregistered evaluation (written before training)

- **Model:** TF-IDF on word 1–2-grams plus a logistic regression with balanced class weights. Topic names and query phrases are masked, so the model cannot learn which topic a paper is about.
- **Baseline:** the arena's current cue-word rule, mapped onto the same three classes:
  - a tension cue without a resolution cue gives `supports_tension`;
  - any resolution cue gives `resolves`;
  - otherwise `neutral`.
- **Evaluation:** leave-one-topic-out cross-validation, where each topic is predicted by a model that never saw it. This is the honest test, because the arena must judge anomalies the model was not trained on.
- **Adoption rule.** The classifier replaces cue words in the arena only if both conditions hold:
  1. Its leave-topic-out macro-F1 is at least the baseline's plus 0.10.
  2. **Control check:** with leave-topic-out predictions, the predicted persistence (supports minus resolves, divided by papers) of `proton_radius_control` is lower than that of both `hubble_tension` and `evolving_dark_energy`.

  If either condition fails, the arena keeps reporting itself as uncalibrated.
- Also reported, but not deciding: the Spearman correlation across the 16 topics between predicted and labelled persistence, and stratified 5-fold macro-F1.

Labels by a single annotator (Claude) are a limitation. A 30-label review by Andrea would measure agreement.

## Result of the first evaluation (2026-10-11, 565 labels)

| | Cue words (baseline) | Classifier |
|---|---|---|
| Macro-F1, leave-topic-out | 0.432 | 0.456 |
| Macro-F1, 5-fold (topics seen) | — | 0.578 |
| Spearman, topic persistence vs labels | −0.32 | +0.22 |
| Control check (proton below Hubble and evolving DE) | fails | passes (0.11 vs 0.36 and 0.58) |

**Decision under the preregistered rule: not adopted.** The classifier passes the control check and ranks topics better than cue words, but its macro-F1 on unseen topics is only 0.024 above the baseline, while the rule requires 0.10. The arena keeps cue-word scoring and stays flagged as uncalibrated.

Weak point: the `resolves` class has only 76 examples. Possible next steps, none of them started:
1. Label more `resolves` cases.
2. Have Andrea review a sample of labels.
3. Run the classifier in shadow next to the cue words, without deciding anything.

## Amendment 1 (2026-10-11, before any new evaluation): more `resolves` data

Authorized by Andrea ("Procedere 1"). About 300 more abstracts are labelled with the same guideline:
- About 140 are drawn at random from periods after each anomaly was widely considered resolved or faded: OPERA from 2012-02, BICEP2 from 2015, the 750 GeV excess from 2016-08, reactor antineutrinos from 2017, the proton radius from 2019, X17 from 2023 and muon g-2 from 2025-06. At most 40 come from any one topic.
- About 160 are drawn at random from the remaining pool.

The selection uses dates and topics only, never cue words, so it does not favour the cue-word baseline. The adoption rule, the model and the evaluation are unchanged. This is the second and last attempt under this rule: if it fails again, the classifier stays out of the arena.
