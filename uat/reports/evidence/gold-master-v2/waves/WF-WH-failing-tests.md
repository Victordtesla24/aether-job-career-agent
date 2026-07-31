# WF / WH — failing tests (§8, §10, §15 step 2)

Run: 2026-07-31T08:4x UTC. Repo: `/home/ubuntu/github_repos/aether-job-career-agent`.
Role: test-author only — no implementation code touched. All commands run under
`flock /tmp/aether-pytest.lock -c "scripts/run-tests.sh <file> -v"` per the
shared-`aether_test`-schema rule; only the 4 new files below were ever run,
never the full suite.

## Scope

- W-F (a): canonical `PATCH /applications/{id}/stage` (§8.1, GOV-003) — does
  not exist yet.
- W-F (b): ML-APP-003 stage-count reconciliation (HIGH).
- W-F (c): `DELETE /approvals/{id}` + `POST /approvals/purge-expired` contract
  verification (§8.2) — ground truth says these already exist and work.
- W-H: `POST /jobs/{id}/apply` backend contract (§10, GOV-010) — the FE
  per-card Apply button is out of scope (owned by another agent,
  `apps/web/**`); this pins the backend write it will call.

## New test files

1. `apps/api/tests/test_gmv2_wf_stage_patch.py`
2. `apps/api/tests/test_gmv2_wf_reconciliation.py`
3. `apps/api/tests/test_gmv2_wf_approvals_contract.py`
4. `apps/api/tests/test_gmv2_wh_apply_contract.py`

## Legal transition matrix (discovered, not re-derived)

Source: `apps/web/src/components/applications/tracker-lib.ts` (`APP_STAGE`,
`STAGE_TO_APP_STATUS`, `STAGE_TO_JOB_STATUS`, `moveTargetsFor`) +
`apps/api/app/routers/applications.py` (`_APP_STAGE_TO_STATUS`,
`_JOB_STAGE_TO_STATUS`, `_validate_stage`, `move_application`,
`move_pipeline_job`).

