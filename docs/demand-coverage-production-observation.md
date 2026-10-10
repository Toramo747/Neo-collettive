# OXIBAY: bounded demand-retrieval coverage (observation only)

Production's normal router retrieves at most three HN results per source, and six overall per query. The public four-week `file access` experiment demonstrated that these caps can hide lexically relevant threads: 9 screened threads in the first-30 window and 22 in the expanded same-window sample. This is NOT evidence of 22 real buyers or a measured increase in market demand.

This change applies the finding by **measuring research coverage without changing any commercial decision**:
- `demand_research_coverage.py` runs **one** HN Algolia public query with up to **60** source results, at most **once every 12 director cycles**. No paid providers, retry loop, new account, API key, extra LLM, external outreach or scraping of private content.
- One 7-second bounded request on an existing research term, executed after the regular collection. Failure and missing source counts fail closed. Provider `exhaustiveNbHits=false` means coverage is incomplete even if `nbHits == len(hits)`.
- The shadow metric reports unique-thread lexical relevance within the first three versus up to 60 results. It never calls those observations demand, buyers, revenue or sales; actual human relevance remains unverified.
- The aggregate is included in the director result under `demand_coverage_observation`. It contains NO content, URLs, source IDs, requester identities, or raw search string. It is not durable commercial evidence, and has no influence on monetization, candidate status, scoring, hysteresis or guard predicates.
- The public snapshot projection requires an explicit separate privacy allowlist before this diagnostic is published; thus it remains internal and does not enlarge existing public outputs.

Cost: free HN public endpoint. Load: one extra capped request every 12 cycles, no increased commercial retrieval limit. Rollback: revert the integration commit/PR and redeploy prior main; no stored-data migration. If runtime latency regresses, stop/revert; do not raise commercial thresholds.

**Acceptance**: CI including privacy and 6/6 controls, source-relevance and bad-provider tests, verify no gate-score diffs with synthetic frozen inputs; then review and explicit merge/deploy approval. This isolated PR is not an authorization to merge the still-draft IPD #242.
