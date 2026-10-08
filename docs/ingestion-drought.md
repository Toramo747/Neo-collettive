# Ingestion drought — observation only

Base: main 9697080. No ingestion fix, query change, threshold change, hidden-case
change, or evidence-memory replacement change is included in this PR.

## Production evidence available before instrumentation

These are three real published observations, not three consecutive cycles:

| Cycle | UTC 2026-10-08 | Raw | Relevance pass | Useful | New signals | Memory | Quarantine | no_demand_signal | no_family | weak_family_relevance |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 2914 | 15:19:59 | 144 | 107 | 1 | 0 | 141 | 96 | 32 | 15 | 15 |
| 2920 | 15:54:21 | 135 | 97 | 0 | 0 | 141 | 96 | 18 | 32 | 11 |
| 2926 | 16:27:25 | 144 | 120 | 0 | 0 | 141 | 96 | 37 | 20 | 16 |

Source: repository snapshots 9b8e9be, 36ef88e, 9697080.
Raw results continue to arrive; at least the three reported rejection categories
account for 62, 61 and 73 results respectively. The existing stages have different
denominators (provider receipts versus routed results); do not subtract their
totals to infer duplicates. The public snapshots contain no raw-result identities.

**Conclusion: (b), predominantly new-to-memory results being rejected.** The
three consecutive instrumented production cycles below establish this result.
The older snapshots alone could not distinguish the cases; historical duplicate
counts cannot be reconstructed from those aggregates.

## Added observation

Every routed provider receipt keeps a private URL/fingerprint, relevance decision
and terminal reason. Raw routing duplicates, missing URLs, irrelevant rows,
relevance errors and results omitted by routing limits remain accounted for.
Ingestion outcomes join those receipts by query slot and normalized URL.
Non-routed groups and scouts receive receipts at ingestion. Memory membership is
captured before the cycle across active, archived and pending evidence; it uses
normalized URL OR an existing fingerprint. No URL-only replacement fingerprint is
invented when a source does not provide one.

Public `select_diagnostics.ingestion_drought.rows` contains numeric/boolean leaves only:
query_slot, provider_code, raw_results, relevance_pass, useful, new_signal_row,
duplicate_memory, new_rejected and numeric rejection codes/counts. Slots are
cycle-local ordinals, not query hashes. Use the private receipt/query mapping for
cross-cycle comparison of the exact same query. Useful means accepted into
current_rows, including quarantined rows, matching the existing useful metric.
New signal means the existing eligible-positive-demand insertion event. Counts
are per receipt, not unique URLs, so repeated returns are visible.

Provider codes: 0 unknown; 1 Bing; 2 Brave; 3 Google PSE; 4 HN; 5 GitHub;
6 StackExchange; 7 Remotive; 8 RemoteOK; 9 persisted price cache (not a live search).
Reason 14 is appended as `unjoined`; existing codes retain their positions.
`routing_limit` is set only by the router at its actual cutoff. Unmatched
receipts are `unjoined`; `unjoined_total` and `measurement_reliable` expose
whether the counters can support a diagnosis. Query keys use lowercase,
compressed whitespace, normalized URL and canonical source on both sides.

Reason codes are the positional enum in ingestion_drought.REASONS; no private
labels are exported. An unrecognized provider/reason maps to 0.

## Regex equivalence

The pre-a75b57e family scorer and pre-612ffe4 term matcher are run against the
same seven synthetic result texts through the full production ingestion function.
Family scores, intent/demand labels and rejection decisions retain the reference
tests from both commits. The new integration test also compares per-result funnel
outcomes, useful count, rejected rows and problem clusters, including Unicode,
vendor pricing and a 68 KB unrelated body. This is a reproducible offline
equivalence sample, not a replay of inaccessible private production results.

Three offline cycles additionally verify URL/fingerprint membership and exact
accounting: each has raw=4, relevance=4, useful=1, new_signal=1,
duplicate_memory=2, new_rejected=1. These numbers are fixtures, not Render data.

## Proposed fix, deliberately not applied

After deploying observation, collect three consecutive production cycles and
compare private query mappings. If (a), rotate saturated queries toward unseen
surfaces using free providers and keep all guards. If (b), review new rejected
rows against their query intent and family; improve query precision first, and
correct a classifier only if a labelled regression demonstrates an actual bug.
For mixed results, apply those changes independently. No threshold relaxation
is proposed. Preserve raw/private data access boundaries.

