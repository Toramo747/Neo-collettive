
## Production trial (PR prepared 2026-10-13, awaiting Andrea's authorization)
Change: `_hn_query_search` searches comments, 10 per request (was stories, 3), and each comment links
its own item so different people in one thread are not collapsed. Kill switch without code change:
`NEO_HN_RETRIEVAL_MODE=story`. No gate, threshold or scoring change.
Baseline before the trial (private snapshot 2026-10-11): HN rows in evidence memory 14 of 236,
gate-eligible HN rows 3. Trial check after 3 days: HN rows and gate-eligible HN rows in evidence
memory, and teacher-confirmed demand among them; the trial is kept only if gate-eligible HN rows
grow and qualified-candidate noise does not (judged by reading the rows).
