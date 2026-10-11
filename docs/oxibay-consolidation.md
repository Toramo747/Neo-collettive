# OXIBAY — consolidation (2026-10-11)

Single source for open problems, proven causes, fixes and the release path.
All production data below comes from read-only GET calls to the Render API
(workflow `Render Env Inventory (read-only)`), aggregate counts only.

## 1. Inventory

| # | Problem | Cause | Fix | Tests | Depends on | Action | Priority |
|---|---------|-------|-----|-------|------------|--------|----------|
| 1 | Evidence 200 → 147 on 10 Oct | **Proven.** Render applies env vars written via API only at the next deploy. Plain restarts (`server_restarted` 10-10 06:13) boot with the deploy-time env (10-08 19:13). The newest orphan generation `999a52d8…` (203 rows) has newest `last_seen` exactly 10-10 06:13; the next snapshot (06:23) shows 147. | PR #246: boot reads the *saved* env from the Render API (`render_saved_env.py`); checkpoint guard on monotonic `state_generation` (`state_generation_guard.py`). | `test_stale_env_restart.py` (fails without the fix — mutation-checked), `test_evidence_restart_continuity.py` | — | merge + deploy #246 | P0 |
| 2 | 58 evidence identities missing | Consequence of 1. All 58 still inside the 21-day retention window, 26 were gate-eligible when saved; the archive is empty, so they were neither expired nor archived. | `evidence_reintegration.py` + `POST /api/admin/evidence-reintegration` (plan → apply with `confirm=plan_id` → revert by batch). Rows re-enter through the normal migration, so gate eligibility is recomputed. | `test_evidence_reintegration.py` | 1, 3 | admin `plan`, then `apply` after deploy | P0 |
| 3 | #244: deploys `update_failed`, no build | **Hypothesis, strongly supported, not proven.** Failed deploys go `deploy_started → deploy_ended(failed)` with no `build_started`; successful ones always build first. Env count is 58 (the reported 150 cap is not the issue) but the saved env holds **1.998 MB**, 72 % of it orphan generations (23 unreferenced generations, 1.44 MB) accumulated because cleanup followed the stale state. A platform cap on total env size (≈1 MiB, typical for container secret stores) would explain a pre-build failure. Render does not document a size limit. | `tools/render_env_orphans.py`: verified backup in the private archive, deletion plan that keeps referenced generations and the ones needed for reintegration; apply only by manual dispatch, refused if plan or backup does not match. Projected env after cleanup: **0.56 MB**. Root cause of accumulation removed by 1. | `test_render_env_orphans.py` | backup (done) | authorize cleanup, then deploy | P0 |
| 4 | Health check timeouts / event-loop stalls (03:56 `server_failed`, stall 3.8 s) | Ongoing, partially explained (checkpoint codec and lzma on the loop, fixed off-thread in earlier PRs). | none new | `test_checkpoint_observation_deploy.py` | 3 | observe after deploy | P2 |
| 5 | Challenge track possibly rolled back on the same restart | Same mechanism as 1; the track is one record per generation, loss not measurable by identity. Current generation is newer than all orphans. | covered by 1 for the future | — | 1 | none (documented) | P3 |
| 6 | Undeployed code on main | `ee591d6a` (bounded demand-retrieval coverage, no gate change) blocked by 3. #246 is based on it. | ships with #246 | Full Python CI | 3 | ships with #246 | P1 |
| 7 | 38 open PRs, 20+ draft experiments | Accumulation. Oldest (#30, #43, #63–66, #79, #94, #126) predate current architecture. | none | — | — | review/close after release (no deletion before proof) | P3 |

## 2. Memory — what is where (11 Oct, 03:05 UTC)

- Current: 172 identities (head `7dcf6821…`, previous `7a75aa99…`, both intact).
- Orphan evidence generations: 17, all intact (sha256 of decoded payload = generation id).
- Missing from current but recoverable: **58** (0 expired, 0 archived, 26 gate-eligible at save time).
- Not recoverable: none found among identities that existed in a saved generation.
- Independent backup: private archive `runtime-checkpoints/env-backups/env-backup-20261011T031403Z` (45 keys, sha256 manifest `8fe60234…`).

## 3. Persistence properties after #246

| Property | How |
|---|---|
| No silent loss on restart | boot reads saved env, process env only as fallback (`boot_env_source` in `/api/memory/status`) |
| No overwrite by a stale writer | `state_generation` + writer id; write refused if saved is newer (`stale_generation_write_blocked`) |
| Read-after-write | chunks already verified; `NEO_STATE_JSON` now verified against the echoed value |
| Integrity | generation id = sha256 of payload, checked on decode |
| Versioned generations / recovery | previous generation and orphan recovery (now on the saved view) |
| Legitimate deletions | retention/archive accounting in `evidence_memory_guard` (unchanged) |
| Independent backup | `render_env_orphans.py backup` → private archive |

Relay (`mycelix-relay-pilot`) was not touched and is not proposed as storage.

## 4. Release plan (needs one authorization)

1. Fresh backup (runs on every push of the orphan tool; or dispatch `Render Env Backup and Orphan Plan`, mode `plan`). Note `backup_dir` and `plan_id` from the annotations.
2. Dispatch the same workflow with `mode=apply`, `plan_id`, `backup_dir`. Expect ~33 keys deleted, env ≈ 0.56 MB.
3. Merge #246 → deploy.
4. Smoke: `/health` returns the new commit; `/api/memory/status` shows `boot_env.boot_env_source=render_api_saved`, `state_generation` increasing each checkpoint, `state_generation_guard.status=ok`.
5. Reintegration: `POST /api/admin/evidence-reintegration {"mode":"plan"}` → expect ~58 candidates; then `{"mode":"apply","confirm":"<plan_id>"}`. Revert: `{"mode":"revert","batch":"<plan_id>"}`.
6. Two consecutive snapshots with persistent evidence ≥ the post-reintegration count (net of logged retention/archive).

Rollback: redeploy `ac91d2aa` (env is compatible: new fields are ignored by old code). Deleted orphans can be restored from the private backup with the same keys.
If step 3 still fails with an env of ~0.56 MB, hypothesis 3 is falsified and the next check is the deploy log text in the Render dashboard.
