# Matched baseline replication v3

The prior v2 shadow holdout found baseline 0 and evolved 3 valid HN signal threads; evolved precision was only 5.56% (3/54). The original baseline used long full topic strings and produced just one relevant result. This leaves substantial query-width confounding.

Pre-registered challenge: two topic-disjoint four-topic panels, each with three arms (exact original, compact matched topic-first, compact evolved signal-first), four suffixes per topic, 16 queries per arm and panel, and shared HN Algolia, 45-day cutoff and response limits. The primary claim compares evolved to compact matched, not to the sparse original baseline.

Verdict requires +2 unique signal threads, no worse precision, two topics with signals, and at least eight relevant hits in the matched control. Otherwise do not claim improvement. Both panels run on one date, one service and one classifier, so they are NOT separate time/source replications. Validated independent rounds remain zero. Synthetic controls only confirm code paths; no human review has occurred. The exact three threads from v2 cannot be individually authenticated using its aggregate artifact, which intentionally omitted source IDs and raw text.

Only public HN read-only requests, no paid APIs or secret/data access, no production mutation, merge, deployment, promotions or commercial policy changes. Artifacts contain aggregate counters without HN IDs, URLs or original text.

Run plan without network: python experiments/research-replication-v3/replicate.py
Run explicit read-only comparison: python experiments/research-replication-v3/replicate.py --execute

Human review of buyer authenticity remains necessary before any commercial statement.