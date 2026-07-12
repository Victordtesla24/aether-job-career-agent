# Phase-2 Traceability Matrix — Wireframe ↔ Backend Wiring Audit

**Date:** 2026-07-09 · **Branch:** `phase-2/intelligence` · **Production:** https://5cb5f0620.abacusai.cloud
**Method:** adversarial live audit against production — every wireframe in `design/screens/` was mapped
to its implemented route, and every implemented control was exercised in a real browser (Playwright,
30-step scripted run; raw evidence in the audit evidence archive: `audit-results.json`, `audit-run.log`,
screenshots, and DB before/after snapshots). Verdicts were assigned **only** from observed behaviour.

**Verdict legend**

| Verdict | Meaning |
|---|---|
| WIRED ✅ | Rendered on production AND the control round-trips to a real backend endpoint with observed effect |
| RENDERED-BUT-DEAD ⚠️ | Visible on production but no backend call / no observable effect (defects filed) |
| MISSING ❌ | In the wireframe and in Phase-2 scope but not rendered at all (defects filed) |
| OUT-OF-PHASE ⏭ | In the wireframe but explicitly deferred beyond Phase 2 — no defect |

All ⚠️/❌ items found by the audit were fixed in this pass and re-verified live —
see `DEFECTS-PHASE-2-AUDIT.md` (D1–D9) for before/after evidence. Verdicts below are **post-fix**.

## Matrix (17 wireframes)

| # | Wireframe (`design/screens/`) | Implemented route | Verdict | Live proof (production) |
|---|---|---|---|---|
| 1 | `job-discovery.html` | `/dashboard/jobs` | WIRED ✅ | 847 jobs listed via `GET /api/jobs`; status/saved filters change result set; Save toggle persists (`POST /api/jobs/{id}/save`); "Run Scout" → 202 + new discoveries; fit scores render. Audit J1 steps 5–12. Per-job "Tailor Resume →" deep link added (was MISSING ❌ — defect D4, fixed). |
| 2 | `resume-studio.html` | `/dashboard/resume` | WIRED ✅ | Tailor run → `POST /api/agents/tailor/run` 200, 20 accepted changes; version list + diff view from `GET /api/resumes`, `/api/resumes/{id}/diff`. Download button (was MISSING ❌ — D5, fixed): `POST /api/resumes/{id}/download` → 501 handled with "coming in Phase 3" note (`reverify-D5-resume.png`). |
| 3 | `story-bank.html` | `/dashboard/stories` | WIRED ✅ | Extractor run 21→33 stories (`POST /api/agents/story-extractor/run`). Manual create/edit STAR form (was MISSING ❌ — D6, fixed): live create verified end-to-end on production (`reverify-D6-stories.png`, story persisted via `POST /api/stories`). |
| 4 | `application-tracker.html` | `/dashboard/applications` | WIRED ✅ | Kanban renders from `GET /api/applications`. Detail panel + pending-approvals banner (was MISSING ❌ — D7, fixed) verified live. Approve/reject now moves the linked application draft→submitted/rejected (was RENDERED-BUT-DEAD ⚠️ — D2, fixed; DB before/after in `reverify-D2.txt`). |
| 5 | `approval-modal.html` | `/dashboard/approvals` | WIRED ✅ | Pending queue from `GET /api/approvals?status=pending`; approve/reject → `POST /api/approvals/{id}/approve|reject` with observed DB effect (audit J4 + `reverify-D2.txt`). 48-h expiry badge + disabled actions added (was MISSING ❌ — D8, fixed). |
| 6 | `cover-letter-studio.html` | `/dashboard/cover-letters` | WIRED ✅ | Letters listed; generation via `POST /api/agents/cover-letter/run` — previously 524 timeout (D1 ❌), now 200 in ≈60 s on production (`reverify-D1.txt`). Wrong-company fixture contamination fixed (D3). |
| 7 | `agents.html` | `/dashboard/agents` | WIRED ✅ | Agent cards + run history from `GET /api/agents/runs`; pipeline trigger `POST /api/agents/pipeline/run` — previously 524 (D1 ❌), now 200 in ≈62 s (`reverify-D1-pipeline.txt`). |
| 8 | `agent-monitor.html` | `/dashboard/agents` (merged) | WIRED ✅ | Run log (status, duration, output) rendered from `AgentRun` rows; verified during audit steps 20–22. Merged into the agents screen — acceptable consolidation, no dead controls. |
| 9 | `analytics.html` | `/dashboard/analytics` | WIRED ✅ | Funnel 847/412/156/23/4 (`period=all`) and 205/105/39/8/1 (`30d`) from `GET /api/analytics/funnel`; ATS distribution + agent ROI wired. Stage-conversion endpoint had no UI consumer (D9 ⚠️ — fixed): conversion rates now render and re-fetch on period change (`reverify-D9-analytics.png`). |
| 10 | `dashboard.html` | `/dashboard` | WIRED ✅ | Live stat tiles hydrate from `/api/jobs`, `/api/applications`, `/api/approvals` (audit step 4; vitest `live-stats.test.ts`). |
| 11 | *(login — implied by all screens)* | `/login` | WIRED ✅ | Demo login → JWT; bad password → visible error; session persists across reload (audit J7 steps 1–3). |
| 12 | `email-center.html` | — | OUT-OF-PHASE ⏭ | Email/outreach agent is Phase 3+ scope; no backend routes exist (`openapi.json` — 37 routes, none email-related). Not rendered, correctly absent from nav. |
| 13 | `interview-center.html` | — | OUT-OF-PHASE ⏭ | Interview prep flows deferred (PROGRESS.md "Deferred to later phases"). No routes/UI. |
| 14 | `networking.html` | — | OUT-OF-PHASE ⏭ | Contact/networking CRM deferred. `Contact` table exists but has no Phase-2 routes/UI. |
| 15 | `offer-comparison.html` | — | OUT-OF-PHASE ⏭ | Offer-stage tooling deferred; funnel tracks offers as counts only. |
| 16 | `settings.html` | — | OUT-OF-PHASE ⏭ | Settings/profile management deferred; auth is fixed demo user in Phase 2. |
| 17 | `mobile-approval.html` / `mobile-dashboard.html` | — | OUT-OF-PHASE ⏭ | Mobile parity explicitly deferred (PROGRESS.md). Desktop approval/dashboard flows cover the functionality. |

