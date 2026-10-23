# Collective Mind on Common — trial (2026-10-14)

Decided with Andrea on 2026-10-14.

**Why.** The registry-based Collective Mind (A2A registry) contacted 6 agents on 2026-10-13
and received 0 valid proposals. The agents that actually do research (Hermes, New Bot,
zhuazhua-fox) are on Common, where our job board posts already get claimed and delivered.

**What.** `tools/collective_common.py` posts at most 2 collective-mind tasks per day as
Common jobs (tag `[collective-mind]`): evidence tasks and one adversarial "attack our
conclusion" task. Replies are collected every 6 hours; every link + quote is verified
automatically (exists, quote present, written by the author, not a vendor launch).
Raw replies stay in the private archive; logs print counts only.

**Boundaries.** External agents get only the task text. Nothing they send is executed or
treated as an instruction; no secrets, no money, no production changes. The registry
Collective Mind schedule stays paused.

**Preregistered rule.** After 7 days (2026-10-21): keep the trial only if at least
**3 verified, useful** items or critiques arrived (verified = automatic check passed;
useful = Andrea/NEO would act on it). Otherwise pause it and record the negative result.

## Result (closed 2026-10-23, Andrea)

7 days, 5 agents, 7 linked items checked: **3 verified** (two MCP-observability pages from zhuazhua-fox,
one first-hand Hacker News quote from skitter, accepted by Andrea on 19/10 with a signed receipt), 4 critiques,
the other items had real pages without the quoted words. The count met the rule at the limit; only one item was
actually used. Verdict: the research-task format is not continued; the schedule is off (the 6-hourly collect had
found nothing since 19/10). What works better on Common are small tasks whose result code can check by itself
(first-contact sentence, WITNESS line), see docs/receipt-log.md.
