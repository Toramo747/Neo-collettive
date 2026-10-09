# Disjoint-topic research holdout v2 — shadow, no production writes

This is a **new experiment**, not a retry or rewrite of the prior holdout.
Prior v1 (GitHub Actions 37876682507) remains **NO_DEMONSTRATED_GAIN**:
baseline 3 HN objects / 0 valid signal threads; g69-elite-1 27 objects /
0 valid signal threads. Both arms completed 16/16 queries.

## Preregistration and boundaries
- Source: one free public Hacker News Algolia search_by_date endpoint.
- Run four distinct topical families: customer support routing, Shopify catalog
  synchronization, podcast editing, broken-link website QA. These avoid the
  four evolution topic names and four v1 holdout topic names, and are judged
  topically distinct from finance, compliance, payroll and spreadsheet cases.
  This is a **manual topical assertion, not independently certified semantics**.
- Fixed g69-elite-1 genes; exact-topic baseline, signal-first compact-topic
  treatment; 16 queries per arm, fixed 45-day cutoff per round, 30 hits
  per query and shared HN source. The two arms are compared without modifying
  champion fitness, production thresholds, scoring, memory, or provider budgets.
- Deduplicate HN objectIDs within each arm, unique discussion threads for
  signals, and record mutually exclusive rejection stages per topic.
- Positive and negative tests are **author-labelled synthetic controls**.
  Positive is adapted from an existing public arena unit-test phrase. These
  controls are never included in HN result counts or presented as
  human-verified buyer evidence.
- Missing query responses => INCONCLUSIVE_PROVIDER_FAILURE. Failed
  controls => INVALID_CONTROL. Zero/zero signal results => NO_DEMONSTRATED_GAIN.
  Candidate requires +2 unique valid signal threads, non-decreasing signal
  precision and two represented topics. A single positive round is **not**
  validation: three separate qualifying, independent rounds would be needed.
- No auto-promotion, commercial influence, private input, paid APIs,
  external tool execution or production writes. No raw HN text, URLs, object
  identifiers or query text are persisted in artifacts. Only public aggregate
  counters and predeclared topic labels are emitted.

## Running
Default command only verifies the plan and does not use network:

    python experiments/research-holdout-v2/run.py

Explicit read-only public HN run:

    python experiments/research-holdout-v2/run.py --execute

The branch-only GitHub Actions workflow runs once after creation and uploads
a JSON aggregate artifact for auditing. Do **not** merge the stacked draft PR
or deploy it. Do not claim human-labelled data or commercial qualification.

## Review and next decision
Review per-topic rejection proportions and the positive/negative controls.
If query precision is too low, preregister a *third* search experiment without
changing v2. If the synthetic control passes but actual content is rejected,
only independently human-labelled real examples can establish a classifier
bug. Do not train the student on this zero-signal experiment.
