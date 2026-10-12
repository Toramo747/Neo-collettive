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
