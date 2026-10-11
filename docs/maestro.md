# Maestro (teacher genome) — plan and phase 1 (preregistered 2026-10-11)

Goal: a teacher that learns, from public traces where people **proved** a need for a software tool, to recognise real demand; it then becomes the fitness of the arenas instead of keyword rules. Isolated arena: no production read/write, manual promotion only, zero cost.

## Sources (chosen with Andrea)
Public, free, official APIs; terms allow automated use; counts and public text only.
| Source | Natural label |
|---|---|
| Stack Exchange `softwarerecs` | explicit "recommend me software for X" question |
| GitHub issues | `label:bounty` (money), `reactions:>=10` (repeated demand) |
| Hacker News (Algolia) | Ask HN on the topic; comments with "would pay" + topic |
| RemoteOK | current paid jobs mentioning the topic (snapshot, not 6 months) |
Excluded for now: Reddit (API approval pending, #35), Upwork/Fiverr (terms), Product Hunt (token, phase 2), review sites and generic forums (opinions without proof).

## Scope
All 25 NEO commercial families (`evidence_integrity.FAMILY_TERMS`), first 2 terms each. In phase 2 families are split into learn / never-seen exam groups.

## Phase 1 — census (does enough proof exist?)
Counts per family and source over 182 days. Counts are search totals: upper bounds, may overlap.
**Viability rule (fixed before running):** at least 1000 natural labels in total **and** at least 15 of 25 families with 30 or more. Otherwise the idea stops here and is recorded as not viable with these sources.

## Next phases (only if phase 1 is viable)
2. Historical dataset: posts from 6–12 months ago, labelled by later proof; teacher trained and tested on unseen periods and families.
3. Calibration against Andrea's 768 labels; hidden 6/6 control stays an exam the teacher never sees.
4. Teacher becomes arena fitness; frequency raised only then.
5. Weekly refresh with new outcomes.

## Results