## Production acceptance and diagnosis (2026-10-08)

PRs #218 and #219 were merged in that order. Production commit
`ac91d2aaaba44d86232b863d51448535d723b623` passed the full deploy workflow:
[run 37830095916](https://github.com/Toramo747/Neo-collettive/actions/runs/37830095916).
Its read-only acceptance step emitted the three public numerical projections
below and `three_consecutive_cycles_valid=true` at 19:26:27 UTC. No rollback
was required. Rows were nonempty and unjoined_total was zero for every cycle.

| Cycle | measurement_reliable | evidence_out | stored_bytes | Raw | Duplicate memory | New rejected | Useful |
|---|---|---:|---:|---:|---:|---:|---:|
| 2956 | true | 145 | 51,615 | 142 | 4 | 138 | 0 |
| 2957 | true | 145 | 52,275 | 140 | 7 | 133 | 3 |
| 2958 | true | 145 | 53,267 | 141 | 3 | 138 | 2 |

Counts by provider across those three cycles (receipts, not unique URLs):

| Provider | Raw | Duplicate memory | New rejected | Useful |
|---|---:|---:|---:|---:|
| Bing RSS | 237 | 3 | 234 | 3 |
| Brave | 12 | 0 | 12 | 0 |
| HN | 114 | 8 | 106 | 2 |
| GitHub | 58 | 3 | 55 | 0 |
| Unknown (code 0) | 2 | 0 | 2 | 0 |
| Total | 423 | 14 | 409 | 5 |

Only 14/423 receipts (3.3%) matched existing evidence; 409/423 (96.7%) were
new to memory and rejected. Useful is not an additional disjoint category:
all five useful receipts were already in memory. New-signal insertions remained
zero. This supports case **(b)** as the principal measured cause, not saturation
of already-stored evidence. Some overlap exists, but it is a small minority.

Rejection counts include no_demand_signal=80, no_family=56 and
weak_family_relevance=65; the other reasons are query_irrelevant=82,
routing_limit=68, noise_domain=33, github_no_buyer_problem_context=23,
github_noise=7 and routing_duplicate=4. Thus not every new rejection is a
classifier rejection: routing and relevance filtering also contribute.

These counters define new relative to evidence memory, not relative to all
previous searches. They cannot establish whether the same rejected URLs recur
across cycles; that narrower search-saturation question needs private receipt
comparison. No classifier defect follows merely from rejection counts. The
regex equivalence sample above remains identical, with the stated sample limits.

Proposed next fix: improve query intent/family precision for the dominant new
rejections, after reviewing their private examples; rotate queries only where
repeated rejected URLs demonstrate saturation. Preserve all gates and thresholds.
No such ingestion fix is applied in this PR.


## Review corrections A/B (2026-10-08)

A regression test was written and run before B's repair. It failed because
`_record_director_result` wrote private_results/private_queries into the disk log
and `_load_recent_results` loaded them back. Full private receipts now remain
only in the in-memory result and existing ADMIN routes; the disk history and
checkpoint discard them. Old disk records are sanitized when read. The cycle
result has one drought block, under evidence_quality; its top-level diagnostics
retain the other counters without a second drought copy.

The checkpoint strips these private diagnostics before encoding even when size
compaction is not triggered. `drop_ephemeral_checkpoint_state` also strips them.
Protected state, evidence rows and their invariant are not traversed or changed.
The recovery payload builder receives the same pure stripping helper.

Production state_codec measurement with 3 simulated cycles of 150 receipts:
baseline 13,447 encoded bytes, instrumented 14,015, delta **568 bytes** (limit
3,000). This is the isolated fixture measurement, not Render checkpoint size.
The production pre-deploy checkpoint observed at 18:55 UTC uses 53,367/100,000
bytes. The public snapshot was stale; post-deploy acceptance must use fresh,
consecutive cycle observations, not repeats of that snapshot.

Deployment acceptance uses the existing ADMIN status route in read-only mode,
with the workflow's existing token. It waits for three completed consecutive
cycles and logs only the public numeric/boolean drought projection, cycle number,
evidence_out and checkpoint bytes. Any failed condition or observation timeout
fails deployment verification and invokes the existing rollback. No repair is
attempted in production.

Full Python 3.12 verification after review corrections and acceptance tests:
`971 passed, 1 warning, 702 subtests passed in 42.12s`.
