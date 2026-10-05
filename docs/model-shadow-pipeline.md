# Model Shadow Pipeline

The model pipeline is observational only. Commercial and challenge gates remain authoritative and unchanged.

## Phase 0 — private label archive

The public repository contains only the schema contract in `docs/private-label-archive-contract.json`.
Raw cases must live in a separate private GitHub repository configured with:

- repository variable `MODEL_LABEL_REPO`
- repository secret `MODEL_LABEL_REPO_TOKEN`

Required private files are `train.jsonl`, `public.jsonl`, and `hidden.jsonl`.
Case IDs must be disjoint across all three files. Hidden labels accept only `human` origins and are written by Andrea. Empty or unlabelled evaluation sets block promotion.

## Phase 1 — independent judges

`model_shadow_registry.json` pins all model repositories, revisions, licenses and thresholds.
The batch computes lexical comparison and three independent training judges: multilingual zero-shot NLI, local quantized LLM, and structural signals. The lexicon never supplies a training vote.

Automatic training labels require at least three high-confidence agreeing judges.
Outcome labels override automatic consensus.

## Phase 2 — Render student

Actions trains a hashed character n-gram logistic classifier. Render loads only the compact NumPy artifact from
`runtime/model-shadow/student.json`. It runs beside the lexical classifier in shadow and records aggregate
agreement/disagreement counters only. The artifact is limited to 5 MB.

A newly trained student is published automatically to the public repository only after a batch completes and the student passes the existing non-regression checks on both the public and human-authored hidden sets. Incomplete or idle batches, missing artifacts, and any regression block publication.

This publishes the artifact in shadow mode only. It does not grant decision authority; production promotion remains manual-only.

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

The weekly scheduled workflow creates `weekly_review.html` in the private label repository with up to five cases, prioritizing high-confidence NLI/LLM agreement against the lexicon
for Andrea to review. It also stores private drift history and raises an aggregate drift flag when agreement or
label distribution changes sharply.

## Privacy boundary

No raw evidence text, URLs or domains may be committed to this public repository or written to public Actions
artifacts. The publicable model outputs are limited to the student weights, aggregate metrics and HMAC cluster map.
`tools/model_shadow_privacy_check.py` fails closed on private-field names, URLs and email-like values.

## Private bootstrap

The private batch imports at most 100 real observations per call from
`/api/model-shadow/private-cases`. In addition to retained commercial/challenge memory, production keeps a bounded in-memory shadow-only buffer of raw observed search rows. This buffer is excluded from commercial/challenge decisions and from durable checkpoints; its only consumer is the authenticated private export. The endpoint requires both existing per-path OPS
HMAC and a second proof using a purpose-derived key. It is read-only and sends
`Cache-Control: no-store`. Fixed-origin import refuses redirects and prints counts only.

The importer skips held-out IDs, deduplicates training IDs, and does not copy any lexical label into training. Before judging, the workflow rebuilds the 24-case public model evaluation set from the public control corpus and fetches the hidden control set from Render through a separate purpose-bound HMAC endpoint. Hidden rows are ephemeral on the runner, have human origin, are never committed to the public repository, and only aggregate evaluation results may leave the private batch.
`collect_only=true` imports without models, training or public publication. Fewer than
four training cases skip heavy downloads. No raw evidence is cached or uploaded as
public artifacts. Raw model errors remain in the temporary runner and are never printed.

## Consensus diagnostics

The private batch emits aggregate-only diagnostics for consensus path, NLI confidence bands, dual-prompt LLM validity/agreement, NLI x LLM label counts, and structural agreement state. The same counters are split by canonical source bucket. Weekly private review sampling includes discarded disagreements as well as accepted labels, prioritizing cases where the model judges agree but consensus still blocks training. No evidence text, URL, domain, or requester identifier is written to public logs or artifacts.
