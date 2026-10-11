# Research arena champion — shadow review (preregistered 2026-10-11)

Candidate: `g75-elite-1` (generation 75, fitness 71.33, `MANUAL_REVIEW_ONLY`).
Genes: mixed/core suffixes (`problem`, `pay for`, `workaround`, `manual`), compact topic, signal-first, plain frame, stories+comments, 45 days, 4 queries x 30 hits.

## Question
Does the champion's query strategy find more real demand signals than the way production queries Hacker News, on topics it never trained on?

## Arms (all scored by the same scorer: `arena_research_algorithm.score_hits`, production primitives)
| Arm | Queries per topic | Scope | Hits |
|---|---|---|---|
| PROD | bare topic phrase (what `natural_search_seed` yields for a term) | stories | 3 |
| PROD_EQ | bare topic phrase | stories | 120 (champion budget) |
| CHAMP | 4 champion queries | all | 4 x 30 |
| CHAMP_BUDGET | first champion query | stories | 3 |

PROD vs CHAMP_BUDGET isolates wording at production budget; PROD_EQ vs CHAMP isolates wording at equal volume.

## Topics
- training: the 4 arena topics (champion evolved on them for 75 generations: expect an advantage here, it proves nothing).
- holdout, fixed before the first run: `crm lead tracking`, `employee onboarding paperwork`, `pdf document extraction`, `ecommerce inventory sync`.

## Decision rule (fixed now, before any result)
Recommend a production trial only if, on **holdout**, in **3 runs on different days**:
1. CHAMP `signal_hits` >= 1.5 x PROD_EQ `signal_hits` in every run, and
2. CHAMP `precision` not lower than PROD_EQ by more than 0.05, and
3. CHAMP adds threads PROD_EQ does not find (`champ_only` > 0).

Otherwise: no promotion; the result is recorded as negative.
A production trial would itself be a separate, authorized change (shadow first, no gate change).

## Boundaries
Public HN Algolia only, read-only. Aggregate counts only (no text, URLs, ids). No production state read or written. No gate, threshold or policy change.

## Runs
| Date (UTC) | Set | PROD sig | PROD_EQ sig | CHAMP sig | CHAMP_BUDGET sig | CHAMP prec | PROD_EQ prec | champ_only |
|---|---|---|---|---|---|---|---|---|
