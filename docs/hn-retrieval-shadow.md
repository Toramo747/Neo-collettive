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
