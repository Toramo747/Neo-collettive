# Eight-gamete external shadow screen: preregistered on 9 October 2026

## Exact hypothesis

Test all **eight pre-generated gametes** from PR #230 against the original
**matched compact query baseline**. Data used to generate gametes (May, June,
July 2026) is never used as an evaluation window. Test separately archived
August and September 2026. This is a **retrospective backtest**, not a
prospective experiment and not independent external buyer validation.

Four task families use new topics not previously selected in research
experiments: retail shelf stockouts, hotel housekeeping, parcel exceptions,
and library catalogue corrections. Topic semantic independence is not certified.
The previously scored August–September HN provider content may overlap other
research experiments; interpretation MUST remain exploratory, not a fresh
source-verified independent replication.

Each gamete receives four topics x four queries = 16 attempts **per month**,
just like the matched baseline. Source HN Algolia search_by_date only; exact
fixed month timestamps; max 30 hits/query. At most 144 different requests
each window (max 288). Duplicate queries across arms are fetched only once;
source data stays in process memory for the month and is not persisted. No
paid API or model required, subject to GitHub Actions free-plan quotas.

## Prespecified strict screening

For every gamete and month: provider 16/16 queries, diagnostic/score agreement,
synthetic plumbing control, matched baseline >=8 relevant records, >=2 net
additional unique discussions, >=2 topics and no precision regression. Penalize
additional duplicate ratios and unstable gains using the *frozen* novelty and
temporal-robustness coefficients generated in PR #230. Require both months to
pass before a **shadow candidate** designation. All other outcomes are
negative, insufficient, invalid or inconclusive; no selective reruns or
parameter retuning after observing results. The result is not commercial proof.

There are **eight simultaneously screened variants**, hence multiple testing
increases false discovery risk. A favorable finding only creates a future
review candidate, NOT a proof of superiority, with
`independent_validated_replications=0`. A separate prospective, multi-source
and blind human-labelled validation is required before any manual promotion.

## Privacy and operational safety

No raw public comment text, usernames, URLs, HN IDs or query strings are
included in GitHub artifacts or logs. Per-window aggregates record only
rejection categories, signal counts, precision, duplication and per-gamete
verdicts. No production state, model/student, price cache, gate thresholds,
policy, evidence memory, Render or main branch changes are made.

No implicit or unapproved merges or deploys.

Commands:

    python -m unittest -v test_research_autocorrection test_research_autocorrection_external
    python experiments/research-autocorrection-external/compare.py
    python experiments/research-autocorrection-external/compare.py --execute

Run the last command only on the isolated branch/CI. Save the complete
aggregate report including negative results and do not reuse these months
as an independent validation of any candidate.
