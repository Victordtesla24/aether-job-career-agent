# FINAL REPORT — Phase-2 Adversarial Audit, Fix Loop & BA Resume Delivery

**Date:** 2026-07-10 · **Branch:** `phase-2/intelligence` · **Production:** https://5cb5f0620.abacusai.cloud
**PR:** #2 (`phase-2/intelligence` → `main`) — updated, **never merged**.
Raw evidence archive: `/home/ubuntu/aether_audit_evidence/` (curl transcripts `reverify-*.txt`,
DB before/after snapshots, screenshots `shots/reverify-*.png`, `audit-results.json`, `audit-run.log`).

---

## 1. Traceability summary — every wireframe

Full matrix with live proof per row: `docs/delivery/TRACEABILITY-MATRIX.md`. Method: adversarial
live audit on production — 17 wireframes in `design/screens/` mapped to implemented routes; every
control exercised in a real browser (30-step Playwright run); all 37 API routes in the production
`openapi.json` reverse-mapped to UI consumers. Verdicts below are **post-fix**.

| # | Wireframe | Route | Verdict |
|---|---|---|---|
| 1 | job-discovery.html | /dashboard/jobs | WIRED ✅ (D4 fixed: per-job Tailor deep link) |
| 2 | resume-studio.html | /dashboard/resume | WIRED ✅ (D5 fixed: Download w/ graceful 501) |
| 3 | story-bank.html | /dashboard/stories | WIRED ✅ (D6 fixed: manual STAR create/edit) |
| 4 | application-tracker.html | /dashboard/applications | WIRED ✅ (D2, D7 fixed) |
| 5 | approval-modal.html | /dashboard/approvals | WIRED ✅ (D8 fixed: 48-h expiry badge) |
| 6 | cover-letter-studio.html | /dashboard/cover-letters | WIRED ✅ (D1, D3 fixed) |
| 7 | agents.html | /dashboard/agents | WIRED ✅ (D1 fixed: pipeline 524→200) |
| 8 | agent-monitor.html | /dashboard/agents (merged) | WIRED ✅ |
| 9 | analytics.html | /dashboard/analytics | WIRED ✅ (D9 fixed: conversion rates rendered) |
| 10 | dashboard.html | /dashboard | WIRED ✅ |
| 11 | login (implied) | /login | WIRED ✅ |
| 12–17 | email-center, interview-center, networking, offer-comparison, settings, mobile-* | — | OUT-OF-PHASE ⏭ (explicitly deferred; no dead UI) |

Reverse direction: after fixes, **all 37 routes** have real UI consumers or are intentionally
UI-less (`/health`, `/auth/login`); no frontend client calls a phantom endpoint. Previously
orphaned routes now consumed: `GET /analytics/conversion` (D9), `GET /applications/{id}` (D7),
`POST /resumes/{id}/download` (D5), `POST /stories` + `PUT /stories/{id}` (D6).

## 2. Defects — root cause → fix → production re-verification

Full log with before/after evidence per defect: `docs/delivery/DEFECTS-PHASE-2-AUDIT.md`.

