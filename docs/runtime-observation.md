# PR #215: observation-only loop-stall instrumentation

The historical 27.5-second stall is still not attributed to a specific
production function. This addition collects the evidence without moving CPU
work, changing compression settings, changing the gate, retrying smoke tests,
or touching Render settings. No merge or deploy has been performed.

## What is observed

- An asyncio heartbeat wakes every 250 ms; a delay over 2 seconds increments
  `event_loop_stalls`. `event_loop_max_lag_ms` records the maximum delay.
- A separate daemon observer samples `sys._current_frames()` while the loop
  heartbeat is overdue. Only repository-relative Python file names, function
  names and line numbers are retained, at most 12 frames. No arguments, locals,
  exception values, source lines, payloads, URLs or credentials are inspected.
- A coroutine-only watchdog could capture only the resumed heartbeat's stack;
  the separate observer is necessary to capture the blocking call itself.
- Phase timers cover restore/merge/migration, search, challenge search, evidence
  gate, commercial evaluator, hysteresis, director/autopilot, SETI, outcome,
  payload building, compaction, JSON, zlib, lzma, decode, local writes, external
  evidence/challenge stores and the checkpoint PUT. Timers use wall time,
  process CPU and thread CPU. CPU intervals for an awaited phase include other
  concurrent work; they are not exclusive attribution. Nested phases overlap.
- Private checkpoint/status includes bounded phase statistics and the last
  project stack. Public snapshot includes only counters and the five slowest
  phases with numeric durations, selected from a fixed phase-name allowlist.
  Public sanitization is idempotent and strips arbitrary phase names and stacks.
- Timings/counts are per process. Import-time restore has timers, but the loop
  heartbeat starts at lifespan before autopilot; there is no running event loop
  to measure during module import.
- Monitoring cannot guarantee a stack if a C extension holds the GIL for the
  entire stall or the process is fully descheduled. It still records the lag
  after resumption. This limitation must not be reported as absence of a stall.

## Reproduction measured locally

Command: `python scripts/reproduce_loop_stall.py --mib 3 --passes 3`.
The script uses deterministic synthetic data, no runtime backup, credentials,
network calls or application startup. Its process is pinned to one CPU, not
throttled to Render's 0.15-core quota. Three encoding passes match the three
existing encodes in `_checkpoint_state_to_render`; the surrounding checkpoint
and autopilot are not fully replayed. Data entropy is synthetic and may differ
from the production checkpoint.

Raw JSON size: 3,145,752 bytes. One resumed-loop stall: **5,349.813 ms**.
Simulated first post-restore work: **5,599.668 ms wall**, **5,599.314 ms CPU**.
Restore decode: **63.600 ms**. JSON max: **8.057 ms**. zlib max: **129.858 ms**.
lzma max: **1,894.880 ms wall / 1,894.796 ms CPU** per encoding call.

Observed project stack during the stall:

```
state_codec.py:22 encode_checkpoint       # existing lzma.compress call
scripts/reproduce_loop_stall.py:29 replay # consecutive checkpoint encodes
scripts/reproduce_loop_stall.py:48 <module>
```

See `runtime-observation-replay.json` for numeric results. This proves that the
actual existing codec can starve the loop with a realistically sized synthetic
payload. It does **not** prove that lzma caused the historical incident. It is
not an extrapolation of the historical delay to a 0.15-core service.

No production correction or before/after claim is made. The next evidence step
is a user-approved instrumentation-only deployment and observation of its first
autopilot cycle. The user has not approved that deploy.

## Validation requirements

Tests capture a project blocking function while it is executing, distinguish
normal awaited IO from a stall, preserve return/exception/cancellation behavior,
verify public privacy/idempotence, and compare checkpoint bytes against the
original codec. Existing extracted-function test/recovery scopes receive the
new observation dependency; their original assertions remain in force.

Render: no settings/environment variables were read, exported or modified by
this work; no deploy, restart or rollback was triggered. Code continues to use
the pre-existing checkpoint write path after an eventual approved deploy.


Final local checks:

```
python -m unittest discover -v
Ran 942 tests in 16.611s
OK
Public commercial 24/24; family mapping 24/24
Public challenge 12/12
Both workflows: YAML and every shell block parse
git diff --check: clean
```

Configured production hidden controls have not been rerun for this un-deployed
candidate. The local hidden-control fixture tests are part of the suite, not
a replacement for Render's actual hidden sets.
