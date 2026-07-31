# GOLD-MASTER-V2 §15 — Approval decision audit gap + TOCTOU double-resolve fix

**Agent:** fixer-medium
**Scope:** `apps/api/app/routers/approvals.py`, `apps/api/app/repositories/approval.py`,
`apps/api/app/services/approval_service.py`, `apps/api/app/db.py`,
`packages/db/src/schema.prisma`, `apps/api/tests/test_gmv2_approval_audit_fix.py`
**Source finding:** `uat/reports/evidence/gold-master-v2/adversarial/APPROVAL-AUDIT-INCIDENT.md`
(claim-auditor + qa-adversary, §6 and §7.2)

---

## 1. Root cause

### Defect 1 — approval decisions write no audit row (HIGH, governance)

`apps/api/app/routers/approvals.py`'s `approve()` and `reject()` handlers called
`ApprovalService().resolve(...)` and returned the result directly — no call to
`write_audit()`. This is the code path behind the product's core human-in-the-loop
safety promise, and its outcomes were unattributable inside the application: the
*only* place a decision was recoverable was `/var/log/aether/api.log`, which rotates
(`truncate -s 0` per the runbook) and carries no `userId`.

**The asymmetry (verbatim from source, pre-fix):**

```python
# apps/api/app/routers/approvals.py — BEFORE
@router.post("/{approval_id}/approve")
def approve(
    approval_id: str, current_user: CurrentUser, body: DecisionBody | None = None
) -> dict[str, Any]:
    _merge_decision_context(approval_id, current_user["id"], body)
    return ApprovalService().resolve(approval_id, current_user["id"], "approved")
    # ^ no write_audit() call


@router.post("/{approval_id}/reject")
def reject(...):
    ...
    return ApprovalService().resolve(approval_id, current_user["id"], "rejected")
    # ^ no write_audit() call
```

...in the very same file, `delete_approval()` (line ~163) and
`purge_expired_approvals()` (line ~125) both DO call `write_audit()`:

```python
write_audit(
    user_id, "approval.delete", target_type="approval", target_id=approval_id,
    detail={"status": deleted["status"], "type": deleted["type"], "expired": _is_expired(deleted)},
)
```

`write_audit` is imported once at the top of the file and used twice — for the two
*housekeeping* actions — never for the two decision actions. Production evidence
(from the adversarial investigation): `AdminAuditLog` action counts included
`approval.delete: 17` and `approval.purge_expired: 2`, but **zero**
`approval.approve` / `approval.reject` rows across 110 `ApprovalRequest` rows.

### Defect 2 — TOCTOU double-resolve window

`ApprovalRepository._resolve()`'s UPDATE was:

```sql
UPDATE "ApprovalRequest"
SET "status" = %s::"ApprovalStatus", "resolvedAt" = NOW()
WHERE "id" = %s
```

