# Anomaly Arena (2026-10-11)

Idea (Andrea): something escapes us that nature keeps signalling, the way OXIBAY looks for market signals. The Anomaly Arena listens to open tensions between measurement and theory in the public physics literature (arXiv) and follows them over time.

- Tracked: Hubble tension, evolving dark energy, S8 tension, neutron lifetime (beam vs bottle), W boson mass (CDF), lithium problem, Casimir / negative energy. Control: proton radius puzzle (widely regarded as largely resolved): if it ever shows up as "strengthening", the scoring is miscalibrated.
- Per anomaly, last 180 days: papers, abstracts stating a tension vs a resolution (negations handled), significances quoted in abstracts (median / max sigma), persistence = (tension − resolution)/papers, trend vs previous run (STRENGTHENING / STABLE / FADING).
- Daily at 05:11 UTC. Metadata only (ids, dates, titles); abstracts are read but not stored.
- Rules as in OXIBAY: only measured signals with their uncertainty, no suggestion counts, verify before believing. These are literature attention signals, not physical evidence; promotion to any research decision is human only.
- Known limits of v1: keyword cues on abstracts are crude; quoted sigmas mix different analyses; arXiv returns at most 200 papers per query (large topics may be capped, flagged in `window_capped`).

### Fix after the first run (same day)
The first observation counted the searched phrase itself as a cue ("Hubble tension" → tension; "proton radius puzzle" → puzzle), inflating persistence (Hubble 0.42, control 1.0). Searched phrases are now removed from abstracts before scoring, and two queries that returned nothing (S8, W mass) were broadened. The first observation is discarded as a baseline.
