# Commercial decision inputs and private replay

This observation change does not repair the historical post-deploy pass. It does
not change commercial/challenge thresholds, hidden controls, evidence replacement,
or the first-cycle guard. No merge/deploy is part of this task.

## Input inventory

| Input | Producer / reader in production | Capture |
|---|---|---|
| Ordered web results, including fresh price results | `cloud_mcp.director_run`: `_free_web_research`, page enrichment; `tool_opportunity.analyze_tool_opportunities` | Full ordered `web_research` |
| Query attribution and roles | `director_run` constructs `query_meta`; scorer reads family, role, validation_kind | Full dictionary |
| Scout/demand results | `director_run` calls `evidence_scouts`; scorer reads title/text/source/family | `demand_evidence` |
| SETI catalog | `seti_market_catalog(SETI_PRIVATE_STATE.candidates, interviews)` | Materialized catalog, not credentials or unrelated peer state |
| Cached prices | `director_run` reads `AUTOPILOT_STATE.commercial_price_evidence` before appending `persisted_price_groups` | Exact pre-update cache plus its insertion index in web results |
| Fresh price phase | `director_run` obtains `price_groups` and updates the cache for the NEXT cycle | Current fresh groups already in web results; not retroactively added to captured cache |
| Coverage counters | `director_run` reads/updates `market_source_diagnostics`; scorer consumes it | `source_diagnostics` |
| Usage evidence | `endpoint_verifier.usage_metrics_snapshot`; scorer uses it for MCP reliability | One frozen `usage_evidence` value |
| Previous hysteresis | `AUTOPILOT_STATE.gate_stability`; `apply_gate_hysteresis` | Entire previous state: candidates, streaks, windows, fingerprints, domains, context and flips |
| Identity/context | `director_run`: VERSION, DEPLOY_COMMIT, TAGGER_VERSION, RESEARCH_ARENA_PRODUCTION_GENOME.source | Version, commit, tagger, genome, cycle and first-cycle flag |
| Policy / upstream guards | `_load_policy().policy_version`; boolean `*_GUARD_ENABLED` globals | Provenance; upstream effects already materialized in scorer inputs |
| Explicit time | `director_run` captures one UTC `decision_now` | Passed into scorer and hysteresis, stored as `now` |

Evidence memory is **not** the entire decision input. It influences upstream
query planning and evidence quality, but `analyze_tool_opportunities` consumes
web/scout/SETI results directly. The replay boundary is immediately before that
scorer, after upstream work. It does not rerun search, model calls, migrations,
query planning or network requests. The full upstream memory is deliberately not
copied: it is not a direct argument to this scoring boundary.

## Input non dichiarati

- `tool_opportunity`: category configurations and insertion order, relevance and
  signal marker lists, price regex, schema and price requirement constants.
- `price_validation`: regex patterns/flags, marketplace host set, article markers,
  currency mappings and other module constants. Cache reconstruction uses this code.
- `gate_stability`: ENTER_STREAK, EXIT_STREAK, MIN_CONFIRM_SECONDS,
  MIN_CONFIRM_CYCLES, MAX_FLIPS, CONFIRM_FAIL_RESET and CONFIRM_MIN_PASS_RATIO.
  The latter two are initialized from environment variables
  NEO_GATE_CONFIRM_FAIL_RESET / NEO_GATE_CONFIRM_MIN_PASS_RATIO.
- TZ affects interpretation of timezone-naive dates; the environment value is
  captured. Config mismatch is rejected, not silently replayed under new settings.
- PYTHONHASHSEED and set iteration: the seed is recorded. Domains, signal labels
  and fingerprint material already sort their sets; candidate order and first-URL
  wins use ordered lists/dictionaries. Lists and category order are preserved.
- The scorer's `_utc` used to read the clock for invalid source dates. It now
  falls back to the explicitly supplied scoring `now`; valid dates and numerical
  scoring are unchanged. SETI timestamps are already materialized before capture.
- No random generator or network operation is used inside the replay boundary.
- Code itself: commit and a fingerprint of the effective module constants/config
  are recorded. Replay under different code is intentional; configuration mismatch
  is rejected. Use the recorded commit and matching environment for historical replay.

The candidate-telemetry HMAC secret is not a scoring input and is never captured.
Receipts use private family identifiers; no new public candidate identifiers.
The config fingerprint includes no credentials. These are private diagnostic
records, not a general dump of globals, environment variables or process state.

## Output and integrity

