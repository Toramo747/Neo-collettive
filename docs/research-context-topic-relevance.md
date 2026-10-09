# September source context × frozen commercial-topic relevance

The PR #236 replay found 18 records (out of 180) passing **content-only** buyer-intent guards within three September HN contexts. That does NOT mean 18 commercial leads: the relevance-to-problem gate was not tested. This experiment applies the **existing** production-derived `min_relevance_tokens=1` gate, without tuning it, for the four compact commercial topics that were already frozen in August PR #232:

- restaurant booking
- inventory alert
- file access
- returns label

All three September contexts and five-request budget remain identical to #235–236. Up to 60 HN items per source context are fetched; the same records are evaluated counterfactually with each frozen topic, using the unmodified official `diagnostic_metrics` and production-derived scorers. Per-topic evaluation must agree with the existing stage diagnostics, and each topical positive must be within the same source-context content-only positive population. The experiments are anonymous: no source text/IDs/URLs are persisted, and only counts per context and topic domain leave the GitHub Actions runner.

**Important:** the HN API was queried *by source context*, **NOT** by the four commercial topics. The `<topic> problem` query passed to the stage classifier is a synthetic, fixed role input; it was not submitted to HN. This is conditional fixed-corpus topic scoring, **not an end-to-end search benchmark**. A row could satisfy multiple topics; summed topic-record evaluations are not independent buyers or deduplicated commercial opportunities. September data are already DEVELOPMENT data, never untouched holdout.

The `source_context` parameter continues to do review routing **only** and never modifies an existing accept/reject label. No assertion of human-reviewed buyer demand, proven false positives, commercial gain, or source independence is allowed. No paid API/model use, no production gate, commercial thresholds, prices, memory, Render deploy, merge or promotion.

If this test finds no topic-relevant content candidates, it supports rejecting the *inference* that the 18 content-only matches represented commercial demand; it does not prove the classifier is accurate. If topical positives remain, two independent blind human reviewers must adjudicate those source examples separately before changing production rules.