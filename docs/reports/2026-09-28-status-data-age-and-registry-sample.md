# Status-data age and Registry sample note — 2026-09-28

Reference report time: `2026-09-28T20:12:00+00:00` (22:12 CEST).

## Age of runtime data

During this audit, `main` received runtime snapshot commit `d56bc90dd7aa6ad898032a70b5384991e98585f5`.

- Cycle floor: **830**.
- Last completed runtime cycle: `2026-09-28T20:07:50.943121+00:00`.
  - Age at the reference report time: about **4 min 9 s**.
- Latest endpoint-latency capture: `2026-09-28T20:09:28.715360+00:00`.
  - Age at the reference report time: about **2 min 31 s**.
- Latest first health sample: `2026-09-28T20:09:25.285Z`, 782.59 ms.
- Latest subsequent health sample: `2026-09-28T20:09:28.091Z`, 670.33 ms.

These ages are relative to the stated report reference time, not the time at which a reader later opens the file.

## Registry FINAL sample selection

The immutable 27 September FINAL remains unchanged.

Persisted sample metadata:
- scope: `SAMPLE`
- population of Registry-declared remote-verifiable servers at snapshot: **21,603**
- completed sample: **663**
- recorded seed: `2140928784970561546`
- `sample_server_names` is persisted for exact replay.

The scanner implementation creates a copy of the remote-server population and runs `random.Random(seed).shuffle(items)`. It then probes that randomized order until the configured wall-clock sample budget is reached. Therefore the 663 servers are a **time-bounded randomized prefix of a seeded random permutation**, not the first 663 Registry entries and not a stratified sample.

The stopping rule is time-based, so the achieved sample size was not fixed in advance. Because probe duration can vary by endpoint and can be related to health outcome, the usual fixed-size simple-random-sample interpretation is an approximation.

## OK + OK_WITH_ISSUES

Observed in the FINAL sample:
- OK: 220
- OK_WITH_ISSUES: 205
- combined: **425 / 663 = 64.10%**.

For the requested random-sample uncertainty indication, the **95% Wilson interval** for 425 successes in 663 observations is approximately **60.38% to 67.66%**.

Interpretation: this interval is a conventional binomial/Wilson interval for the observed randomized sample. It does not remove the design caveat introduced by the time-budget stopping rule, GitHub Actions network vantage point, or endpoint-dependent probe durations. The 64.1% should therefore be described as the observed share in the seeded, time-bounded randomized sample, with the approximate interval above, rather than as an exact Registry-wide health rate.