Schema v1 records SHA-256 for canonical JSON inputs and outputs. Output includes
the complete scorer return, full updated hysteresis state and stable rows. A
passive observer additionally records exact component counts/points for **all**
configured candidates, before diagnostic source lists are capped: real priced
competitors, dissatisfaction/gap domains, payment/dissatisfaction/gap/trend points
and counter penalty. Candidates outside the existing top-five hysteresis input
have `hysteresis_evaluated=false` and `stable_gate_pass=null`; they are not falsely
reported as evaluated. Raw score/gate and missing codes are captured for all.

The observer does not change the scorer return or authorization. Capture/storage
failure does not change scoring. It sets private `capture_failed` and public
`replay_ok=false`. Receipt corruption, schema/config incompatibility and oversized
receipts are rejected; no private exception values are logged.

Hashes compare canonical JSON bytes (including list order), not compressed file
bytes or Python object addresses. A counterfactual must deliberately update its
input hash; otherwise it is rejected as corruption. Its original output hash
remains the comparison target.

## Storage and deployment continuity

`decision_replay.TraceBuffer` keeps the latest 20 compressed receipts outside
AUTOPILOT_STATE, checkpoint, result history and repository. Each is limited to
16 MiB uncompressed (oversized capture is rejected, never truncated). Files are
0600, directory 0700, writes use temporary file + fsync + atomic replace.
Only existing ADMIN credentials authorize:

- `GET /api/admin/decision-traces`: private index and capture status.
- `GET /api/admin/decision-traces?trace=<id>`: private full receipt, `Cache-Control: no-store`.

Public status exposes only `trace_count`, `last_trace_cycle`, 16-hex `input_hash`
and `output_hash`, and boolean `replay_ok`. No receipt is attached to a checkpoint
or emitted in CI logs. Tests use reserved-domain synthetic fixtures only.

**Deployment prerequisite:** set NEO_DECISION_TRACE_DIR to a private directory
on an already available durable mount, or export the most recent receipt through
ADMIN before deployment to approved private storage. Default `/tmp/neo-decision-traces`
is process-restart persistent but NOT container-deploy persistent. Merely setting
the variable does not prove the mount is durable. No paid disk is provisioned and
no Render setting is changed in this PR. Cross-container retention is not claimed
without that prerequisite. There is no mechanism here to recover an old container's
erased filesystem.

Every scored cycle is captured, including the first post-deploy and the most
recent completed pre-deploy cycle. With durable storage, the former process's
latest receipt and the new process's first receipt coexist in the rolling buffer.
Export the pair before 20 newer receipts rotate it out. Startup/failure before
scoring completes may leave only the previous completed receipt: inspect private
capture status and cycle numbers rather than treating missing data as success.

## Replay workflow (offline)

Save an ADMIN-exported JSON receipt in approved private storage; never commit it.

```
python scripts/replay_decision.py /private/pre.json
python scripts/replay_decision.py /private/post.json
python scripts/replay_decision.py /private/pre.json --commit
python scripts/replay_decision.py /private/post.json --commit
```

`--commit` validates the recorded full SHA, creates a detached git worktree,
runs that commit's replay script and removes the worktree in finally. It never
fetches unknown code automatically and rejects commits without replay support.
Only execute trusted repository commits. Match the recorded TZ and gate environment
when using another machine; incompatible effective configurations are rejected.

Exit 0: IDENTICO. Exit 1: DIFF with differing field paths. Exit 2:
REPLAY_RIFIUTATO, with exception type only. Field values are not printed, to avoid
leaking private URLs/text into terminal/CI logs. To compare pre/post inputs,
privately call `decision_replay.differences(pre['inputs'], post['inputs'], 'inputs')`;
then replay each receipt independently. Different original scores with identical
individual replays point to changed inputs, not necessarily serialization loss.
A failed replay with identical code/config requires investigation; it is not proof
of the historical cause by itself.

## Validation

Tests exercise actual director capture through the gate, all candidate components,
first-cycle marking, offline hash equality, three hash seeds (1, 17, 951), emptied
price-cache DIFF, invalid-date explicit time, passive scoring equivalence, integrity
rejection, 20-file rotation/reopen, ADMIN auth, public allowlisting, storage failure,
checkpoint byte equality and recorded-commit worktree cleanup. No hash-seed
variation was observed in this fixture; no ordering fix was applied.

Checkpoint growth caused by capture: **0 bytes** (production state_codec output
byte-identical before/after saving a private receipt, with checkpoint timestamp
held equal). No deployment is part of this verification.

Complete Python 3.12.14 pytest result:

```
982 passed, 1 warning, 702 subtests passed in 35.62s
```

The warning is the existing Starlette async-generator lifespan deprecation.
The production `_state_payload` AST is unchanged from branch-base main `5b8ac54`.
`git diff --check` passes. No production deploy, historical root-cause claim or
three-deploy acceptance is implied by these offline results.
