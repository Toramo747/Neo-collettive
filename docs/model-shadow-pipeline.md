# Model Shadow Pipeline

The model pipeline is observational only. Commercial and challenge gates remain authoritative and unchanged.

## Phase 0 — private label archive

The public repository contains only the schema contract in `docs/private-label-archive-contract.json`.
Raw cases must live in a separate private GitHub repository configured with:

- repository variable `MODEL_LABEL_REPO`
- repository secret `MODEL_LABEL_REPO_TOKEN`

Required private files are `train.jsonl`, `public.jsonl`, and `hidden.jsonl`.
Case IDs must be disjoint across all three files. Hidden labels accept only `human` or `outcome` origins.

## Phase 1 — independent judges

`model_shadow_registry.json` pins all model repositories, revisions, licenses and thresholds.
The batch pipeline runs four independent judges:

1. current lexical rules;
2. multilingual zero-shot NLI;
3. local quantized LLM;
4. structural signals.

Automatic training labels require at least three high-confidence agreeing judges.
Outcome labels override automatic consensus.

## Phase 2 — Render student

Actions trains a hashed character n-gram logistic classifier. Render loads only the compact NumPy artifact from
`runtime/model-shadow/student.json`. It runs beside the lexical classifier in shadow and records aggregate
agreement/disagreement counters only. The artifact is limited to 5 MB.

Publishing a newly trained student requires an explicit manual workflow dispatch with `publish_student=true`.
This does not promote the student to decision authority.

## Phase 3 — semantic challenge clustering

Embeddings and cosine clustering run only on Actions. Render accepts only an authenticated HMAC map containing
16-hex evidence IDs, 16-hex cluster IDs, review-state codes and bounded requester weights.

The semantic shadow treats `not_planned` as unresolved and feasibility `unknown` as `REVIEW_REQUIRED`.
These semantics do not change the current challenge gate while the system remains shadow-only.

## Phase 4 — evaluation and promotion

Every trained version compares lexical rules and the student on public and hidden sets. Hidden output is aggregate
only. Promotion eligibility requires student accuracy to be no worse than lexical accuracy on both sets.

Promotion is never automatic. `manual_only` is enforced in the registry, runtime state and deploy tests.
Rollback is a one-step removal/disable of the student artifact, returning to lexical authority.

## Phase 5 — drift surveillance

The weekly scheduled workflow creates `weekly_review.html` in the private label repository with five random cases
for Andrea to review. It also stores private drift history and raises an aggregate drift flag when agreement or
label distribution changes sharply.

## Privacy boundary

No raw evidence text, URLs or domains may be committed to this public repository or written to public Actions
artifacts. The publicable model outputs are limited to the student weights, aggregate metrics and HMAC cluster map.
`tools/model_shadow_privacy_check.py` fails closed on private-field names, URLs and email-like values.
