# Context triage trial (September 2026; shadow, not a new production gene)

Original August PR #234 checked a HN job-seeker thread and found 45/60 commercial-family matches and only 4/60 buyer-voice matches, with **no human adjudication**. The proposed hypothesis is that thread-level context may help reviewers interpret candidate signals without discarding genuine requests.

Protocol frozen **before first September query**: two confirmed September public HN titles ("Who wants to be hired?" and "Who is hiring?") and the source tag `show_hn`. The latter replaces the missing August personal-project thread with a reproducible, mixed showcase source type. Five or fewer HN Algolia requests with up to 60 records per group. Only aggregated counts of existing commercial-family and buyer-voice predicates and their overlap are reported. "Buyer-family overlap" is NOT the full scorer's accepted commercial signal and must not be called a proven false positive. No raw data, source IDs or URLs in the stored result.

The experimental `source_context` parameter has **REVIEW_ONLY_NEVER_AUTO_REJECT** policy:
- applicant_offers → prioritize review of likely supplier context
- employer_job_posts → prioritize review of job hiring context, which is distinct from purchasing software
- show_hn_projects → mixed source, possible genuine buyer pain; **no blanket negative**
- unknown/unavailable source → explicit inconclusive, no zero-metric success

Automated tests guard against suppressing showcase content, source-category errors and production mutation. Without independently reviewed human labels the experiment cannot establish false-positive rates, precision improvement, or improved customer discovery. September turns into development data immediately after inspection, so it must not be reused as untouched confirmation. No pricing, commercial thresholds, memory, model/student or Render changes; draft only, no merge, no promotion.