# Market Intuition Arena

Opened 2026-10-12 at Andrea's request: a continuous arena (one generation every
30 minutes) with a self-evolving algorithm, to see how far an open-ended search
for real markets gets once competitor-price validation is retired.

- **Genome:** two pain phrases, two problem terms, two free public sources
  (HN comments/stories, Stack Exchange softwarerecs/superuser/webapps/stackoverflow),
  a time window, and the genome's own mutation rate.
- **Fitness:** 10 per *new* person describing a problem in their own voice,
  3 per already-seen person, 15 per person signalling willingness to pay,
  20 per problem term with 3+ people in the same generation, 30 x precision.
  Hits are classified by `market_inference.classify_row` (demand/supply/noise).
- **Self-evolution:** log-normal self-adaptive mutation rates; a learned
  vocabulary (words recurring in demand from different people are reinforced,
  others decay); a hashed novelty archive; more immigrants after 6 generations
  without new people.
- **Isolation:** no production state, gate, evidence memory or search budget.
  State and discoveries live only in the private archive (`market-intuition/`);
  the public log prints aggregates and generic problem terms only. Nothing is
  promoted automatically.
- **Known limits:** keyword classifiers, two sources only, HN skews to
  developers. A high fitness is a lead for human review, not proof of a market.

## v3 — the mind (2026-10-12)

Andrea asked for a spark of autonomy: the arena now has a local LLM "mind"
(qwen2.5 3B via Ollama on the GitHub runner, zero cost). Each generation it:

1. **judges** the candidate need sentences (real need? which problem? any
   hint of paying?) and only confirmed needs count for fitness;
2. **thinks**: writes an observation and a hypothesis into its diary, assigns
   each need to a problem in its **market map** (problems with how many
   different people share them), proposes up to 3 new search terms and 2 new
   first-person phrases, and drops terms that keep failing;
3. **learns from its ideas**: genomes born from its proposals are tracked and
   their results are fed back into the next thought.

Fitness adds 10 per need that belongs to a problem already shared by 3+
different people. The mind's output is sanitized short strings only; it cannot
run code, alter the fitness rules, reach production or publish. Diary, market
map and discoveries stay private.

Earlier fixes the same morning: v2 requires the need and the term in the same
sentence (v1 rewarded unrelated chatter: 45 → 3 when replayed), broad
retrieval with strict filtering, and a self-chaining loop because GitHub's
scheduler had stopped firing.

## Deep mind on Kaggle (2026-10-12)

Every 12 generations (~6 h) the arena dispatches `mycelix-market-mind-deep`:
a private Kaggle kernel on a free T4 runs qwen2.5 **14B** over the queued need
sentences (max 150, people only as hashes), re-judges them, assigns problems,
merges synonym problems and writes a deeper diary entry with new ideas. The
result lands in `deep_inbox/` and the next generation applies it (deep verdicts
override the small mind). GPU use is tracked privately with a 25 h/week cap.
Measured on Kaggle: 14B fully on GPU, ~3.5–5 tokens/s, so a session takes
about 30–40 minutes.

## Fixes and focus (2026-10-12 afternoon, authorized by Andrea)

- `pay` now counts DIFFERENT people hinting at paying (`payers` list); v1 could
  exceed the number of people (6 of 3) because deep reflections re-added them.
  Old entries are clamped at load.
- Discoveries keep one row per person per generation.
- **Split vague problems:** each deep reflection also re-judges members of
  problems with 3+ people that the 14B model has not judged yet, so lumped
  labels (e.g. "automation code management": specs, salary, a broken monitor,
  meeting transcription) get split into their real problems.
- **Focus:** 2 genomes per generation search the first credible signal,
  monitoring that costs too much ("database monitoring", "monitoring cost",
  "observability pricing", "metadata monitoring"), to see if more people confirm it.
