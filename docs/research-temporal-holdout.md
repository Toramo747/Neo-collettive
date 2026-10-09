# Research Algorithm: preregistered historical temporal holdout

Purpose: try to falsify the claim that g69-elite-1 improves retrieval of validated *machine-classified* demand signals over the exactly matched compact-topic baseline. The previous positive group B is NOT independent validation. The current operational gate, thresholds and student promotion remain unchanged.

## Design pinned before any experiment API calls

- Three time-disjoint archived HN Algolia windows: May, June and July 2026 (start inclusive, end exclusive).
- Same four task topics across windows, chosen before data access. Full labels distinct from evolution and earlier holdouts. Semantic/domain independence from earlier work is not guaranteed.
- Two arms, both using compact query topics, four identical query suffixes, 16 query attempts per arm per window. Only term order changes: topic-first versus signal-first.
- Source HN Algolia only; read-only, public, no API key and no paid services. Up to 96 provider calls and 30 hits per query.
- Per-window fail-closed: all 16 queries succeed in each arm, scorer vs diagnostic valid-signal counts agree, synthetic controls pass, baseline >=8 relevant hits. A positive result requires at least +2 distinct signal discussion threads in >=2 topical categories, and precision not worse than baseline.
- Two of three positive historical windows would support a limited *temporal exploratory* hypothesis. It does not constitute proof: same provider and classifier, archive data only, no independent prospective trial, no reviewed source records, and zero cross-source validation.
- Tests and privacy: source texts, URLs, source identifiers and query texts are not persisted in reports. The author-labelled synthetic control is NOT evidence of customer demand. Validated independent replication counter is fixed to 0.
- Prior v1, v2, v3 runs and adverse/inconclusive outcomes remain unmodified; no data selected based on new run outcomes may be used to retrofit this protocol.
- Any later provider, human validation, or forward-out-of-time collection requires a new preregistered protocol and fresh sources, not selective reruns of these windows.

Run plan without network:
    python experiments/research-temporal-holdout/run.py

Run the fixed read-only experiment:
    python experiments/research-temporal-holdout/run.py --execute

No merge, deploy, price/competitor changes, commercial thresholds, learning/promotions or production memory writes are authorized. The PR stays draft until human review.
