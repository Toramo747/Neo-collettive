# Research experiments of 2026-10-09 (consolidated)

Fifteen stacked, shadow-only draft PRs (#225, #227–#240) tested whether the evolved research genome (g69-elite-1) and its variants find more real demand on Hacker News than a matched baseline. None changed production. This page keeps their protocols and outcomes; the PRs were then closed with Andrea's authorization on 2026-10-11. The branches remain on GitHub.

## Outcomes

| PR | Question | Outcome |
|---|---|---|
| #225 | Independent holdout, 4 new topics, 16 queries per arm | **NO_DEMONSTRATED_GAIN.** Retrieval improved (27 vs 3 objects, 13 vs 1 relevant), but both arms had 0 valid signal threads. The topics were only lexically, not semantically, independent. |
| #227 | Disjoint-topic holdout plus rejection diagnostics | 0 vs 3 distinct valid signal threads: **CANDIDATE_FOR_FUTURE_REPLICATION**, a single run, not validated. |
| #228 | Matched-baseline replication, two panels | Found and fixed a **diagnostic bug**: the long-text `clean_text` limit made the diagnostics disagree with the scorer, giving 5 against 4 signals. With a fail-closed metric audit, panel A (weak baseline) was inconclusive. In panel B the evolved arm had 3 unique threads against 1 for the matched baseline, with precision 0.25 against 0.13: a candidate only, not validated. |
| #229 | Three preregistered historical windows (May, June, July 2026) | **NO_REPRODUCIBLE_TEMPORAL_GAIN.** 0 of 3 qualifying windows (May 0 vs 0, June 1 vs 1, July 2 vs 2 signal threads). |
| #230 | Generator of 8 rejection-guided gametes trained on the May–July aggregates | Generator only; all variants unvalidated by design. |
| #231 | Eight gametes on archived August–September data | Protocol for an external comparison; no separate result recorded. Its adapter's strongest possible verdict was a review candidate, never promotion. |
| #232 | Fresh, equal-budget August screen of the 8 gametes | **All 8 rejected.** The matched control found 5 unique threads (precision 9.4%); the gametes found 2, 2, 0, 0, 0, 0, 0 and 0. August is now development data and cannot serve as validation. |
| #233 | Local, private, double-blind human audit of classifier errors | Tool only; it needs two human reviewers and was never run. |
| #234–#235 | Context confounding on HN job threads and showcases | In a "who wants to be hired" thread, 45 of 60 comments matched a commercial family but only 4 of 60 had a buyer voice: **supply is easily mistaken for demand**. Review-only parameter; no human adjudication. |
| #236–#237 | Replay of guards and topic relevance on the September overlaps | Diagnostics to reject or keep the inference that content-only matches are demand; no separate result recorded. |
| #238 | October end-to-end retrieval with a review-only context annotation | Integrity check only; by design it changes no score. |
| #239 | April pain-query mode against mixed mode | Preregistered screening rule; no separate result recorded. |
| #240 | Buyer/seller role collision diagnostic on March data | Review-priority ordering only; no separate result recorded. |

## Conclusions

1. **No replicated gain.** The evolved genome showed isolated favourable runs (#227, #228 panel B) but failed the preregistered temporal test (0 of 3 windows) and the fresh screen (0 of 8 gametes). Raw retrieval volume rose; validated signal threads did not.
2. **The bottleneck is labelling, not search.** Every protocol ended needing human or independent ground truth. That need led to the teacher model (maestro, `docs/maestro.md`), which now ranks a parallel arena lineage and is being compared with the lexicon under a preregistered rule (due 2026-10-25).
3. **Supply confounds demand** (#234–#235). This links to the HN retrieval shadow running now (`docs/hn-retrieval-shadow.md`), where comment-based retrieval is under test.
4. The metric-integrity audit from #228 (scorer and diagnostics must agree, otherwise the result is INCONCLUSIVE) is good practice for any future research experiment.
