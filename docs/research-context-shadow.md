# OXIBAY – public HN thread-context shadow audit

Scientific purpose: probe **context confounding** of buyer/seller heuristics on two preselected, public August 2026 HN discussion types. The titles are the only public source descriptors committed; no HN user IDs, story IDs, comment IDs, raw excerpts or URLs enter source or GitHub Actions reports.

Contexts:
- Employment supply: "Ask HN: Who wants to be hired? (August 2026)" – includes people offering their work, not demand evidence merely because they say "I need" or mention paid work.
- Mixed project showcase: "Ask HN: What are you working on? (August 2026)" – has vendor showcase, but may also contain genuine unmet needs. **Do not blanket exclude.**

The query looks up both August story titles, fetches at most 60 public comments per context in 2 more requests (max 4 requests total), and immediately reduces to counts: relevance heuristics buyer voice, known commercial family, vendor/supply, and review-priority context flags. Exact match must identify one public story, else the result fails closed. No exact prior PR232 matched-case replay exists.

All results are **exploratory, not human-labelled true/false positives or commercial evidence**. The shadow priority flags are neither automatic exclusions nor replacements for the existing classifier. Reviews by two independent humans remain needed. No performance claim, no new search gamete, no classifier mutation, no thresholds, no paid API, no deploy and no commercial gate influence. All real raw content is transient within the Actions job and is never persisted or uploaded; only anonymized aggregate report is retained for 14 days.

The deliberate thread-type selection prevents any population recall/precision estimate, and public search index changes may limit replicability.
