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

- Inspect Render request/runtime logs for the historical timeout and establish
  its cause before claiming Phase 1 is closed.
- Review and run the rollback workflow in CI, including Render restoration;
  local tests do not demonstrate a production rollback.
- Run configured hidden controls against the candidate runtime.
- Merge/deploy only after required checks; record the first post-deploy
  snapshot here. No deployment or post-deploy snapshot exists for this draft.
- Phases 2–6 remain pending in the requested order.
