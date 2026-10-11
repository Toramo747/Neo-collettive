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

## Result after amendment 1 (2026-10-11, 866 labels, same rule)

| | Cue words (baseline) | Classifier |
|---|---|---|
| Macro-F1, leave-topic-out | 0.413 | **0.528** (+0.115) |
| Macro-F1, 5-fold (topics seen) | — | 0.601 |
| Spearman, topic persistence vs labels | −0.29 | +0.46 |
| Control check | fails | **passes** (proton 0.05; Hubble 0.45; evolving DE 0.50) |

**Decision under the preregistered rule: adopted.** Both conditions hold. The arena now uses the stance classifier (`scoring_v` 3). Cue-word persistence is still reported as `persistence_cue`, and baselines from the two methods are never compared.

Caveats, stated openly:
- The margin over the 0.10 threshold is small (+0.015).
- The extra data were chosen after the first, failed evaluation. The selection used dates and topics only and was declared before the evaluation, but it is still a second look.
- There is a single annotator (Claude).
- Known miscalibrations on unseen topics: Casimir is predicted at 0.43 while its labels give 0.00 (it is almost all neutral theory), and muon g-2 is predicted at 0.38 against 0.04. Persistence for topics dominated by theory papers is therefore overestimated.

Preview on the current 180-day window: S8 +0.54, Hubble +0.43, evolving dark energy +0.34, proton-radius control −0.27.

## Independent label audit (2026-10-11, requested by Andrea)

Two other models relabelled 80 of Claude's abstracts blind: they saw the guideline and the text, but not Claude's labels. The models were Claude Sonnet and Claude Haiku; a third model was unavailable for lack of credits. The sample is stratified by Claude's label (30 supports, 25 resolves, 25 neutral), so these figures describe agreement per class rather than the population.

| Pair | Agreement | Cohen's κ |
|---|---|---|
| Claude vs Sonnet | 84% | 0.75 |
| Claude vs Haiku | 83% | 0.74 |
| Sonnet vs Haiku | 89% | 0.83 |

- Claude matches the majority of the three on 71 of 80 items.
- On the 9 items where both reviewers disagree with Claude, most of the errors are Claude's:
  - two experiment proposals were labelled `supports_tension`, against the guideline's own rule that they are neutral;
  - mixed abstracts were labelled `resolves` too readily.

  Claude's weak class is `resolves`, which is over-assigned in borderline cases.
- **Sensitivity check:** with those 9 labels replaced by the reviewers' majority, leave-topic-out macro-F1 is 0.522 against a baseline of 0.405. The margin of +0.117 is unchanged, so the adoption decision does not depend on the contested labels. The audit files are in the private archive (`anomaly/audit/`).
