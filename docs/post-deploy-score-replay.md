# Competitor-price cache replay: confirmed equivalent-state defect

Base main: 9697080. This is a repair of durable scoring observations, not a
change to scoring weights or either gate's acceptance conditions.

## Evidence and attribution boundary

Public candidate fcd986b2d09b3548 had score 85/raw pass at cycle 2914 and score
35/raw fail at cycle 2926. Its missing codes changed from [] to
[two_competitors_with_real_price, monetization_score_60]. This isolates the
observed difference to priced competitors, but public aggregates cannot show
which private input field caused the real incident.

The new anonymous fixture reproduces a **confirmed cache representation defect**:
two current strict pricing observations plus a buyer gap produce 85, [] and
true. The durable price cache keeps only a short price_context. Replaying it
replaces title with domain and removes the original snippet. After checkpoint,
all compaction levels, codec decode and the real _merge_state_payload, the same
observations produce 25, [two_competitors_with_real_price,
monetization_score_60], false on unmodified main.

Changed fields are the scorer's title, excerpt/family relevance and signal_types
(including TREND and potentially COUNTER outside the price window). The price
amount itself survives; the classifier no longer sees the evidence that makes
it a competitor in this family. Memory length remains unchanged. Compaction's
protected commercial_price_evidence is byte-identical: the loss happens in
compact_price_evidence/persisted_price_groups, not replace_evidence_memory.

This is **not yet proof of the exact production fcd986b2 cause**: its private
price/demand observations were unavailable in this session. The reproduced
delta is 85 -> 25; the actual public delta is 85 -> 35. Do not conflate them.

## Repair

Persist a versioned, bounded normalized scoring receipt alongside each strict
price window. It contains the existing _source_row observation, including the
original title, 500-character excerpt, signal tags and strict price facts; full
HTML and fetched page text are not stored. No generated demand markers or cached
monetization score are added. Existing cache row limits remain unchanged.

Use receipts only on the internal persisted_strict path with matching family,
URL and source. Recheck the price amount/currency/period against the original
title and price window, validate the receipt structure and allowlist its fields.
Fresh provider payloads cannot override classification using receipt keys.
Legacy/malformed receipts follow the previous parser path; missing historical
context cannot be reconstructed and is not invented.

The normalized receipt has already been produced by the unchanged classifier.
Reusing it makes the same observation stable across restart. New observations,
retention and query rotation can still legitimately change a later cycle's score.

## Verification

The regression was run before the fix: all three initial tests failed, including
85 -> 25 and 65 -> 25 with counter-signals outside the price window.
After the fix, tests cover passing and failing raw gates, exact missing-code
equality, title-only prices, counters outside the window, reversed evidence
ordering, three successive checkpoint/restore operations, malformed/legacy
receipts and attempted receipt injection from a fresh provider.

The existing post-deploy guard, score formula, commercial/challenge thresholds,
hidden control and evidence-memory invariant are untouched.

## Pending production acceptance

No merge or deploy was performed. Three **real consecutive deploys** remain
unverified. For each, compare the last pre-deploy candidate score with the first
post-deploy score (tolerance 0) and check post_deploy_pass_ignored=0. Record the
same candidate ID and observation inputs; if fresh provider inputs differ,
identify the input change rather than forcing scores to match. A legitimate raw
pass still invokes the unchanged first-cycle guard; do not falsify its counter
to satisfy acceptance. Offline restore repetitions are not deployment evidence.

Old caches without receipts require normal re-observation of competitor inputs;
this patch cannot recover deleted context from historical compact windows.
The PR remains draft pending private production replay and the requested deploy
acceptance evidence.