- **Application-fed stages** (`Application.status`): `ready`(draft) →
  `submitted` → `in-review`(screening) → `interview` → `offer`. **Any**
  transition between these five is legal, **forward or backward**
  (`move_application` docstring: "the user is the source of truth for their
  own pipeline"); same-stage is an idempotent no-op.
- **Job-fed stages** (`Job.status`): `discovered` / `evaluating`(screening) /
  `tailoring`. Disjoint set — an application card targeting one of these is
  422 ("Job-status-fed"); a job card targeting an application-fed stage is
  422 the other direction.
- **Unknown stage key** → 422.
- **Closed application** (`rejected`/`withdrawn`) → cannot move at all, 422.
- A move that would create a second **active** Application for the same job
  → 409 (RT-004 promotion guard, backstopped by the partial unique index
  `Application_user_job_active_key`). Already covered by
  `test_applications_move.py`; not re-tested here.
- A job card that already has an Application → 409 (it left the pipeline
  half).

## Results summary

| File | Passed | Failed | Notes |
|---|---:|---:|---|
| `test_gmv2_wf_stage_patch.py` | 1 | 12 | 12 fail because the route doesn't exist; 1 (backward-compat) passes by design |
| `test_gmv2_wf_reconciliation.py` | 1 | 1 | ML-APP-003 reproduced on 1 of 2 seams |
| `test_gmv2_wf_approvals_contract.py` | 5 | 0 | endpoints already correct — verified, not rebuilt |
| `test_gmv2_wh_apply_contract.py` | 7 | 0 | backend Apply contract already honest — verified, not rebuilt |
| **Combined run** (all 4 files, single invocation) | **14** | **13** | matches per-file totals — no cross-file interaction |

Combined command:
```
flock /tmp/aether-pytest.lock -c "scripts/run-tests.sh tests/test_gmv2_wf_stage_patch.py tests/test_gmv2_wf_reconciliation.py tests/test_gmv2_wf_approvals_contract.py tests/test_gmv2_wh_apply_contract.py -v"
```
→ `13 failed, 14 passed, 6 warnings in 48.86s` [VERIFIED — command run 2026-07-31, full log
`/tmp/claude-2000/-home-ubuntu/0651e783-3ef0-4bfa-a33d-267c8becdc79/scratchpad/wf_wh_combined_run.log`
(scratchpad; per-file logs below are the durable evidence)].

---

## (a) `PATCH /applications/{id}/stage` — 12/13 FAIL for the right reason

Command:
```
flock /tmp/aether-pytest.lock -c "scripts/run-tests.sh tests/test_gmv2_wf_stage_patch.py -v"
```
Result: `12 failed, 1 passed, 6 warnings in 18.6xs` [VERIFIED-WITH-FRESH-EVIDENCE
2026-07-31T08:4xZ].

Every failure is a plain `404 {"detail":"Not Found"}` — Starlette's generic
unmatched-route response, distinct from the app's own
`HTTPException(404, "Application not found")` used everywhere else in this
router. That distinction is asserted explicitly in one test
(`test_owner_scoped_foreign_application_is_honest_404`) so a future "owner
scoping is broken" defect can't hide behind "the route doesn't exist" and
vice versa.

Node IDs and verbatim failure reason:

- `TestStagePatchEndpointExists::test_requires_auth`
  ```
  AssertionError: PATCH /applications/{id}/stage should require auth (401) like every
  other mutation endpoint; got 404 {"detail":"Not Found"}. A route that does not exist
  at all answers with a generic 404 before auth is even evaluated (FastAPI resolves
  routing before dependencies) -- this failure is the §8.1 canonical-endpoint gap, not
  an auth defect.
  ```
- `TestStagePatchEndpointExists::test_legal_move_succeeds_and_persists`
  ```
  AssertionError: expected 200 from the canonical PATCH stage endpoint (§8.1); got 404
  {"detail":"Not Found"} -- PATCH /applications/{id}/stage does not exist yet (GOV-003).
  ```
- `TestStagePatchEndpointExists::test_legal_moves_between_app_stages[draft-ready-submitted]`
  `[submitted-submitted-in-review]` `[screening-in-review-interview]`
  `[interview-interview-offer]` `[offer-offer-in-review]` `[submitted-submitted-ready]`
  (6 parametrized cases, the whole forward+backward matrix) — each:
  ```
  AssertionError: legal move <from> -> <to> should be a 200; got 404 {"detail":"Not Found"}
  assert 404 == 200
  ```
- `TestStagePatchEndpointExists::test_illegal_job_fed_target_is_422_with_honest_message`
  ```
  AssertionError: an application card moving to a job-fed stage must be rejected with an
  honest 422; got 404 {"detail":"Not Found"}
  assert 404 == 422
  ```
- `TestStagePatchEndpointExists::test_closed_application_cannot_move`
  ```
  AssertionError: a closed (rejected/withdrawn) application must not be movable via the
  canonical endpoint; got 404 {"detail":"Not Found"}
  assert 404 == 422
  ```
- `TestStagePatchEndpointExists::test_audit_logs_actor_from_to_timestamp`
  ```
  AssertionError: {"detail":"Not Found"}
  assert 404 == 200
  ```
- `TestStagePatchEndpointExists::test_owner_scoped_foreign_application_is_honest_404`
  ```
  AssertionError: got detail='Not Found' — if this is the generic Starlette 'Not Found'
  the route does not exist yet at all, which is NOT the same finding as a real
  owner-scope check (§8.1 requires the latter: 'another user's application -> 404/403,
  never a silent success').
  assert 'Not Found' == 'Application not found'
  ```

**Unexpected pass (documented, not manufactured):**
`TestLegacyMoveBackwardCompatibility::test_post_move_still_works_today` PASSED.
Meaning: the *legacy* `POST /applications/{id}/move` still works correctly
today — exactly the ground truth ("Move to..." menu is fully functional). It
is included as a forward-looking regression guard for §13.1 (the refactor to
delegate both endpoints to one shared transition service must not break this
existing, working path) — it was never expected to fail and its pass is not a
test defect.

Full verbatim log:
`/tmp/claude-2000/-home-ubuntu/0651e783-3ef0-4bfa-a33d-267c8becdc79/scratchpad/wf_stage_patch_run1.log`
(same content reproduced above for durability).

---

## (b) ML-APP-003 — stage-count reconciliation — 1/2 FAIL, root cause proven

Command:
```
flock /tmp/aether-pytest.lock -c "scripts/run-tests.sh tests/test_gmv2_wf_reconciliation.py -v"
```
Result: `1 failed, 1 passed, 6 warnings in 5.97s` [VERIFIED-WITH-FRESH-EVIDENCE
2026-07-31T08:4xZ].

- `TestStageCountReconciliation::test_board_and_funnel_agree_on_screening_stage_count`
  **FAILED** (reproduces the live defect through the app's own public
  endpoints — `POST /jobs/{id}/apply` then `POST /applications/{id}/move`,
  no hand-crafted DB inconsistency):
  ```
  AssertionError: ML-APP-003: GET /applications (board) and GET /applications/
  funnel/sankey (funnel) disagree on the screening-stage count for the identical
  underlying data — board=0, sankey=1. The board's default query hides this row
  because its parent Job.status is 'applied' (set by the earlier apply call and
  never advanced again); the funnel counts purely off Application.status with no
  Job.status filter.
  assert 0 == 1
  ```

- `TestStageCountReconciliation::test_applied_tab_and_funnel_agree_on_screening_stage_count`
  **PASSED** (1 == 1). This is a useful, honestly-reported unexpected pass: it
  isolates the break to the *default* board query specifically (`GET
  /applications` with `include_applied` unset/false) rather than a general
  applied-tab-vs-funnel divergence — `?include_applied=true` does surface the
  row (at its real `screening` status; the "generic applied badge" described
  in the ground-truth live observation is a frontend rendering choice on top
  of that correct payload, out of scope for this backend-seam test).

**Root cause, confirmed in code and by the test run:**
`list_applications()` (`app/routers/applications.py:103`) excludes any
application whose parent `Job.status IN ('applied','archived')` unless
`include_applied=true`. `funnel_sankey()` (`:35`) computes its `screened`
node straight off `Application.status IN ('screening','interview','offer')`
with **no** `Job.status` filter at all. `POST /jobs/{id}/apply` flips
`Job.status` to `'applied'` the moment an application is created/promoted —
and nothing ever advances it again when the application is later moved
deeper into the pipeline via `POST /applications/{id}/move` (which only ever
touches `Application.status`). A screening-stage application reached via the
ordinary apply-then-advance flow is therefore permanently invisible to the
default board query while the funnel keeps counting it — exactly the 3-way
disagreement (board 0 / applied-tab generic badge / funnel 2) from the live
ground truth.

Full verbatim log:
`/tmp/claude-2000/-home-ubuntu/0651e783-3ef0-4bfa-a33d-267c8becdc79/scratchpad/wf_reconciliation_run1.log`.

---

## (c) Approvals contract (§8.2) — 5/5 PASS — verified, not rebuilt

Command:
```
flock /tmp/aether-pytest.lock -c "scripts/run-tests.sh tests/test_gmv2_wf_approvals_contract.py -v"
```
Result: `5 passed, 6 warnings in 10.51s` [VERIFIED-WITH-FRESH-EVIDENCE
2026-07-31T08:4xZ].

All 5 node IDs passed on the first run:
- `TestDeleteOwnerScopedAndIdempotent::test_delete_is_owner_scoped`
- `TestDeleteOwnerScopedAndIdempotent::test_delete_is_idempotent_honest`
- `TestDeleteOwnerScopedAndIdempotent::test_delete_is_audit_logged`
- `TestPurgeExpiredProtectsLivePending::test_purge_never_touches_a_live_pending_approval`
  (**the important one** per the brief — asserts a non-expired pending
  approval is neither reported as purged nor removed)
- `TestPurgeExpiredProtectsLivePending::test_purge_is_audit_logged_with_expiry_window`

This is the honest finding for §8.2: `DELETE /approvals/{id}` and
`POST /approvals/purge-expired` (`app/routers/approvals.py:112,139`) already
implement owner-scoping, idempotent-honest 404s, the 409-still-actionable
guard, non-expired protection, and audit logging correctly. No new defect to
reproduce here — these tests exist as a self-contained confirmation filed
alongside this wave's failing tests, not a rebuild (near-identical coverage
already lives in `test_approvals_delete.py`, which this file does not
duplicate line-for-line).

