# Production HN retrieval — shadow test (preregistered 2026-10-11)

Question: production asks Hacker News for the bare seed, stories only, 3 hits, usually with no time window. Would a cheap change (same number of requests) retrieve more real demand?

Judge: maestro teacher v1 (threshold 0.5), with the production lexicon as second opinion. Topics: 4 arena training topics, 4 holdout topics, first term of each of the 25 NEO families (32 unique). Same run, same moment, one request per topic per arm.

| Arm | Tags | Hits | Window |
|---|---|---|---|
| PROD (current) | story | 3 | none |
| STORY10 | story | 10 | none |
| ALL10 | story + comment | 10 | none |
| COMMENT10 | comment | 10 | none |
| ALL10_45D | story + comment | 10 | 45 days |
| ALL30_45D | story + comment | 30 | 45 days |

Decision rule (fixed before the first run): recommend an arm for a production trial only if, in 3 runs on different days, it finds at least 2x PROD's teacher-demand hits, its teacher precision is not lower than PROD's by more than 0.05, and it covers at least as many topics with some demand. Any production change is a separate, authorized PR (shadow first, no gate change).

## Runs
| Run | Arm | Hits | Teacher demand | Teacher precision | Topics with demand (of 32) | Lexicon signals |
|---|---|---|---|---|---|---|
| 1 (2026-10-11 10:4x UTC) | PROD | 94 | 6 | 0.064 | 5 | 11 |
| 1 | STORY10 | 311 | 41 | 0.132 | 22 | 37 |
| 1 | ALL10 | 320 | 82 | 0.256 | 31 | 89 |
| 1 | **COMMENT10** | 320 | **91** | **0.284** | **31** | **103** |
| 1 | ALL10_45D | 277 | 77 | 0.278 | 28 | 73 |
| 1 | ALL30_45D | 705 | 185 | 0.262 | 28 | 195 |

Run 1 reading: with the same 32 requests, comments instead of stories multiply demand found by ~15x (6 → 91) and raise precision (0.06 → 0.28); production currently finds demand for 5 of 32 topics, comments for 31. Teacher and lexicon agree on the direction (lexicon 11 → 103), so this is not only a teacher bias (the teacher saw HN comments among its positives). COMMENT10 passes the rule in run 1; runs 2 and 3 pending.
