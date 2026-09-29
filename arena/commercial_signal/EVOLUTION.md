# Automatic evolution cycle

The optimizer reads only the current concordant dataset (`train_real.jsonl`) minus the fixed holdout IDs. The holdout file is public until a private evaluation repository exists; this is a methodological limitation. `evolve.py` never opens the holdout. Only `judge.py` reads it.

Initial split: 12 concordant cases -> 6 train and 6 holdout. The holdout is 50% and stratified 2/2/2 across REAL_DEMAND, VENDOR_OR_SELLER and NOISE, meeting the minimum of two holdout cases per label.

New concordant cases are added by the separate dual-label pipeline to `train_real.jsonl`. Every evolution run rebuilds train from that file while excluding the fixed holdout IDs, so new evidence becomes train data without exposing holdout to optimization.

The cycle is deterministic. Round N uses seed `20260929 + N`; the population starts from the baseline and existing alternatives and mutates only weights, demand threshold and vendor exclusions within the existing proposal schema. Positive marker vocabularies are not mutated. Complexity breaks score ties in favor of fewer markers/rules.

Cross-run state uses GitHub Actions cache because the workflow is intentionally restricted to `contents: read`. The identical state is also uploaded as a 30-day artifact for audit. A terminal SUCCESS or STALLED state makes later scheduled runs no-op.

SUCCESS requires holdout recall strictly above the baseline, zero vendor false positives on both train and holdout, for three consecutive rounds. STALLED means ten rounds without an eligible holdout recall improvement.

A known search-space limitation is detectable by the judge: the current evaluator requires at least one paid-marker hit for REAL_DEMAND. If the fixed positive-marker vocabulary cannot recognize any holdout REAL_DEMAND beyond the baseline, a stalled cycle is classified as `proposal_schema_or_marker_space_insufficient` rather than merely `more_data_needed`.

No result is adopted into the production gate automatically.