Full verbatim log:
`/tmp/claude-2000/-home-ubuntu/0651e783-3ef0-4bfa-a33d-267c8becdc79/scratchpad/wf_approvals_run1.log`.

---

## W-H — `POST /jobs/{id}/apply` backend contract (§10, GOV-010) — 7/7 PASS

Command:
```
flock /tmp/aether-pytest.lock -c "scripts/run-tests.sh tests/test_gmv2_wh_apply_contract.py -v"
```
Result: `7 passed, 6 warnings in 17.07s` [VERIFIED-WITH-FRESH-EVIDENCE
2026-07-31T08:4xZ].

All 7 node IDs passed:
- `TestApplyIsAtomic::test_success_creates_application_and_advances_job_together`
- `TestApplyIsAtomic::test_gate_failure_leaves_job_not_applied_and_creates_no_application`
- `TestApplyIsAtomic::test_cover_letter_gate_failure_leaves_job_not_applied`
- `TestApplyOwnerScoped::test_foreign_job_is_404_not_silent_success`
- `TestApplyIdempotent::test_applying_twice_does_not_duplicate_the_application`
- `TestBulkApplyHonestPerJobOutcomes::test_partial_batch_success_is_reported_honestly_per_job`
- `TestBulkApplyHonestPerJobOutcomes::test_one_job_failing_does_not_affect_another_jobs_success`

