# Maestro (teacher genome) — plan and phase 1 (preregistered 2026-10-11)

Goal: a teacher that learns, from public traces where people **proved** a need for a software tool, to recognise real demand; it then becomes the fitness of the arenas instead of keyword rules. Isolated arena: no production read/write, manual promotion only, zero cost.

## Sources (chosen with Andrea)
Public, free, official APIs; terms allow automated use; counts and public text only.
| Source | Natural label |
|---|---|
| Stack Exchange `softwarerecs` | explicit "recommend me software for X" question |
| GitHub issues | `label:bounty` (money), `reactions:>=10` (repeated demand) |
| Hacker News (Algolia) | Ask HN on the topic; comments with "would pay" + topic |
| RemoteOK | current paid jobs mentioning the topic (snapshot, not 6 months) |
Excluded for now: Reddit (API approval pending, #35), Upwork/Fiverr (terms), Product Hunt (token, phase 2), review sites and generic forums (opinions without proof).

## Scope
All 25 NEO commercial families (`evidence_integrity.FAMILY_TERMS`), first 2 terms each. In phase 2 families are split into learn / never-seen exam groups.

## Phase 1 — census (does enough proof exist?)
Counts per family and source over 182 days. Counts are search totals: upper bounds, may overlap.
**Viability rule (fixed before running):** at least 1000 natural labels in total **and** at least 15 of 25 families with 30 or more. Otherwise the idea stops here and is recorded as not viable with these sources.

## Next phases (only if phase 1 is viable)
2. Historical dataset: posts from 6–12 months ago, labelled by later proof; teacher trained and tested on unseen periods and families.
3. Calibration against Andrea's 768 labels; hidden 6/6 control stays an exam the teacher never sees.
4. Teacher becomes arena fitness; frequency raised only then.
5. Weekly refresh with new outcomes.

## Results
### Phase 1 run 2026-10-11 (Actions run 38118770209)
By source (182 days): softwarerecs 16, GitHub bounty 732, GitHub reactions>=10 1118, Ask HN 4659, "would pay" comments 416, RemoteOK (snapshot of 99 jobs) 128. **Total 7069; 17/25 families >= 30 → viable by the preregistered rule.**

Honest reading:
- Ask HN is the weakest label (an explicit question, not a proof) and is 66% of the total. Without it: 2410 labels, **14/25** families >= 30, just below the threshold. Money-only labels (bounty, "would pay", jobs): 1276, 10/25 families.
- Coverage is uneven: integration/API, AI tools, CRM, developer tools, spreadsheets, support, data cleanup are rich; finance ops, local business, education, micro-SaaS, creator and content tools have almost nothing.
- Some counts look inflated by loose matching (CRM: 2875 Ask HN, 275 "would pay"): counts are search totals and upper bounds; label precision must be measured on a sample before training.
- Stack Exchange softwarerecs is almost empty for these terms (16): low value, candidate for replacement.

Proposal (pending Andrea): proceed to phase 2 on the label-rich families only, starting with a precision check on a sample of each label type.

### Phase 2a — precision check (2026-10-11, sample of 100, seed 20261011)
Seeded random sample, 20 per label type, from the 14 label-rich families; texts stored only in the private archive (`maestro/maestro-sample-20261011T064953Z.jsonl`). Annotation by Claude with one rubric: *does a person or organisation show a need for a software tool or feature in the matched family?*

| Label type | Real demand | Main failure |
|---|---|---|
| GitHub `label:bounty` | 0/20 | agent/crypto bounty farms, mirrored bounty boards, internal project tasks |
| GitHub reactions >= 10 | 3/20 | bug reports on big products; family term matched somewhere in long bodies |
| Ask HN | 1/20 | sellers presenting products, opinion threads |
| HN "would pay" | 1/20 | phrase present 20/20, but almost always "companies would pay…" in unrelated debates |
| RemoteOK | 0/20 | job ads for roles; substring artefacts ("excel" in "excellent") |
| **Total** | **5/100** | |

Automatic lexical check: the family term appears in the stored text in only 4/20, 4/20, 9/20, 2/20, 0/20 items.

**Conclusion: the phase 1 "viable" verdict does not hold.** At about 5% precision the 7069 counts correspond to a few hundred real labels, spread thin. The idea is not dead, but these label definitions are noise.
Signals worth keeping: first-person "I would pay for this" replying to a concrete product, and feature requests with many reactions on tool repositories (demand to *improve* existing tools, which is part of NEO's mission).
Next step if approved: strict label definitions (first-person pay/tool-seeking patterns, product-context replies, bounty-farm exclusion, whole-word matching), new sample, same rubric; viability re-judged only on measured precision.

### Phase 2b — strict labels (2026-10-11, seed 20261012)
Same rubric, now family-agnostic (need for a software tool or feature). Sample in the private archive (`maestro-sample-v2-20261011T065709Z.jsonl`).

| Label type | Pool (6 months, capped at 3 pages per query) | Real demand in sample |
|---|---|---|
| HN first-person willingness to pay | 134 | 6/20 (software; the other "pay" items are hardware, food, rhetoric) |
| HN explicit tool seeking | 37 | 11/20 |
| GitHub titled feature requests, >= 20 reactions | 0 | — (query too strict) |
| **Total** | | **17/40 = 42%** (phase 2a: 5%) |

Findings:
- Strict, first-person definitions raise precision about 8x. Precision problem solved in principle.
- Volume is the new limit: at this precision the pools give roughly 70 real labels in 6 months, below what a teacher needs. Pools were capped (3 pages per query) and can be widened.
- None of the 171 pooled items mention a NEO family term as a whole word: real expressed demand on HN is about consumer and developer software, not the B2B workflow families NEO targets. This is a finding about NEO's scope, not only about the teacher.
- Best signals: replies under "Show HN" ("I was looking for an app like this", "I would happily pay a one-time price") — demand attached to a concrete product.

Proposal (pending Andrea): widen the strict pools (more pages and phrase variants, GitHub feature requests with relaxed reaction threshold) and re-measure volume at fixed precision before any training.

### Phase 2c — widened strict pools (2026-10-11, seed 20261013)
More phrase variants, up to 20 pages per query, two new label types. Sample of 95 (pools smaller than 20 sampled whole).

| Label type | Pool (6 months) | Real demand in sample | Estimated real labels |
|---|---|---|---|
| HN first-person pay (12 phrases) | 187 | 3/20 | ~28 |
| HN tool seeking (12 phrases) | 49 | 6/20 | ~15 |
| HN product validation under Show HN | 67 | 15/20 | ~50 |
| GitHub feature requests, term in title, >= 5 reactions | 15 | 14/15 | ~14 |
| Stack Exchange softwarerecs (all questions) | 83 | 20/20 | ~83 |
| **Total** | **401** | **58/95 = 61%** | **~190** |

Findings:
- Widening the phrases added little volume and some noise ("take my money", "pay good money" are mostly rhetoric): first-person pay fell to 3/20. Keep the original strict phrases only.
- The precise sources are the ones where demand is structural: product validation under Show HN (75%), GitHub feature requests (93%), softwarerecs (100% by construction).
- GitHub feature requests are the only source that lands inside NEO's B2B families (CRM, integrations/webhooks, AI tools, knowledge management): it is the natural candidate for the families HN does not cover.
- Volume is still the limit: ~190 real labels in 6 months.

Levers for volume (proposal): (1) extend the window to 3 years — labels are historical by design; (2) GitHub feature requests with >= 5 reactions on all repositories, family assigned afterwards, instead of family term in the title; (3) drop the noisy pay phrases.

### Phase 2d — three-year pools (2026-10-11, seed 20261014)
Window 3 years; only the precise label types; GitHub feature requests on all repositories (36 monthly windows, 300 per month, sorted by reactions; GitHub reports 56,472 matching issues in total). Pools and a 100-item sample in the private archive (`maestro-pool-v4-20261011T071419Z.jsonl`).

| Label type | Pool (3 years) | Real demand in sample | Estimated real labels |
|---|---|---|---|
| HN first-person pay | 871 | 4/20 | ~170 |
| HN tool seeking | 315 | 13/20 | ~200 |
| HN product validation under Show HN | 353 | 16/20 (one "I'm going to buy it") | ~280 |
| GitHub feature requests, >= 5 reactions | 8,621 | 19/20 | ~8,200 |
| Stack Exchange softwarerecs | 1,370 | 20/20 | ~1,370 |
| **Total** | **11,530** | **72/100** | **~10,200** |

**Volume solved: about 10,000 real demand labels at 72% sample precision.**

Limits to carry into phase 3:
- Skew: GitHub dominates (80%) and is mostly developer and AI tooling. Only 208 items match a NEO family term (the 2-term family matcher is too narrow); B2B workflow families remain under-represented.
- Strength: feature requests and tool requests show need, not payment. Explicit willingness to pay is ~170 labels (the noisiest type). The teacher will learn "real need for a software tool"; "will pay" stays a separate, small signal.
- Only positives so far: training needs matched negatives from the same sources (ordinary comments, bug reports, questions without tool seeking).

Proposal (pending Andrea): phase 3 — dataset with matched negatives, a light classifier trained on years 1–2 and tested on year 3, then calibration against the 768 private labels before any arena use.

### Phase 3 — first teacher (2026-10-11)
Dataset: positives from the 3-year pools, negatives from the same sources and period (random HN comments, GitHub bug/question issues with >= 5 reactions, superuser how-to questions), balanced per source. Selection phrases and issue-template words masked in both classes; HN story titles excluded. TF-IDF + logistic regression, trained on items older than 12 months (8,850), tested on the last 12 months (4,150). Baseline on the same test: production lexicon primitives.

| Test (last 12 months) | Teacher AUC | Teacher P / R / F1 | Lexicon P / R / F1 |
|---|---|---|---|
| Hacker News (most comparable: same source, random negatives) | 0.787 | 0.71 / 0.73 / 0.72 | 0.72 / 0.17 / 0.27 |
| GitHub | 0.972 | 0.95 / 0.88 / 0.91 | 0.72 / 0.52 / 0.60 |
| Stack Exchange | 0.973 | 0.93 / 0.92 / 0.92 | 0.68 / 0.58 / 0.63 |
| All | 0.942 | 0.89 / 0.85 / 0.87 | 0.71 / 0.44 / 0.55 |

First run (before stronger masking) had HN AUC 0.841 with "show hn", "shut up", "looking for" among the top terms: leakage, fixed; the table above is the cleaned run.

Reading:
- HN is the honest number: at the same precision as the lexicon, the teacher finds 4x more real demand (recall 0.73 vs 0.17).
- GitHub and Stack Exchange scores are inflated by style differences between the classes (feature request vs bug report, softwarerecs vs superuser): partly a real distinction, partly source style. Not to be taken at face value.
- No Show HN negatives were collected (0): product-validation positives are compared only with random comments; a confound to remove.
- On the 768 NEO observations the teacher flags 57% as demand, against a few percent for the lexicon judge: likely domain shift (74% of them are GitHub issues). Cannot be judged without human labels.

Correction: the 768 records in `train.jsonl` are unlabelled observations (final_label empty; 5 auto-labels). There is no human-labelled calibration set outside `hidden.jsonl`, which is reserved and never opened. Calibration therefore needs a small set labelled by Andrea.

### Phase 3b — calibration on NEO's own observations (2026-10-11)
Andrea asked Claude to act as trainer. Calibration set: 100 NEO observations from `train.jsonl` (seed 20261016), labelled by Claude with the archive's 5 labels, stored as `maestro/maestro_calibration_claude.jsonl` with `label_origin: claude` (not human; `hidden.jsonl` untouched). Result: 9 buyer_tool_search, 16 vendor_offer, 2 job_posting, 73 other.

| Teacher version | HN F1 (web test) | Calibration AUC | Calibration P / R / F1 at 0.5 | at 0.8 | Lexicon P / R / F1 |
|---|---|---|---|---|---|
| 3a (random negatives) | 0.73 | 0.814 | 0.15 / 0.89 / 0.26 | 0.40 / 0.44 / 0.42 | 0.28 / 0.89 / 0.42 |
| 3b (+769 seller posts as negatives) | 0.77 | 0.805 | 0.13 / 0.78 / 0.23 | 0.60 / 0.33 / 0.43 | 0.28 / 0.89 / 0.42 |

Reading:
- On its own domain (web posts) the teacher is clearly better than the lexicon; seller negatives improved it further (HN F1 0.73 → 0.77).
- On NEO's real input it is **not better than the lexicon yet**: it still flags 11/16 vendor pages and 34/73 other items. NEO's stream is made of genres the teacher never saw: SEO articles and listicles, spam issues ("Best X company in Y"), internal project tasks on GitHub.
- The calibration set has only 9 positives: every figure here is noisy.

Next (proposal): Claude labels the remaining 668 NEO observations; the teacher is retrained on web labels + in-domain NEO labels and tested on the 100 calibration items, which stay out of training.
