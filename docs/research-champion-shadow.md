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
| 2026-10-11 05:44 | training | 1 | 1 | 13 | 0 | 0.194 | 0.167 | 71 |
| 2026-10-11 05:44 | holdout | 0 | 0 | 1 | 0 | 0.033 | 0.000 | 55 |
| 2026-10-12 06:06 | training | 1 | 1 | 13 | 0 | 0.217 | 0.200 | 66 |
| 2026-10-12 06:06 | holdout | 0 | 0 | 3 | 0 | 0.079 | 0.000 | 63 |
| 2026-10-13 05:5x | training | 1 | 1 | 12 | 0 | 0.188 | 0.200 | 68 |
| 2026-10-13 05:5x | holdout | 0 | 0 | 2 | 0 | 0.095 | 0.000 | 62 |

### Note after run 1 (amendment, declared openly)
PROD_EQ retrieved only 7–8 stories for 120 requested hits: a bare topic phrase restricted to stories in 45 days finds almost nothing. On training, CHAMP's advantage is volume (13.98 vs 14.29 signals per 100 hits: same yield per hit). On holdout every arm is near zero (CHAMP 1 signal out of 83 hits).
The original rule is degenerate when the baseline is 0 (1 >= 1.5 x 0). Amendment for runs 2–3, stated before running them: condition 1 also requires **CHAMP holdout `signal_hits` >= 5**. Run 1 passes the original rule only trivially and fails the amended one.

### Run 2 (2026-10-12)
Holdout: CHAMP 3 signals vs PROD_EQ 0. Fails the amended condition (CHAMP holdout `signal_hits` >= 5). Two runs out of three now fail it, so the rule cannot be met in 3/3 runs: **no promotion** whatever run 3 shows. Run 3 is still executed for the record.

## Final verdict (after run 3, 2026-10-13): NEGATIVE, no promotion
Holdout CHAMP signal_hits across runs: 1, 3, 2 (amended threshold: >= 5 in every run). 0 of 3 runs pass.
On training topics the champion finds 12-13 signals vs 1, but on topics it never trained on it finds
almost nothing more than production: the evolved genome fits its training topics and does not
generalize. Recorded as a negative result; the arena's champion is not proposed for a production trial.
