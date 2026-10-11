# Maestro v2: sentence embeddings (preregistered)

Authorized by Andrea on 2026-10-11 ("3 procedere"). This document was written before any v2 result.

**Question.** Does a sentence-embedding teacher recognise buyer demand ("someone needs a tool") better than teacher v1 (TF-IDF plus logistic regression)?

**Arms.** Same data, same masking (`maestro_teacher.mask`), same class balancing, in-domain items weighted ×5.
- **V1:** teacher v1's recipe, refit inside each split.
- **V2 (primary):** `BAAI/bge-small-en-v1.5` sentence embeddings (normalised) plus logistic regression with balanced classes and C=2.
- **V2H (secondary, reported, cannot be adopted):** V1 TF-IDF features and V2 embeddings concatenated.

**Data.** All of it is in the private archive; `hidden.jsonl` is never opened.
- The web dataset of phase 3, as used for v1, with its time split: the last 365 days are the test set.
- 668 in-domain NEO observations labelled by Claude.
- 100 calibration observations labelled by Claude (9 positive), never used for training.

**Measures** (AUC unless stated; the positive class is `buyer_tool_search` or demand `y=1`):
1. **Web time-split test.** Train on web items before the split plus all in-domain items; test on web items after the split.
2. **In-domain 5-fold CV.** Train on all web items plus 4/5 of the in-domain items; test on the held-out fifth. Stratified, seed 20261015.
3. **Calibration.** Train on all web items plus all in-domain items; test on the 100 calibration items.

**Adoption rule** (V2 only):
- AUC(V2) ≥ AUC(V1) + 0.02 on measure 1, **and**
- AUC(V2) ≥ AUC(V1) + 0.02 on measure 2, **and**
- AUC(V2) ≥ AUC(V1) − 0.03 on measure 3. With 9 positives, measure 3 can only veto a clear loss; it cannot prove a gain.

If all three hold, teacher v2 replaces v1 as the **shadow** teacher and in the teacher-fitness arena lineage, after a separate PR. Otherwise v1 stays. There is one attempt: no model or threshold changes after seeing the result.

**Cost.** Zero: GitHub-hosted CPU runner and an open-weights model. Logs show aggregate metrics only.
