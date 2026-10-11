# Post-deploy score determinism — reproduction not established

Status: blocked at reproduction, not a fix and not accepted for deployment.
Fresh branch `fix/post-deploy-score-determinism` starts at main `5b8ac54`, after
#218 and #219. No content from #220 was used. Only tests and this report change.

## Historical observation

Public snapshot `9b8e9be` records candidate `fcd986b2d09b3548` at cycle 2914:
score 85, raw_gate_pass true, no missing codes and post_deploy_pass_ignored true.
The snapshot actually reports 16 sources and 13 independent domains. The fixture
uses 15 sources / 12 independent domains, 145 evidence-memory rows, and two
cached competitor price receipts, all under reserved `.invalid` domains.
It does not claim to reconstruct that candidate's private evidence.

## Production path exercised

1. Run `cloud_mcp.director_run` with fixed external service replies until the real
   candidate telemetry callback. Evidence quality, cached-price reconstruction,
   opportunity scoring and gate hysteresis are not mocked. A sentinel stops
   execution after scoring, before unrelated build or outreach actions.
2. Increment the completed-cycle counter as the autopilot does. Invoke the real
   `_checkpoint_state_to_render`, with only the Render HTTP transport replaced
   by an in-memory receiver. Incompressible ephemeral history exceeds the real
   75,000-byte compaction trigger. Evidence externalization, compaction, codec,
   checkpoint size convergence and chunk verification run unchanged.
3. Load the captured checkpoint and external evidence chunks through the real
   `_restore_state`, in a clean directory. This executes state recovery selection,
   supplementary merge, external-store hydration, migrations and
   `_merge_state_payload`. Verify 145 evidence rows and byte-equivalent price
   receipts survive. No newer cycle floor is supplied in this controlled case.
4. Run the real director scoring path with a new commit identity and the same
   external replies. Assert first_cycle_after_deploy is true, and compare every
   requested field with zero tolerance.

`startup_guard.py` checks the hidden control before exec'ing cloud_mcp; it does
not rewrite commercial scoring state. The investigation neither invokes nor
modifies that hidden control. `_restore_state` runs on cloud_mcp import and is
explicitly rerun with the fixture for the test. Full autopilot scheduling and
uncontrolled live network replies are deliberately outside this offline test.

## Measured field comparison on unmodified production code

| Field | Valid cache before / after | Contextless cache before / after |
|---|---|---|
| score | 85 / 85 | 35 / 35 |
| monetization_score | 85 / 85 | 35 / 35 |
| raw_gate_pass | true / true | false / false |
| competitors_with_real_price | 2 / 2 | 0 / 0 |
| dissatisfaction | 2 / 2 | 2 / 2 |
| documented_gap | 2 / 2 | 2 / 2 |
| missing_codes | [] / [] | both price and monetization codes / same |

The contextless-cache case also passes with reversed source/cache order.
The separate missing-price test confirms `two_competitors_with_real_price` and
`monetization_score_60` are present and raw_gate_pass is false after restore.
Every field comparison is printed as FIELD_DIFF in the test output.

There is **no valid red reproduction of 35 -> 85**. The tests pass before any fix.
This does not prove the historical defect absent: it means this fixture and
controlled external inputs do not reproduce it. No artificial state mutation or
incorrect expected score is presented as a reproduction. Per the requested
stop condition, no runtime fix or deployment has been attempted.

## Findings, not an identified root cause

References below are to the branch base `5b8ac54`:

- `state_compaction.py:18-29` protects commercial_price_evidence.
- `cloud_mcp.py:536` includes the cache in the checkpoint; `:682-685` restores it.
- `price_validation.py:247-264` reconstructs cached results from URL, domain and
  price_context. This transformation runs on ordinary cycles too; it is not
  specific to restart. Loss of relevance in a short cached context is not by
  itself evidence of a restore defect.
- `cloud_mcp.py:9951-9967` appends those cached results every cycle.
- `cloud_mcp.py:10236-10244` scores current web/scout/SETI inputs, not merely
  commercial_evidence_memory or the previous stored score. Equal evidence-memory
  counts do not establish equal scoring inputs.
- `tool_opportunity.py:605-610` assigns up to 50 points for two real-price
  competitors. That component can explain a 35/85 difference arithmetically,
  but the historical private price inputs are needed to establish causation.
- `tool_opportunity.py:654-669` already rejects missing price data and emits
  both relevant missing codes. No permissive missing-price fallback was found
  on this exercised path.
- `cloud_mcp.py:10248-10271` leaves the post-deploy guard active. A legitimate
  raw pass at 85 remains ignored on the first post-deploy cycle; that fact alone
  is not a score divergence.

`git diff a75b57e..5b8ac54 -- tool_opportunity.py price_validation.py
startup_guard.py state_recovery.py` is empty.

## Missing evidence and next step

The historical deployment run 37799354906 exposes only a Pathwren response
artifact, not a private checkpoint. Heartbeat run 37799805557 has no artifacts.
The public snapshot exposes aggregate scores and fingerprints, not the scoring
receipts or complete price cache. No matching historical private checkpoint or
raw-result archive was found in the checked repository/workspace.

To reproduce the historical transition, obtain a private/anonymized capture of
both scoring inputs around cycle 2914: checkpoint plus price cache, web_research
with query_meta, demand_evidence and SETI catalog. Alternatively collect those
inputs prospectively in a separately reviewed observation change. Do not publish
raw URLs, private text, credentials or hidden-control cases in the PR.

Do not change thresholds, gates, replace_evidence_memory, or the post-deploy guard
to force a reproduction or satisfy acceptance. No paid provider was called.

## Verification and acceptance status

Python 3.12.14, targeted investigation on unmodified runtime:

```
3 passed, 1 warning, 2 subtests passed in 1.35s
```

Full suite:

```
974 passed, 1 warning, 704 subtests passed in 41.66s
```

The warning is the existing Starlette async-generator lifespan deprecation.
No before-fail/after-pass pair exists, so none is claimed. Production acceptance:
**0 of 3 deploys**; no deploy or rollback was performed for this task. The three
accepted ingestion cycles from #219 are not three score-determinism deployments.
