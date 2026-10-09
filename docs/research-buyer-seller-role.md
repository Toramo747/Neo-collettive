# OXIBAY – Separate seller/buyer actor from buyer-language detection

Prior experiment #239: the one-gene `query_mode=pain` mutation was inferior (4 valid threads vs 6 and lower precision). Do NOT promote it. Source review only reorders inspection, not retrieval. Instead, audit the **role attribution weakness** in the existing HN pipeline.

The current `evidence_integrity.is_vendor_content` and `is_supply_offer` intentionally early-return False for `source="hn-algolia-routed"`, unlike generic search. `seller_voice_present` protects against common phrases including "our app", "we built", but descriptions such as "I offer invoice automation consulting, looking for clients" can still share commercial-family, apparent buyer voice and demand tag words. This experiment adds **shadow-only explicit seller-actor role flags**; it NEVER changes old accepted/rejected classifications, prices, memory, gate or thresholds. Mixed seller/customer narratives must be shown to a human, never silently rejected.

The experiment is preregistered for March 2026, a window not used in recorded May–October HN studies. It reruns the frozen four-topic baseline on exactly sixteen no-cost public HN queries, up to 30 hits each; stores no source text, URLs, IDs or query strings in artifacts. It compares native unchanged `diagnostic_metrics` to the independent existing stage helper from PR #233, then counts and review-queue-prioritizes accepted rows with explicit seller-role cues. Top-8 reviews are evaluated in both original and risk-first order. This is an annotation experiment; identical labels and scores are a required invariant.

Ten **author-written synthetic fixtures** include overt service offers, seller looking for customers, direct buyer needs, hiring a specialist as a buyer and a mixed seller/buyer. Their labels were authored as a diagnostic control, NOT independently human reviewed or used to measure natural accuracy. Real HN role collisions are possible *review priorities*, NOT verified false positives, and cannot justify automatic rejection or gate promotion.

Result interpretation:
- 0 collision flags: the guard offers no measured review coverage in this window; not proof of zero seller confusion.
- >0 collision flags: there are records worth blind independent human review; not a measured decrease in false positives.
- Provider/metric mismatch: INCONCLUSIVE and fail closed.
- Even if the risk-first top-eight queue is better targeted than arrival order, that is not commercial quality improvement without reliable independent human feedback.

External real-world verification, separate provider, at least 2 genuine independent reviewers and at least 3 preregistered replications still required before proposing classifier modifications. No merge or Render deploy.