| ID | Sev | Defect | Root cause | Fix | Prod re-verification proof |
|---|---|---|---|---|---|
| D1 | CRIT | cover-letter & pipeline runs 524 at edge (~100 s); AgentRun rows 133–157 s vs 60 s budget | httpx read timeout is per-chunk, not wall-clock; pipeline agents each had an independent budget (additive) | hard wall-clock cap via worker thread + `future.result(timeout)`; `shared_budget()` contextvar deadline across pipeline; provider override env vars (ADR D-0017) | `reverify-D1.txt`: cover-letter **200 in 60.3 s**; `reverify-D1-pipeline.txt`: pipeline **200 in 62.4 s** |
| D2 | HIGH | approve/reject never moved the linked application off `draft` | `ApprovalService.resolve()` flipped only the approval row; `applicationId` FK ignored | `_sync_application()`: approve→submitted, reject→rejected, draft-only guard (ADR D-0016) | `reverify-D2.txt`: DB before/after — draft→submitted and draft→rejected |
| D3 | HIGH | cover-letter retry fixture contained wrong role/company | contaminated recorded fixture replayed verbatim | fixture neutralised; guard test added | pytest fixture-integrity test green |
| D4 | MED | no path from a job card to tailoring (wireframe CTA missing) | link never implemented | per-job "Tailor Resume →" deep link (`/dashboard/resume?job=<id>`) | `reverify-ui.log`: 847 tailor links on prod |
| D5 | MED | resume Download button absent; 501 route orphaned | UI never wired to `POST /resumes/{id}/download` | Download button with graceful 501 "coming in Phase 3" note | `shots/reverify-D5-resume.png` |
| D6 | MED | Story Bank had no manual create/edit (wireframe STAR form missing) | `POST/PUT /stories` had no UI consumer | STAR create/edit form wired | `shots/reverify-D6-stories.png` — live story persisted |
| D7 | MED | application detail panel + pending-approvals banner missing | `GET /applications/{id}` had no consumer | detail panel + banner added | `shots/reverify-D7-*.png` |
| D8 | LOW | approval 48-h expiry badge missing | expiry never surfaced | expiry badge + disabled actions when expired | `shots/reverify-D8-*.png` (0 currently-expired rows — rendering path verified, data-dependent) |
| D9 | LOW | `GET /analytics/conversion` had no UI consumer | endpoint orphaned | stage-conversion rates rendered, re-fetch on period change | `shots/reverify-D9-analytics.png` — 48.88 / 37.68 / 14.74 / 17.39 % |

Also fixed this session (post-audit, found live): atomic approval→application sync hardening +
pending-count preservation on fetch failure (commit `5b5bde0`).

## 3. Journey evidence (J1–J7, post-fix)

| Journey | Result | Evidence |
|---|---|---|
| J1 Discover → save → fit score | ✅ | `audit-results.json` steps 5–12; 847 jobs; save persists; scout 202 |
| J2 Tailor resume + review diff | ✅ | tailor 200, 20 changes; diff renders from `/api/resumes/{id}/diff` |
| J3 Generate cover letter | ✅ (was ❌ D1) | `reverify-D1.txt` — 200 in 60.3 s |
| J4 Approve/reject → application state | ✅ (was partial, D2) | `reverify-D2.txt` — DB draft→submitted / draft→rejected |
| J5 Story extraction + manual add | ✅ (was partial, D6) | 21→33 extracted; live manual create verified |
| J6 Analytics funnel + conversion | ✅ (D9 fixed) | funnel 847/412/156/23/4 (all) & 205/105/39/8/1 (30d); conversion rates render |
| J7 Auth (login / bad password / persist) | ✅ | audit steps 1–3 |

## 4. BA resume — trace summary, format conformance, registration proof

**Deliverable:** `assets/resume/Vik_Resume_BA_Final.pdf` (3 pages) — “VIKRAM DESHPANDE — Senior
Business Analyst / Product Owner”.

**Content traceability (anti-fabrication):** every claim traces to the two source PDFs only.
- From `Vik_Resume_BA.pdf`: career objective (reworded BA/PO-first, same claims), key skills,
  ANZ Senior Delivery Lead/Technical PO (Sept 2017–June 2025) + AI/ML Architect bullets, NAB
  Senior PM & BA, Microsoft Lead BA, Telstra BA/Project Coordinator, InfoCentric Senior BA,
  MYOB, Independent AI Consulting, education (Monash MCS 2010, UniMelb BE 2007), CSM cert,
  AWS/GCP in progress.
- From `Vik_Resume_Final.pdf`: current ATO Scrum Master role (March 2026–Present, 4 bullets),
  NAB “deep-dive business analysis” bullet, Independent role end-date (Feb 2026).
No dates, employers, metrics, tools or achievements were invented.

**Format conformance:** rebuilt programmatically (`scripts/generate_ba_resume.py`, reportlab)
against a measured spec extracted from `Vik_Resume_Final.pdf` with PyMuPDF: US Letter; left rail
x=36/w=154 and main column x=230/w=346; 20.2 pt bold name `#222222`; peach title panel `#FCD9CF`
with coral `#F4715C` subtitle; coral square section icons; 8.7–8.9 pt body `#4D4D4D`; coral
bullets; bold lead-ins `#2B2B2B`; identical section order; 3 pages.
`assets/resume/Vik_Resume_Final.pdf` was **not modified** — md5
`16b856c0f3f4ec0d801fdde6d084452c` verified identical before and after generation.