## Backend route coverage (reverse direction)

All **37 routes** in the production `openapi.json` were enumerated and mapped to frontend callers.
After fixes, every user-facing route has a real UI consumer; no frontend client calls a phantom
endpoint. Notable reverse-direction findings, all resolved:

- `GET /analytics/conversion` — had **no** UI consumer (D9) → now consumed by the analytics page.
- `GET /applications/{id}` — had no UI consumer → now backs the application detail panel (D7).
- `POST /resumes/{id}/download` — 501 stub unreferenced → now wired with graceful 501 handling (D5).
- `POST /stories`, `PUT /stories/{id}` — had no UI consumer → now back the Story Bank create/edit form (D6).

Intentionally UI-less routes: `/health`, `/auth/login` (used by the login page), and the
`DELETE /stories/{id}` route (wired to the existing per-card delete button).

## Journey verdicts (J1–J7, post-fix)

| Journey | Result | Evidence |
|---|---|---|
| J1 Discover → save → fit score | ✅ | audit steps 5–12, `audit-results.json` |
| J2 Tailor resume + review diff | ✅ | tailor 200, 20 changes; diff renders |
| J3 Generate cover letter | ✅ (was ❌ D1) | `reverify-D1.txt` — 200 in 60.3 s |
| J4 Approve/reject → application state | ✅ (was partial, D2) | `reverify-D2.txt` — draft→submitted / draft→rejected in DB |
| J5 Story extraction + manual add | ✅ (was partial, D6) | 21→33 extracted; live manual create verified |
| J6 Analytics funnel + conversion | ✅ (D9 fixed) | funnel counts consistent; conversion rates render |
| J7 Auth (login/bad password/persist) | ✅ | audit steps 1–3 |
