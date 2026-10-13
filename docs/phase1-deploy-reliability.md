# Phase 1 — partial repair, not yet released

## Observed failure

Run 37739657754, job 113187175785, deployed commit
0172177c68e230f22f470cf877585aa80970d83b (PR #214).
At 2026-10-08 06:51:17 UTC the Arena smoke reported exactly:

```
curl: (28) Operation timed out after 30003 milliseconds with 0 bytes received
Process completed with exit code 28.
```

The log does not identify which of the four requests timed out. PR #214
changes challenge decision telemetry and its public projection, not Arena
handlers or the deploy workflow. This rules out a direct edit to those
components, **not** an indirect runtime effect. Root cause remains open;
no timeout increase or speculative Arena runtime fix is included.

Rollback was skipped because main advanced to e5ab43f. That commit changed
only neo_latest_result.json and neo_cycle_floor.json. The old workflow
compared SHA equality, and would also have used an invalid plain revert
on the PR merge commit (it needs mainline parent 1).

## Changed files and reason

- `.github/workflows/neo-render-deploy.yml`: capture the actual previous
  production commit before deploying; restore it through the existing Render
  hook and verify its SHA before reverting main; allow snapshot-only advances;
  handle merge commits; place snapshot dispatch after SETI readiness; identify
  each Arena request in future failure logs. Full git history is needed for
  per-commit checks. The job budget includes time for rollback.
- `scripts/deploy_rollback.py`: inspect every intervening commit against the
  exact snapshot path allowlist, rather than just comparing heads or net diff.
- `cloud_mcp.py`: add `Cache-Control: no-store` to successful and rate-limited
  health responses; live health previously had no cache directive.
- `test_deploy_rollback.py`, `test_deploy_health.py`: exercise snapshot-only,
  mixed, reverted application changes, and health cache behavior.

## Validation before publication

```
Deployment regression suite: Ran 533 tests in 9.424s — OK
Focused rollback/health/workflow tests: Ran 30 tests — OK
Public commercial controls: 24/24; family mapping: 24/24
Public challenge controls (existing evaluator): 12/12
YAML parse and bash -n on every workflow run block: OK
Historical e5ab43f advancement: rollback_allowed = True
git diff --check: clean
```

Commercial thresholds, requirements and gate codes are unchanged. Existing
privacy and commercial non-regression tests are part of the green suite.
The existing challenge control does not yet validate the new Phase 2 contract.

Historical hidden commercial result: 6/6 at the failed deploy. Hidden challenge
result: required=false, cases=0. This is **not** a hidden-suite pass for this PR.

## Outstanding before completion

- Render logs inspected below: process-wide stall strongly supported; the
  responsible synchronous function is not identified. Do not claim closure.
- Review and run the rollback workflow in CI, including Render restoration;
  local tests do not demonstrate a production rollback.
- Run configured hidden controls against the candidate runtime.
- Merge/deploy only after required checks; record the first post-deploy
  snapshot here. No deployment or post-deploy snapshot exists for this draft.
- Phases 2–6 remain pending in the requested order.


## Read-only Render investigation — 2026-10-08

Service: Neo-collettive in the user-confirmed My Workspace. No environment
variable endpoint was read. No settings, deploys, restarts or rollbacks were
requested. PR #215 remains draft, with no merge/deploy.

### Timeline (UTC)

| Time | Evidence |
| --- | --- |
| 06:48:23 | GitHub deploy job starts (not Render build start). |
| 06:49:16.749 | Render build_started / deploy_started. |
| 06:49:46.645 | Render build_ended, succeeded (29.896 seconds). |
| 06:50:21.529 | New instance bnnlw: Started server process [1]. |
| 06:50:22.024 | New instance: Application startup complete. |
| 06:50:31.725 | New instance: GET /livez 200. |
| 06:50:32.699 | Old instance ctlpn starts normal shutdown. |
| 06:50:33.226 | Render deploy_ended, succeeded. |
| 06:50:33.432 | Render: Your service is live. Exact load-balancer switch timestamp is not exposed; these events bound the transition. |
| 06:50:37.127 | New instance answers workflow GET /health; Actions verifies commit 0172177. |
| 06:50:45.175 | GitHub Arena smoke step begins. |
| 06:50:45.875 | GET /arena 200. |
| 06:50:46.931 | GET /arena/neo-dialect 200. |
| 06:50:47.530 | GET /arena/micelio 200. |
| approximately 06:50:47.628 | /arena/evoluzione request starts, inferred from curl timeout timestamp minus its reported 30.003 seconds. |
| 06:51:14.428–14.430 | Six /livez responses complete within 3 ms, following a 27.495-second gap since 06:50:46.932. |
| 06:51:17.631 | curl timeout: 30003 ms, zero received bytes. |
| 06:51:18.324 | GET /arena/evoluzione 200, about 30.70 seconds after inferred request start, 0.69 seconds after client timeout. |

Sanitized relevant application lines (IP addresses omitted):

```
06:50:22.023572952 Application startup complete.
06:50:31.725478630 GET /livez 200 OK
06:50:47.530498552 GET /arena/micelio 200 OK
06:51:14.427581705 GET /livez 200 OK
06:51:14.428150407 GET /livez 200 OK
06:51:14.428779841 GET /livez 200 OK
06:51:14.429413115 GET /livez 200 OK
06:51:14.429968787 GET /livez 200 OK
06:51:14.430334095 GET /livez 200 OK
06:51:18.323608504 GET /arena/evoluzione 200 OK
```

### Resource samples

Render metrics at 30-second resolution; finer 15-second resolution is rejected
by the connector. CPU is measured in cores, not percent. Quota: 0.15 core.

| UTC | CPU cores | Fraction of quota | New-instance memory MiB |
| --- | ---: | ---: | ---: |
| 06:50:30 | 0.0095886 | 6.4% | 100.20 |
| 06:51:00 | 0.1214932 | 81.0% | 142.64 |
| 06:51:30 | 0.1413705 | 94.2% | 143.70 |
| 06:52:00 | 0.076627366 | 51.1% | 175.55 |

Memory limit: 512 MiB. No server_failed/server_restarted/OOM event occurs in
06:48–06:53. Old instance shuts down normally and new instance continues with
the same ID throughout. These are sampled measurements, not an instantaneous
peak trace.

### Causal assessment and limits

- (a) is not supported: startup and traffic handover had completed, with many
  successful requests on the new instance before the timeout.
- (d) is not supported: no OOM/restart event, memory well below the limit.
- The simultaneous delay of /livez supports an event-loop/process-wide stall,
  not just slow asynchronous network I/O for an Arena response.
- (c) is the leading explanation, **not a proven attribution to autopilot**.
  The workflow's autonomy result reports running=true and cycle start at
  06:50:21.623. director_run executes synchronous evidence evaluation and state
  serialization in the shared event loop. No trace identifies which function
  was running during the stall, however.
- (b) is not conclusively ruled out. On the local test runtime with the deployed
  repository files and network fetch mocked to local file reads, parse+render
  takes 0.0102 seconds for micelio and 0.0045 seconds for evoluzione; output sizes
  are 266075 and 179142 bytes. This does not reproduce the 27-second stall and
  is not a benchmark of the constrained Render CPU or its network.
- #214 does not modify Arena handlers or the workflow. Its indirect effect on
  cycle execution cannot be conclusively excluded by these logs.

No speculative cache/thread/archive/timeout change is added. In particular,
serving cached Arena HTML on the **same blocked event loop** would not by itself
make the request responsive. Moving the whole state-mutating cycle into a
thread without an established cause would introduce an unreviewed concurrency
change.

### Current latency availability

Latest retrieved application access log: 07:30:18.891, GET /arena/evoluzione
200. Application logs have completion timestamps but no request duration;
request logs and HTTP-latency metrics for that endpoint return no samples.
The previous turn measured 13.87 seconds for a GET. It is a prior measurement,
not a fresh measurement in this investigation. No new unauthenticated GET was
issued and no authentication key was read/exported to manufacture a signed GET.
A fresh authenticated latency measurement is therefore unavailable here.

### Additional rollback verification

Tests now execute actual git reverts in temporary repositories:

- failed application commit followed by snapshot/Arena-only commits: application
  reverted, latest snapshots preserved;
- newer code commit: no revert and HEAD unchanged;
- failed merge commit: first-parent revert succeeds, cycle-floor snapshot kept.

The workflow invokes the same tested revert function. These tests reproduce
and fix the demonstrated snapshot-advancement rollback defect, not the
unattributed historical event-loop stall. A red/green regression of that stall
cannot truthfully be claimed without identifying its producer.


Final local validation after the additional tests:

```
python -m unittest discover -v
Ran 937 tests in 17.171s
OK
Public commercial: 24/24; family mapping: 24/24
Public challenge: 12/12
Rollback tests: 8/8, including actual reverts
```

The timeout-specific red/green reproduction and fresh authenticated latency
remain unavailable. Phase 1 is therefore not declared complete.