**Honest finding (per the brief — do not manufacture failure):** every
assertion in the W-H backend-contract list already holds against current
code:
1. Atomic create+advance, with an honest 422 (no partial Application row, job
   left unmarked) on gate failure — confirmed both for the missing-tailored-
   résumé and missing-cover-letter branches.
2. Owner-scoped: applying to another user's job is an honest 404
   (`JobRepository.get_by_id` filters by `userId`), never a silent success.
3. Idempotent: applying twice returns the same `applicationId` and leaves
   exactly one `Application` row for the job — respects the partial unique
   index `Application_user_job_active_key`.
4. **No dedicated backend "bulk apply" endpoint exists.** Confirmed by
   grepping `app/routers/` for `bulk` (no hits) and reading
   `apps/web/src/app/dashboard/jobs/page.tsx` (~line 605-620): the Bulk Apply
   button loops over the same `POST /jobs/{id}/apply` per selected job
   client-side. The two batch tests here pin the backend property that makes
   an honest frontend report *possible*: each call succeeds/fails strictly
   per-job, in either order, with zero cross-job contamination — a failing
   job never gets silently marked applied, and a failing job elsewhere in
   the batch never blocks or corrupts a different job's genuine success.

The gap named by GOV-010 (no per-card Apply button on the Jobs screen UI) is
a frontend-only finding — `apps/web/**` is out of scope for this test file
per the brief; not reproduced here.

Full verbatim log:
`/tmp/claude-2000/-home-ubuntu/0651e783-3ef0-4bfa-a33d-267c8becdc79/scratchpad/wh_apply_run1.log`.

---

## Claims

- [VERIFIED-WITH-FRESH-EVIDENCE 2026-07-31T08:4xZ] `PATCH /applications/{id}/stage`
  does not exist: 12/12 targeted assertions fail with a 404 distinguishable
  from the app's real "not found" convention.
- [VERIFIED-WITH-FRESH-EVIDENCE 2026-07-31T08:4xZ] ML-APP-003 reproduced
  end-to-end through public endpoints: board=0 vs funnel=1 for the identical
  screening-stage row; root cause is `Job.status` filtering in
  `list_applications()` vs no such filter in `funnel_sankey()`.
- [VERIFIED-WITH-FRESH-EVIDENCE 2026-07-31T08:4xZ] `DELETE /approvals/{id}`
  and `POST /approvals/purge-expired` (§8.2) already satisfy the full
  contract, including the non-expired-protection guarantee — 5/5 pass.
- [VERIFIED-WITH-FRESH-EVIDENCE 2026-07-31T08:4xZ] `POST /jobs/{id}/apply`
  backend contract (atomicity, owner-scoping, idempotency, honest partial-
  batch outcomes) already holds — 7/7 pass; the only known gap (GOV-010) is
  the missing frontend per-card Apply button, out of scope here.
- [INFERRED] The legal transition matrix documented above is derived from
  code comments/docstrings already in the repo (`move_application`,
  `tracker-lib.ts`), not independently re-verified against a spec document —
  flagged as INFERRED rather than VERIFIED since no separate wireframe/spec
  text was cross-checked in this run.
