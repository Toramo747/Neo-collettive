# Residual intent classification stall after #216

## Observed problem

Production observation deploy of commit a75b57e, run 37799354906, first cycle 2914,
instance 6q52s, 2026-10-08 (UTC):

- 15:18:45.568: stack in evidence_integrity.contains_term → buyer_voice_present →
  classify_intent_class → cloud_mcp.ingest → _commercial_evidence_quality →
  director_run → _autopilot_cycle.
- 15:18:49.576: gate 6974.645 ms wall, 1060.451 ms process CPU.
- 15:18:50.265: event_loop_stall 7440.138 ms.
- First-cycle aggregate: autopilot 30045.741 ms; one stall; codec_offthread=false.
- Public snapshot captured 15:19:59.842 UTC confirms these aggregates.
- Arena smoke passed at its first attempt after the cycle (15:19:10–15:19:13).

The sample proves execution in this path during a stall. It does not attribute the
entire gate duration to one function. The observer's later private stack also
sampled price_validation.extract_price; that function is not changed here.

## Reproduction and measured cause

Offline cProfile of 24 synthetic 65535-character bodies through
classify_intent_class with a generic web source: original regex searches consumed
6.755 s of 6.993 s. Buyer and seller phrase checks repeatedly search the whole
body for absent terms. This is the same contains_term primitive sampled in the
production stack. No private evidence is read or copied into the replay.

The only runtime function changed is contains_term. For literal ASCII terms, an
absence prefilter avoids the regex scan. The original regex still decides any
possible match. Controlled forms manual/spend/waste time and non-ASCII terms
bypass the prefilter. Case folding with explicit dotted/dotless I handling
preserves Python IGNORECASE's ASCII/Unicode equivalences. No word boundaries,
weights, intent precedence, signals or gate conditions are changed.

No payload truncation, evidence retention change, mutable-state offload, cache,
checkpoint mode change or Arena change is included.

## Repeatable checks

Run `python scripts/reproduce_intent_classification.py` on Linux. The script pins
itself to one available CPU and measures the real classifier under the loop
observer. Numeric output is in intent-classification-replay.json:

| Synthetic replay | Before | After |
| --- | ---: | ---: |
| Wall ms | 6351.827 | 821.409 |
| Process CPU ms | 6343.494 | 821.113 |
| Regex searches | 4728 | 312 |
| Maximum loop lag ms | 6341.960 | 811.749 |

All intent outputs are identical. The replay is not the full first autopilot
cycle, does not simulate Render's 0.15-core quota and cannot establish a production
lag below one second. Timings are observations, not CI thresholds.

The deterministic regression fails on the previous matcher: 35 regex constructions
for absent buyer phrases instead of zero. With this change it passes. Other tests
compare the original matcher across phrase lists, boundaries, controlled forms,
Unicode and deterministic random strings. Voice, intent and demand decisions on
all text fields of public commercial/challenge controls match the old matcher.

## Production validation still required

No merge or deploy is authorized for this follow-up. After Andrea's approval,
leave codec=0 and use the observation deployment procedure from #215. Record the
first cycle's maximum lag, gate timings, private project-only stack and first Arena
smoke attempt. Require maximum lag below 1 s. If a different path remains sampled,
report it before changing that path. Do not infer production success from the
synthetic replay or the smoke alone.
