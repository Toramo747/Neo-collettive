
## Production trial (PR prepared 2026-10-13, awaiting Andrea's authorization)
Change: `_hn_query_search` searches comments, 10 per request (was stories, 3), and each comment links
its own item so different people in one thread are not collapsed. Kill switch without code change:
`NEO_HN_RETRIEVAL_MODE=story`. No gate, threshold or scoring change.
Baseline before the trial (private snapshot 2026-10-11): HN rows in evidence memory 14 of 236,
gate-eligible HN rows 3. Trial check after 3 days: HN rows and gate-eligible HN rows in evidence
memory, and teacher-confirmed demand among them; the trial is kept only if gate-eligible HN rows
grow and qualified-candidate noise does not (judged by reading the rows).


## Trial verdict (2026-10-16): NOT kept — default back to `story`
Evidence memory 3 days after the v0.99.56 deploy: HN rows 14 → 19, gate-eligible HN rows 3 → 6.
Reading the rows: the 3 new gate-eligible ones are a "Who is hiring" job ad, a builder showcasing
their own product in "What are you working on", and an opinion comment — none is first-hand demand.
Most other new rows come from "Who wants to be hired" threads (job seekers tagged as buy intent).
Gate-eligible rows grew only with noise, so the preregistered rule says revert. Possible follow-up
(not part of this trial): exclude hiring/self-promotion threads before retrying comment retrieval.