No `"userId"` predicate, no `"status" = 'pending'` predicate. `user_id` was passed
into `_resolve()` only to scope the *side-effect* syncs (`_sync_application`,
`_sync_resume`), never the resolve write itself — an inconsistency: the author
clearly intended user-scoping (it's present one line below, on the sync calls) but
missed it on the primary UPDATE.

---

## 2. Fix

### Defect 1 — audit rows

Added `_write_decision_audit()` to `apps/api/app/routers/approvals.py`, called
from both `approve()` and `reject()` **after** a successful resolve (never on a
409/404 — no side effect, no audit noise). It mirrors the existing
`write_audit()` calls in the same file, same helper, same `target_type="approval"`
/ `target_id=<approval id>` shape:

```python
def _write_decision_audit(user_id, action, decision, resolved) -> None:
    payload = ApprovalRepository._payload_dict(resolved)
    write_audit(
        user_id, action, target_type="approval", target_id=resolved["id"],
        detail={
            "decision": decision, "type": resolved.get("type"),
            "kind": payload.get("kind"), "job_id": payload.get("job_id"),
            "application_id": resolved.get("applicationId"),
            "edited": bool(payload.get("edited")),
            "trust_agent": payload.get("trust_agent"),
        },
    )
```

Also added `resolvedByUserId` (populated with the resolving `user_id` — always the
approval's own owner today, since only the owner can reach `resolve()`) and
`resolvedFromIp` (best-effort caller IP, captured via a `_client_ip(request)`
helper duplicated from `routers/admin.py`'s identical helper — duplicated rather
than cross-imported to avoid coupling one router to another router's private
function). Both are additive columns on `ApprovalRequest`, populated by the same
UPDATE that flips `status`, so they land in the *row itself* — recoverable even if
`AdminAuditLog` or the access log is gone.

### Defect 2 — TOCTOU close

`ApprovalRepository._resolve()`'s UPDATE is now a compare-and-set:

```sql
UPDATE "ApprovalRequest"
SET "status" = %s::"ApprovalStatus", "resolvedAt" = NOW(),
    "resolvedByUserId" = %s, "resolvedFromIp" = %s
WHERE "id" = %s AND "userId" = %s AND "status" = 'pending'::"ApprovalStatus"
```

`ApprovalRepository.approve()`/`reject()` now return `None` when the compare-and-set
matches zero rows (lost the race, or wrong owner). `ApprovalService.resolve()` no
longer does `assert resolved is not None` (which was itself a latent 500-on-race
bug the moment the WHERE clause tightened) — it now raises an honest
`409 Conflict` ("Approval was resolved concurrently — no change made.").

---

## 3. Was the TOCTOU a real hole or defence-in-depth?

**Split answer, and it matters which predicate:**

- **The `"status" = 'pending'` predicate closes a REAL hole.** `ApprovalService.resolve()`
  reads the row (`get()`), checks `status == 'pending'`, then writes. Two concurrent
  HTTP calls from the *legitimate owner* (e.g. a double-click, a retried request, two
  browser tabs) can both pass the read before either commits the write. Pre-fix, BOTH
  writes would succeed unconditionally — the second silently overwrites the first
  (e.g. approve-then-reject could flip a `submitted` Application back to `rejected`,
  or fire `_sync_resume`/`_sync_application` twice). This is reachable through the
  normal HTTP surface with no special access. Proven directly by
  `test_repository_second_resolve_does_not_silently_succeed` and
  `test_service_stale_read_race_returns_honest_conflict_not_500` (the latter's
  pre-fix run returned `200` with `status: "rejected"` on a row already resolved
  `approved` — a live double-resolve, not a hypothetical).

- **The `"userId" = %s` predicate is defence-in-depth for the HTTP path today**,
  because `ApprovalService.get()` (called before `resolve()` ever reaches the
  repository) already does an owner-scoped `SELECT ... WHERE "id" = %s AND "userId" = %s`
  and 404s a foreign caller before the write is ever attempted — confirmed by the
  pre-existing, still-green `test_user_isolation` /
  `TestDeleteOwnerScopedAndIdempotent.test_delete_is_owner_scoped`-equivalent HTTP
  behaviour. A foreign user's own JWT can never reach `_resolve()` with a mismatched
  `(approval_id, user_id)` pair through the router. However, it was a genuine gap for
  any *other* caller of the repository directly (future admin bypass, batch job,
  internal service call, or a bug in the upstream ownership check) — the write itself
  enforced no authorization, matching neither the pattern already used by
  `claim_execution()` (which *does* scope its own UPDATE by `userId`) nor the
  side-effect syncs one line below it. Closing it costs nothing and removes a latent
  trap for future code. Proven directly by `test_repository_write_is_owner_scoped`.

---

## 4. Files changed

| File | Change |
|---|---|
| `apps/api/app/db.py` | Extended `ensure_approval_columns()`: additive `ALTER TABLE "ApprovalRequest" ADD COLUMN IF NOT EXISTS "resolvedByUserId" text` / `"resolvedFromIp" text`, alongside the pre-existing `executedAt`. Fast-path existence check now requires all 3 managed columns present before short-circuiting. |
| `apps/api/app/repositories/approval.py` | `_COLUMNS` now includes `resolvedByUserId`, `resolvedFromIp`. `approve()`/`reject()`/`_resolve()` take an optional `ip` param. `_resolve()`'s UPDATE is now a compare-and-set (`AND "userId" = %s AND "status" = 'pending'`) and stamps the two new columns; returns `None` on zero rows affected. `ensure_approval_columns()` called at the top of `create()`, `get_by_id()`, `_list()`, `delete_by_id()`, `_resolve()` (all methods whose SQL references `_COLUMNS`). |
| `apps/api/app/services/approval_service.py` | `resolve()` takes an optional `ip` param, forwards it to the repository, and replaces the `assert resolved is not None` with an honest `HTTPException(409, ...)` when the repository reports a lost race. |
| `apps/api/app/routers/approvals.py` | Added `_client_ip(request)` and `_write_decision_audit(...)` helpers. `approve()`/`reject()` now take `request: Request`, pass `ip=_client_ip(request)` into `ApprovalService().resolve(...)`, and call `_write_decision_audit(...)` after a successful resolve. |
| `packages/db/src/schema.prisma` | Documented the two new columns on `ApprovalRequest` (additive, nullable) — matches the existing convention of annotating lazy-DDL-managed columns (`executedAt`) in the Prisma schema for truthful documentation, even though the Python app applies the DDL itself (no migration runner; ADR-TR-1). |
| `apps/api/tests/test_gmv2_approval_audit_fix.py` | New — 7 tests, written and proven RED before any production code changed. |

No changes to `app/routers/analytics.py`, `app/routers/applications.py`,
`app/services/stage_transitions.py`, or `apps/web/**` (out of scope, per brief).

---

## 5. Migration details

Additive-only, lazy DDL, mirroring the existing `executedAt` pattern
(`ensure_approval_columns()` in `app/db.py`):

```sql
ALTER TABLE "ApprovalRequest" ADD COLUMN IF NOT EXISTS "resolvedByUserId" text;
ALTER TABLE "ApprovalRequest" ADD COLUMN IF NOT EXISTS "resolvedFromIp" text;
```

- No default, no `NOT NULL` — existing rows read `NULL` ("not resolved by/from
  recorded"), which is honest for the 110 pre-existing production rows (their
  resolver is genuinely unrecoverable from the DB — only `AdminAuditLog`/logs, per
  the incident report §4).
- No FK — matches every other lazy-DDL text column added this way
  (`Job.dedupHash`, `Resume.approvalStatus`, etc.) and the existing sibling
  `executedAt` on the same table.
- `ADD COLUMN ... text` with no default is metadata-only on PostgreSQL — fast and
  safe against the live production table.
- Guarded by the existing transaction-scoped advisory lock
  (`pg_advisory_xact_lock(7420240725)`, unchanged) so concurrent first-hit callers
  across worker processes cannot race the ALTERs.
- `TRUNCATE` (used by the test suite's per-test cleanup) never drops columns, so
  this survives the shared `aether_test` schema across runs.
- Never DROP, never ALTER TYPE, no production row was written by this fix (test
  suite runs exclusively against `aether_test`).

---

## 6. Verbatim test output

### 6.1 BEFORE — new tests proven RED (pre-fix)

Command:
```
flock /tmp/aether-pytest.lock -c "scripts/run-tests.sh tests/test_gmv2_approval_audit_fix.py tests/test_gmv2_wf_approvals_contract.py tests/test_approvals.py tests/test_approvals_delete.py tests/test_approval_modal.py -v"
```

Result: **7 failed, 36 passed** in 81.69s (2026-07-31, timestamps per API host clock).

```
FAILED tests/test_gmv2_approval_audit_fix.py::TestApproveRejectAuditRows::test_approve_writes_audit_row_naming_actor_target_decision
FAILED tests/test_gmv2_approval_audit_fix.py::TestApproveRejectAuditRows::test_reject_writes_audit_row_naming_actor_target_decision
FAILED tests/test_gmv2_approval_audit_fix.py::TestApproveRejectAuditRows::test_audit_row_shape_matches_delete_convention
FAILED tests/test_gmv2_approval_audit_fix.py::TestResolvedByUserIdPersisted::test_resolved_by_user_id_persisted_and_readable
FAILED tests/test_gmv2_approval_audit_fix.py::TestToctouWriteScoping::test_repository_second_resolve_does_not_silently_succeed
FAILED tests/test_gmv2_approval_audit_fix.py::TestToctouWriteScoping::test_repository_write_is_owner_scoped
FAILED tests/test_gmv2_approval_audit_fix.py::TestToctouWriteScoping::test_service_stale_read_race_returns_honest_conflict_not_500
============= 7 failed, 36 passed, 7 warnings in 81.69s (0:01:21) ==============
```

Key failure excerpts (proving each is a genuine defect, not a test bug):

```
AssertionError: expected an approval.reject audit row — none written
AssertionError: expected an approval.approve audit row — none written
AssertionError: resolvedByUserId must be persisted and returned by the approve response;
  got {'id': 'c852c9cb2c812ac139c06b6f5', ..., 'status': 'approved', ...} (no resolvedByUserId key)
AssertionError: a second resolve of an already-resolved approval must not silently succeed
  a second time (TOCTOU close at the write, §15 Defect 2)
  assert {'id': 'cea2e7ebc34c1fb1ba3052f76', ..., 'status': 'approved', ...} is None
AssertionError: resolving with a mismatched userId must not succeed at the write layer
  assert {'id': 'c07318503a48e082ee0a3be86', 'userId': 'c43a...', ...} is None
AssertionError: a losing racer must get an honest 409, not a silent second resolve or a 500;
  got 200 {"id":"c518b8c947a8c67fcaad31cae",...,"status":"rejected",...}
  assert 200 == 409
```

The last one is the clearest live proof of the TOCTOU: a row already resolved
`approved` was silently flipped to `rejected` by a second call, returning `200`.

### 6.2 AFTER — same files, fix in place

Command (same invocation):
```
flock /tmp/aether-pytest.lock -c "scripts/run-tests.sh tests/test_gmv2_approval_audit_fix.py tests/test_gmv2_wf_approvals_contract.py tests/test_approvals.py tests/test_approvals_delete.py tests/test_approval_modal.py -v"
```

Result: **43 passed**, 0 failed, in 81.67s.

```
tests/test_gmv2_approval_audit_fix.py::TestApproveRejectAuditRows::test_approve_writes_audit_row_naming_actor_target_decision PASSED
tests/test_gmv2_approval_audit_fix.py::TestApproveRejectAuditRows::test_reject_writes_audit_row_naming_actor_target_decision PASSED
tests/test_gmv2_approval_audit_fix.py::TestApproveRejectAuditRows::test_audit_row_shape_matches_delete_convention PASSED
tests/test_gmv2_approval_audit_fix.py::TestResolvedByUserIdPersisted::test_resolved_by_user_id_persisted_and_readable PASSED
tests/test_gmv2_approval_audit_fix.py::TestToctouWriteScoping::test_repository_second_resolve_does_not_silently_succeed PASSED
tests/test_gmv2_approval_audit_fix.py::TestToctouWriteScoping::test_repository_write_is_owner_scoped PASSED
tests/test_gmv2_approval_audit_fix.py::TestToctouWriteScoping::test_service_stale_read_race_returns_honest_conflict_not_500 PASSED
tests/test_gmv2_wf_approvals_contract.py::TestDeleteOwnerScopedAndIdempotent::test_delete_is_owner_scoped PASSED
tests/test_gmv2_wf_approvals_contract.py::TestDeleteOwnerScopedAndIdempotent::test_delete_is_idempotent_honest PASSED
tests/test_gmv2_wf_approvals_contract.py::TestDeleteOwnerScopedAndIdempotent::test_delete_is_audit_logged PASSED
tests/test_gmv2_wf_approvals_contract.py::TestPurgeExpiredProtectsLivePending::test_purge_never_touches_a_live_pending_approval PASSED
tests/test_gmv2_wf_approvals_contract.py::TestPurgeExpiredProtectsLivePending::test_purge_is_audit_logged_with_expiry_window PASSED
tests/test_approvals.py  (9/9) PASSED
tests/test_approvals_delete.py  (11/11) PASSED
tests/test_approval_modal.py  (9/9) PASSED
================== 43 passed, 7 warnings in 81.67s (0:01:21) ===================
```

`tests/test_gmv2_wf_approvals_contract.py` — **5/5 green**, as required (2 delete
tests shown above correspond to the file's `TestDeleteOwnerScopedAndIdempotent`
class 3/3 + `TestPurgeExpiredProtectsLivePending` 2/2 = 5/5; full listing above).

### 6.3 Wider regression sweep — other approvals-touching suites

Ran (single flock invocation, background due to >120s runtime — LLM replay
fixtures): `test_email_send_gate.py`, `test_mv_cluster_a_cover_letter.py`,
`test_mv_resume_studio.py`, `test_mv_j_correctness.py`, `test_part2_remediation.py`,
`test_wave4c_outreach_contact_agents.py`, `test_wave4c_notification_agent.py`.

Result: **1 failed, 88 passed** in 262.46s.

```
FAILED tests/test_mv_cluster_a_cover_letter.py::TestRefineFabricatedSignOffName::test_fabricated_signoff_name_must_not_survive_refine
  AssertionError: {"detail":"Cover letter rejected: Your profile name looks like a
  placeholder or test value, not a real name — set your real name in Settings
  before generating a cover letter."}
  assert 422 == 200
```

**Adjudicated as a PRE-EXISTING failure, unrelated to this fix.** Verified by
`git stash push` of exactly the 5 files this fix touched (`app/db.py`,
`app/repositories/approval.py`, `app/routers/approvals.py`,
`app/services/approval_service.py`, `packages/db/src/schema.prisma`), then
re-running the single failing test against the resulting pre-fix tree — it fails
identically (`422` on a placeholder-name guard inside the cover-letter generation
path, `app/routers/agents.py:2378`, nothing to do with approvals). Confirmed:

```
tests/test_mv_cluster_a_cover_letter.py::TestRefineFabricatedSignOffName::test_fabricated_signoff_name_must_not_survive_refine FAILED
1 failed, 7 warnings in 6.98s
```

Stash was then popped and all 5 files restored (`git status` confirmed identical
diff stat before/after: `142 insertions(+), 29 deletions(-)` across the 5 files).
Not this fix's file set; not touched by this fix; explicitly out of this fix's
scope per the brief's file ownership. Reported honestly, not silenced.

---

## 7. Residual risks

1. **`resolvedByUserId` is always the approval's own owner today.** Since only the
   owning user can reach `resolve()` (owner-scoped read + owner-scoped write), this
   column currently duplicates `userId` on every row. It becomes non-redundant the
   moment any delegated-resolve path exists (e.g. an admin override, a team
   approval flow) — the column is there ahead of that need, per the incident
   report's recommendation, but has no differentiating value yet.
2. **`resolvedFromIp` is best-effort and spoofable.** Per the existing
   `rate_limit.py` docstring for this deployment (`Envoy -> nginx -> uvicorn`),
   nginx does not forward a trustworthy `X-Forwarded-For`, so this is documentary
   ("what did the request claim"), not an authentication signal — same caveat that
   already applies to `admin.py`'s identical `_client_ip()` helper it mirrors.
3. **Historical data is not backfilled.** The 110 pre-existing production
   `ApprovalRequest` rows (and their corresponding zero `approval.approve`/
   `approval.reject` audit rows) remain exactly as unattributable as before — this
   fix is forward-only, as instructed (additive DDL, no data migration requested).
4. **UI surfacing not in scope.** The incident report's recommendation #3 ("surface
   the decision record in the UI's approval history") was explicitly UI work; this
   fix is backend-only per the brief's file ownership (`apps/web/**` off-limits).
5. **`_merge_decision_context()` runs before `resolve()`, in a separate
   transaction.** If the merge commits but the resolve then hits the new 409 (lost
   race) or expires, the merged `edited`/`trust_agent` context is left on an
   otherwise-still-pending row — this is pre-existing behaviour (explicitly
   documented as intentional/harmless in that function's own docstring) and is
   unchanged by this fix.

---

## 8. Verification checklist

- [x] `tests/test_gmv2_approval_audit_fix.py` — 7/7 new tests, RED before fix,
      GREEN after `[VERIFIED-WITH-FRESH-EVIDENCE — flock pytest run, 2026-07-31]`
- [x] `tests/test_gmv2_wf_approvals_contract.py` — 5/5 green, unchanged
      `[VERIFIED-WITH-FRESH-EVIDENCE]`
- [x] `tests/test_approvals.py` (9), `tests/test_approvals_delete.py` (11),
      `tests/test_approval_modal.py` (9) — 29/29 green, unchanged
      `[VERIFIED-WITH-FRESH-EVIDENCE]`
- [x] Wider approvals-adjacent regression sweep (7 files, 89 tests) — 88/89 green;
      the 1 failure independently reproduced on the pre-fix tree via `git stash`,
      confirmed unrelated `[VERIFIED-WITH-FRESH-EVIDENCE]`
- [x] Migration additive-only, lazy DDL, no production row touched
      `[VERIFIED — code inspection + test-schema-only pytest runs]`
- [x] No self-approval, no ledger/gate edits made by this agent
