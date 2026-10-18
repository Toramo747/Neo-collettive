# Evidence checker experiment — 18 October 2026

This PR is an offline/Common-mind experiment, not a Render release. Production
publishing and model adoption still require Andrea's approval. The benchmark
sentences, message bodies and per-row analysis remain private.

## Protocol

Use the same 53-row private benchmark (22 unsupported/invented-or-promise rows,
31 supported rows), the same public voice facts from base commit
`c1102acedc74774867384f714915a1da253d3772`, and `mode=evidence` for baseline and
candidate runs of `common-ensemble-cpu.yml`. Do not edit labels or source bodies.
Judge the ensemble rule, not whichever individual model has the best score.
Require zero inference errors. Adoption criterion: fewer false alarms than the
new baseline, with at least 19 of 22 unsupported rows caught.

The reported `ensemble.seconds` is the sum of each pair of small-model latency
maxima, plus 14B latency for disagreements. It estimates this decision rule's
latency; it is not the wall time of the matrix workflow, which runs all three
models. CPU-runner variation also limits timing comparisons. Tags are not
immutable model digests, so model-download reproducibility is a limitation.

## Preliminary diagnosis

The earlier evidence CPU result had 19/22 caught and 12/31 false alarms. Those
12 alarms fell into five manually reviewed groups: invitations (4), very short
mappings (2), general interpretation/advice (3), an informational pointer (1),
and supported paraphrases (2). This is a diagnosis of the historical result,
not a replacement for the new baseline. The current code already includes the
request category and typographic-quote normalization.

The saved result contains verdicts, not the model's raw evidence excerpt.
Consequently, a false alarm alone cannot establish whether a model chose the
wrong category, copied the wrong excerpt, or found too few exact words. Do not
attribute failures to punctuation without inspecting corresponding evidence.

## Safeguards

The exact evidence check still requires at least five consecutive normalized
source words for claims. Promises stay unsupported even if the source makes the
same promise. An invitation must not hide a factual assertion or a promise;
the separate Common drafting guard remains in force. Tests use new synthetic
examples rather than copying the private benchmark into the public repository.

## Proposed independent benchmark v2 (Andrea decision)

Collect new real drafts after freezing this experiment. Keep complete source
context and collect multiple languages and threads, with genuine invitations,
mixed thanks-and-fact sentences, supported paraphrases, fabricated actions and
promises. Keep whole threads separate from the tuning set; sentence-level
splits of one conversation leak context. Label before seeing model verdicts,
with Andrea adjudicating disputed labels. Preserve disagreements explicitly.

Reserve the new measurement file (for example `claims-v2-holdout.json`) in the
private archive solely for measurement. Do not use it to tune prompts; keep v1
as the visible development benchmark. Agree the size and acceptance policy
before collection. With only 31 good and 22 bad v1 rows, each example moves the
reported rates substantially: improvement here is preliminary, not proof of
reliability on new conversations. No automatic adoption or posting follows
from passing either benchmark.

## Trial 1: prompt clarification only

Append explicit instructions to classify the entire sentence, preserve future
commitments as promises, and distinguish pure invitations/advice from reported
facts or guaranteed effects. Clarify that a paraphrased claim still needs a
verbatim supporting source excerpt of at least five words; allow a longer
supporting source passage for a short draft sentence. A merely related passage
is explicitly insufficient. The schema, categories, normalizer, deterministic
evidence test, ensemble rule, source facts and private benchmark are unchanged.
No private example text is included in the prompt or tests.

Baseline and trial may run concurrently after their source commits are fixed;
this does not change their checked-out code. No adoption is proposed before
both finish and the private per-row comparison is reviewed.
