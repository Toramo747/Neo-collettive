# Memory recovery safety case — restart continuity (draft)

## Evidence
2026-10-10 snapshots: 07:14 CEST cycle 3309 **200** active evidences; 08:23 CEST post-restart cycle 3311 **147**, without reported retention/archive/duplicate removals and without `evidence_regression_blocked`. Later 159. Identity-level cause unverified; not proof of physical deletion.

## Scope
- In `_restore_state` **after** hydrating external evidence, compare current verified generation with immediately previous verified generation using canonical runtime evidence identities. This check operates only on private memory and returns aggregate counts.
- If the current generation lacks any predecessor identities, union known records only **in volatile memory**, mark `evidence_store_degraded=true`, set `evidence_store_status=continuity_blocked`, preserve the original external checkpoint reference. Existing checkpoint logic uses degraded mode to avoid rewriting the active evidence store. **No automatic promotion or gate change.**
- Tests reproduce **200 -> 147** and identity loss even when count stays equal; clean growth stays accepted.
- No scoring, thresholds, commercial gate, student, production env vars, Render plan, credentials, disk, Relay, or snapshots changed.

## Critical limitations: not a full recovery
1. The predecessor reference is only one generation deep and can be missing or legitimately different due to retention/archive. When unavailable, status is `predecessor_unavailable` (**not verified**), but this draft currently does not stop all writes. Do NOT merge/deploy until fail-closed behavior for an unavailable baseline is reviewed.
2. A subset can pre-exist before restart; this check detects subset regressions relative to the immediate predecessor only, not against an external high-water archive. Need HMAC-only private generation inventory and comparisons, validated to avoid false positives on approved retention/archival.
3. No fresh full private snapshot of the 200 evidence IDs is in GitHub public snapshots. Recovery of the missing IDs requires private backup inspection (including existing `BACKUP_20261007T023646Z`) without uploading raw rows to public GitHub.
4. Do not reuse the Relay's persistent pilot volume or change Render configuration until storage isolation, access controls, and operational costs are reviewed.
5. Render production deploys are independently failing pre-build (see #244). This PR is offline-only and **must remain draft** until tests and production release blockers are cleared.

## Required next proof
- Full CI green and offline restart/partial-write/corrupt generation/expired-or-archived evidence tests.
- Non-public evidence-ID comparison, recovery source selection and immutable verified backup.
- Fail-closed semantics when predecessor inaccessible, including explicit legitimate-retention exception only with private proof.
- Repeated restart simulation with zero unexplained loss, preserve privacy; existing 6/6 public+hidden gate unchanged.

Related: #244 (Render deploy blocked).
