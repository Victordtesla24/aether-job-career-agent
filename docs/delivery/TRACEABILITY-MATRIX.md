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

---

## Phase 6 — Requirements → Evidence Matrix (Subscription/Billing/Admin/Sourcing-Compliance/Quality, 2026-07-16)

**Method:** each Phase-6 gap in `docs/delivery/phase6-gap-analysis.json` is mapped to the production
evidence artifact that verifies it (all under `uat/reports/evidence/phase6/` unless noted). Status values
are copied verbatim from the machine ledger, not re-derived — this table does not itself close any gate
(gate closure is the QA/reviewer sub-agent's sole authority).

| Gap | Requirement | Status | Gate(s) | Evidence artifact |
|---|---|---|---|---|
| GAP-P6-BILL-001 | Subscription/billing architecture (schema, endpoints, GST, webhook) | FIX-READY-MERGED (live verify blocked-on-human) | GATE-13/14/15/16/33/34 | `review-billing.json`, `docs/subscription/billing-architecture.md` |
| GAP-P6-BILL-002 | Per-user LLM spend-cap / agent-run quota enforcement | FIX-READY-MERGED | GATE-17 | `review-billing.json` (checklist item 4), `deploy-verify.json` |
| GAP-P6-PRICING-001 | Public `/pricing` page | FIX-READY-MERGED | GATE-13 | `deploy-verify.json` (`pricing` endpoint 200) |
| GAP-P6-ADMIN-001 | Admin panel (users, spend, health, settings) | PROD-FLOW-VERIFIED / GATE-17-human-gated | GATE-17 | `review-admin.json`, `gate17-admin-verification-raw.json` |
| GAP-P6-ADMIN-003 | Audit log + per-user data export/delete | PROD-FLOW-VERIFIED / GATE-17-human-gated | GATE-17 | `review-admin.json` (checklist item 4), `gate17-admin-verification-raw.json` (`audit_log_test`) |
| GAP-P6-SEC-001 | `admin/admin123` must not hold admin privilege | VERIFIED-CLOSED | GATE-31, GATE-17 | `review-admin.json` (checklist item 5), `deploy-verify.json` (`admin_rotation_gate_31`) |
| GAP-P6-SRC-001 | Job-sourcing volume ≥25, ≥2 sources with ≥5 each | VERIFIED-CLOSED | GATE-07, GATE-08 | `qa-prod-sourcing.json` (`gate07`) |
| GAP-P6-SRC-002 | Seek adapter ToS-prohibited scraping removed | VERIFIED-CLOSED | GATE-07, GATE-08 | `qa-prod-sourcing.json` (`seek_verification`), `seek-tos-check.md`, `review-sourcing.json` |
| GAP-P6-DATA-001 | Stale/unreachable Seek cards not shown to users | VERIFIED-CLOSED | GATE-08 | `qa-prod-sourcing.json` (`gate08`) |
| GAP-P6-WIRE-001 | Dead/decorative view-toggle controls wired | VERIFIED-CLOSED | GATE-03 | `qa-prod-console-admin.json` |
| GAP-P6-AGCONF-001 | All runtime agents PUT-config + billing routing | VERIFIED-CLOSED | GATE-06 | `probe-16-agent-keys.json` |
| GAP-P6-AUTH-OAUTH-001 | Anthropic OAuth API-key-only + flag-gated | VERIFIED-CLOSED | GATE-04 | `anthropic-oauth-verification.md` |
| GAP-P6-MULTI-001 | Multi-Gmail inbox (simultaneous accounts, `select_account`) | CODE-VERIFIED-CLOSED / LIVE-BLOCKED-ON-HUMAN | GATE-05 | `docs/delivery/phase6-gap-analysis.json` (code-level tests only; live 2nd-account consent pending) |
| GAP-P6-TAIL-001 | Resume tailoring craft (writer-audit) | VERIFIED-CLOSED | GATE-09, GATE-10 | `qa-prod-craft5.json` |
| GAP-P6-COV-001 | Cover-letter craft (writer-audit) | VERIFIED-CLOSED | GATE-11, GATE-12 | `qa-prod-craft2.json`, `review-quality.json` |
| GAP-P6-CONV-001 | Conversion-estimate label + methodology + tooltip | VERIFIED-CLOSED | GATE-10 | `qa-prod-craft2.json`, `qa-prod-craft5.json` (`methodology_present`) |
| GAP-P6-MET-001 | Metric recomputation delta, user-scoped | VERIFIED-CLOSED | GATE-18 | `user-scoped-sql-recompute.txt` |
| GAP-P6-AUTH-002 | Fixture-fallback removed from live-failure path | VERIFIED-CLOSED | GATE-02, GATE-09, GATE-11 | `review-authenticity2.json` |
| GAP-P6-TAIL-002 | Cross-context keyword-bleed / raw_text regeneration | VERIFIED-CLOSED | GATE-09 | `review-authenticity2.json` (checklist items 4–5) |
| GAP-P6-TAIL-003 | Entailment verification eliminates fabrication | VERIFIED-CLOSED | GATE-09 | `qa-prod-craft3.json`, `review-tail3.json` |
| GAP-P6-DOCS-002 | Live `/privacy-policy` + `/terms` honesty (GST/subscription terms, no false self-service-deletion claim) | VERIFIED-CLOSED | GATE-19 | `docs/subscription/privacy-policy.md`, `docs/subscription/terms-of-service.md` |
| GAP-P6-TAIL-004 | Dedicated entailment budget + anchor-collision fix | VERIFIED-CLOSED | GATE-09 | `review-tail4.json` |
| GAP-P6-TAIL-005 | Top-K batch cap + scaled entailment budget → genuine lift | VERIFIED-CLOSED | GATE-09 | `qa-prod-craft5.json`, `review-tail5.json` |
| GAP-P6-REPO-002 | Stale branches / open PRs cleaned up | TRIAGED (Cluster H, deployer) | GATE-21, GATE-22 | `probe-11-branches.txt`, `probe-11-prs.json` |
| GAP-P6-DIR-001 | Monorepo directory reorganisation | TRIAGED (Cluster H, fixer-medium) | — | `inventory-backend.json`, `inventory-frontend-docs.json` |
| GAP-P6-DOCS-001 | Docs updated to post-implementation truth + `docs/subscription/` created | TRIAGED → in progress this update (doc-updater) | GATE-19, GATE-20 | `docs/subscription/*.md` (this update), `inventory-frontend-docs.json` |
| GAP-P6-EXEC-001 | `EXECUTION-REPORT.md` claims re-verified, honest agent-count wording | TRIAGED → in progress this update (doc-updater) | GATE-28 | `EXECUTION-REPORT.md` §9 (this update), `probe-16-agent-keys.json` |

**Honest backlog (not gap-tracked, non-blocking):** `BACKLOG-P6-01` (per-run Cost column absent from
`/dashboard/agents` Recent Runs table) and `BACKLOG-P6-02` (~20% honest tailoring/cover-letter 503 rate,
durable fix is async generation) — both recorded in `docs/delivery/phase6-gap-analysis.json`'s `backlog`
array, deliberately out of Phase 6 scope.
