# Context-aware review annotations vs legacy content-stage guards

Stacked on PR #235. The 25 buyer-voice + commercial-family overlaps observed in September are **heuristic coincidences, not classifier positives**. This experimental follow-up asks how many newly retrieved records also pass the pre-existing supply/vendor and demand-tag guards.

We reretrieve up to 60 public HN hits from each of the same three **September development contexts** in at most five requests. The historical index might return different records from #235; values here must not be described as paired longitudinal changes.

For each deduplicated record the existing production-derived guard predicates are applied in the same order:
1. vendor or supply offer
2. unknown commercial family
3. no buyer voice
4. no positive demand tags
5. `passes_content_only`

**Crucial limitation:** this source-context probe has no customer-problem query, so its evaluator intentionally omits commercial *topic relevance*. Consequently `passes_content_only` is *not* an accepted commercial signal or a full `score_hits` result. Even this label is not proof of human demand. The reviewer-only `source_context` annotation cannot change any stage, matching what the experimental parameter promises. Show HN projects remain mixed and never blanket rejected.

Only aggregate counters may leave the runner. Identifiers, URLs and source text exist in memory for diagnostic processing only; no private datasets, model training, commercial production gate changes, threshold modifications, Render deployment or promotion. A genuinely new independent matched research test and two blind human reviewers would be required to justify changing production detection rules.

If this replay eliminates most buyer-family coincidences at existing gates, context would be a low-priority improvement hypothesis. If many remain, flag them for real blind review before altering acceptance. Either way, no automatic veto based on thread title.