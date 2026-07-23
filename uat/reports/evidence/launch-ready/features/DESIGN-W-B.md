# Workstream B — Design Note (FEAT-B1 + FEAT-B2)

Date: 2026-07-24 · Base: main @ 837a173 · Author: launch-ready agent

## FEAT-B1 — Remove stale/expired approval requests

**Schema convention discovered:** `ApprovalStatus` enum is `pending|approved|rejected` only —
no terminal "dismissed" state; every other domain (offers, interviews, networking, stories)
hard-deletes with `DELETE … WHERE id AND userId`. → **Hard-delete** is the convention.

**Expiry source of truth:** `app.services.approval_service.EXPIRY_HOURS = 48`
(`_is_expired`: pending && `createdAt` older than 48h). FE mirrors it in
`components/approvals/lib.ts::isExpired`. Server-side purge imports `EXPIRY_HOURS` — one source.

### API
- `DELETE /approvals/{approval_id}` — owner-scoped.
  - 404 unknown/foreign id (second delete → 404: idempotent-honest, no side effect).
  - **409 for a live (non-expired) pending approval** — it is still actionable; approve/reject it instead.
  - Deletable: expired-pending, approved, rejected rows. Returns the deleted row.
  - Audit: `approval.delete` (targetType=approval, detail: status/type/expired).
- `POST /approvals/purge-expired` — one request, one SQL
  `DELETE WHERE userId=? AND status='pending' AND createdAt < NOW() - EXPIRY_HOURS` RETURNING ids.
  - Returns `{"purged": n, "ids": [...]}`. MUST NOT touch non-expired pending or resolved rows.
  - Audit: `approval.purge_expired` (detail: count + ids). Audit convention:
    `app.repositories.admin.write_audit` (append-only AdminAuditLog; also used by billing router).

### Frontend (dashboard/approvals)
- Per-card **Remove** button on every non-actionable card (expired OR resolved) —
  `window.confirm` (app's destructive pattern, cf. story-card.tsx), testid `remove-btn`.
- Header **Clear expired (N)** bulk button when N>0 (`clear-expired-btn`), confirm → purge → refetch.
- After mutation the page refetches; pending badge / counts reconcile from server truth.

## FEAT-B2 — Move applications between stages

**Data model (tracker-lib.ts):** 8 columns; first 3 Job-status-fed
(`discovered→discovered`, `screening|matched→evaluating`, `tailoring→tailoring`),
last 5 Application-status-fed (`draft→ready`, `submitted→submitted`, `screening→in-review`,
`interview→interview`, `offer→offer`). Job cards only shown when the job has no application.

### API (follows the router's action-POST convention, cf. `/{id}/submit`)
- `POST /applications/{application_id}/move` body `{"to_stage": "<stageKey>"}`.
  - Legal matrix: any move **between the 5 application-fed stages** (`ready`, `submitted`,
    `in-review`, `interview`, `offer`) — forward and backward; the user is the source of truth
    for their own pipeline. Same-stage = idempotent no-op returning the row.
  - 422: unknown stage key; job-fed target (`discovered|evaluating|tailoring` —
    those columns are Job-status-fed); source application is closed (`rejected|withdrawn`).
  - 404 unknown/foreign id. Audit `application.stage_move` (detail: from/to status + stage keys).
- `POST /applications/pipeline/{job_id}/move` for **job cards** (so EVERY card can move):
  body `{"to_stage"}` with a job-fed target → `Job.status` update
  (`discovered→discovered`, `evaluating→screening`, `tailoring→tailoring`).
  App-fed target → 422 (an application must exist first). 404 unknown/foreign job;
  409 if the job already has an application (card would not be on a job-fed column).
  Audit `job.stage_move`.
- Sankey (`/funnel/sankey`) is computed live per request from statuses (cumulative model) —
  no denormalised counters to desync; tests assert non-negative dropoffs + exact counts after moves.

### Frontend (dashboard/applications)
- Cards `draggable`; columns accept HTML5 dragover/drop → move API.
- Per-card accessible **Move to…** menu (same role=menu/menuitemradio pattern as the page's
  HeaderMenu) — keyboard/SR operable; app cards list the 5 app stages, job cards the 3 job stages.
- Optimistic column move with rollback + error banner on API failure; `load()` refetch reconciles counts.

## Test plan (written FIRST, confirmed RED)
- `apps/api/tests/test_approvals_delete.py` — delete/purge matrix incl. authz, idempotency,
  audit rows, non-expired-pending protection.
- `apps/api/tests/test_applications_move.py` — legal/illegal matrix, authz, idempotent same-stage,
  audit fields, sankey integrity after moves, job-card move endpoint.
- `apps/web/e2e/launch-b1-approvals-remove.spec.ts`, `launch-b2-move-stage.spec.ts` — vs prod
  (default config): remove one card, clear-expired affordance, menu move + drag move, reload
  persistence, counter reconciliation; illegal move 422 asserted via API request context
  (the menu never offers illegal targets by construction — honest note).