**Registration proof (production, via the app's own API):**
- New endpoint `POST /resumes` (ADR D-0018) + `scripts/ingest_ba_resume.py` → **201**, root resume
  id `c57a44d136100943494554143`, version 15 (`reverify-C-register.txt`).
- `GET /api/resumes` → **15 resumes, 2 root resumes** (“BA Resume — Senior Business Analyst /
  Product Owner” + “Demo seed resume”) — `reverify-C-list.txt`.
- Resume Studio UI on production shows the BA resume — `shots/reverify-C-resume-studio.png`
  (Playwright also asserted the label is visible on the page).
- **Tailoring run against the BA resume:** `POST /api/agents/tailor/run` with
  `{job_id: c56ebb711ee0a9bbb04a95dae (Staff Engineer @ Canva), resume_id: <BA id>}` → **HTTP 200
  in 44.2 s, 20 accepted changes**; child resume `c39cbf4a6e6d1b3b2fe37787d` parented to the BA
  root with the same `formatHash` (`2df88344d04efe30`) — `reverify-C-tailor.txt` /
  `reverify-C-tailor-full.json`.

## 5. Gate numbers & commit SHAs

Quality gates (final state, after all changes this session):

| Gate | Result |
|---|---|
| pytest (apps/api) | **108 passed**, 0 failed |
| coverage | **89%** (floor 86%) |
| ruff | clean |
| mypy | clean (48 source files) |
| vitest (apps/web) | **47 passed** |
| next lint / tsc --noEmit / next build | clean |
| Playwright e2e | **24 passed** |

Commits pushed to `phase-2/intelligence` (chronological, from `09bc302`):

| SHA | Description |
|---|---|
| `2367518` | fix(api): D1–D3 — hard wall-clock LLM cap + shared pipeline budget + provider override; approval→Application sync; neutralised retry fixture |
| `7f6ed0f` | fix(web): D4–D9 — tailor deep link, download w/ 501 note, story create/edit, application detail + banner, approval expiry, conversion analytics (+9 vitest) |
| `5b5036d` | docs: TRACEABILITY-MATRIX.md + DEFECTS-PHASE-2-AUDIT.md; ADRs D-0016/D-0017; .env.example provider vars |
| `5b5bde0` | fix: atomic approval-application sync + preserve pending count on fetch failure |
| `afddce0` | feat(resume): BA resume PDF, generator, POST /resumes ingestion, tailor resume_id selection (+4 pytest) |
| *(this commit)* | docs: Section C/D closeout — ADR D-0018, PROGRESS update, final report |

## 6. Not verified — exact blockers

1. **Server logs** — `journalctl` for the API unit is empty and the legacy `/tmp` log stale.
   Runtime evidence was gathered from `AgentRun` DB rows and live reproduction instead.
2. **D8 expiry badge with live expired data** — no approval row on production is currently past
   its 48-h window, so the badge was verified via rendering-path inspection + unit tests, not a
   live expired row (data-dependent).
3. **`anthropic/claude-fable-5` via OpenRouter** — the model **exists** on OpenRouter, but a live
   call from this VM returns 404: *“No endpoints available matching your guardrail restrictions
   and data policy. Configure: https://openrouter.ai/settings/privacy”* — the account's privacy /
   data-policy settings block it. Not something the agent can change. Once the account owner
   updates https://openrouter.ai/settings/privacy, enabling it is one line:
   `AETHER_MODEL_REASONING=anthropic/claude-fable-5` in `.env` + `systemctl restart aether-api`.
4. **Anthropic Max subscription auth** — `~/.claude/.credentials.json` holds a Max-plan OAuth
   token but it **expired in May 2026** (`/v1/models` → 401); the OAuth refresh endpoint returns
   403 (Cloudflare error 1010) from this VM, and interactive `claude login` requires the account
   owner. After re-login, the app can point at Anthropic via `AETHER_LLM_BASE_URL` /
   `AETHER_LLM_API_KEY` (ADR D-0017).
5. **PR #2** — body updated with this verification summary; intentionally **not merged** per the
   standing instruction.
