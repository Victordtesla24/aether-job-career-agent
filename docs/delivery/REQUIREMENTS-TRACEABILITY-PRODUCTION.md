# Aether Career Agent — Requirements-to-Production Traceability Matrix

**Generated:** 2026-07-12 04:30 UTC | **Branch:** main | **Production:** https://5cb5f0620.abacusai.cloud
**Login:** demo@aether.dev / AetherDemo1 | **Source:** docs/delivery/TRACEABILITY-MATRIX.md, DECISIONS.md, PROGRESS.md, FINAL-REPORT-PHASE-2-AUDIT.md

## Legend
| Verdict | Meaning |
|---|---|
| ✅ WIRED | Rendered + backend round-trips with real data |
| 🔧 FIXED | Was broken, fixed this session on main |
| ⚠️ PARTIAL | Functional but missing wireframe elements |
| ⏭ DEFERRED | Out of Phase-2 scope per docs |

---

## REQUIREMENTS MATRIX WITH CODE MAPS

### REQ-1: Authentication & Login
**Doc ref:** D-0006, PHASE-2-REVIEW §4, FINAL-REPORT §3 J7
**Wireframe:** (implied by all screens)

| Requirement | Code | Status |
|---|---|---|
| Demo login with prefilled credentials | `apps/web/src/app/login/page.tsx` — form with demo@aether.dev/AetherDemo1 | ✅ WIRED |
| JWT session via bearer token | `apps/api/app/routers/auth.py` — `POST /auth/login` returns access_token, 24h expiry | ✅ WIRED |
| CurrentUser dependency guards routes | `apps/api/app/middleware/auth.py` — get_current_user bearer dependency | ✅ WIRED |
| Bad password shows error | Login page inline alert rendering | ✅ WIRED |

### REQ-2: Dashboard
**Doc ref:** TRACEABILITY-MATRIX row 10, D-0002, D-0003
**Wireframe:** `design/screens/dashboard.html` (design-ids: stats-row-p7q8r9, sidebar-main-a1b2c3, etc.)

| Element | Code | Status |
|---|---|---|
| 12-item Schema-A sidebar | `apps/web/src/components/sidebar.tsx` — nav items with FontAwesome icons | ✅ WIRED |
| Stats row (4 cards) | `apps/web/src/components/dashboard/DashboardStats.tsx` — fetches /analytics/funnel + /jobs + /applications | ✅ WIRED |
| Agent Activity feed | `apps/web/src/app/dashboard/page.tsx` — agent-feed section with live filters | ✅ WIRED |
| Today's Opportunities (3 job cards) | Dashboard page — real jobs from /api/jobs | ✅ WIRED |
| Application Funnel widget | Dashboard page — real data from /api/analytics/funnel (112/2/0/0/0) | ✅ WIRED |
| Story Bank widget | Dashboard page — links to /dashboard/stories, shows 24 stories | ✅ WIRED |
| Recruiter CRM widget | Dashboard page — links to /dashboard/networking | ✅ WIRED |
| Needs Approval widget | Dashboard page — links to /dashboard/approvals, shows pending count | ✅ WIRED |
| Market Pulse panel | `apps/web/src/components/analytics/MarketPulse.tsx` — 8 sub-panels | ✅ WIRED |
| Funnel = real data (not 847/412) | `apps/api/app/routers/applications.py:27-63` — funnel_sankey() queries live DB | 🔧 FIXED (this session) |

### REQ-3: Job Discovery
**Doc ref:** TRACEABILITY-MATRIX row 1, D4
**Wireframe:** `design/screens/job-discovery.html` (49 elements, design-ids jd01–jd49)

| Element | Code | Status |
|---|---|---|
| Market tabs (AU/Intl/Saved) | `apps/web/src/app/dashboard/jobs/page.tsx` — market tabs with live counts | ✅ WIRED |
| Source bar (connected job boards) | Jobs page — per-source counts from /api/jobs | ✅ WIRED |
| Source filter dropdown | Jobs page — filters by source (Seek, LinkedIn, Indeed, etc.) | ✅ WIRED |
| Job list with cards | Jobs page — real jobs from `GET /api/jobs` | ✅ WIRED |
| Job detail panel + insights | `apps/api/app/routers/jobs.py:267-273` — /jobs/{id}/insights, 10-dim fit | ✅ WIRED |
| Match score rings (SVG) | Jobs page — MatchRing component, colored by score | ✅ WIRED |
| Save/bookmark toggle | `apps/api/app/routers/jobs.py:276-281` — POST /jobs/{id}/save persists | ✅ WIRED |
| "Sync Now" (Run Scout) button | Jobs page — POST /agents/scout/run → 202 | ✅ WIRED |
| Per-job "Tailor Resume" link | `apps/web/src/app/dashboard/jobs/page.tsx:361` — deep link to /dashboard/resume | ✅ WIRED |
| Two-step apply flow (Tailor → Review → Submit) | Jobs page — startTailoring() → openGate() → confirmSubmit() | ✅ WIRED |
| Submit confirmation gate (modal) | Jobs page — gateOpen/gateJobId/confirmSubmit | ✅ WIRED |
| Real seek.com.au data | `apps/api/app/services/discovery/seek_adapter.py` — Seek adapter with live HTTP | ✅ WIRED |
| Fit scoring per job | `apps/api/app/agents/fit_scorer.py` + ATSEngine in `apps/api/app/services/ats_engine.py` | ✅ WIRED |
| Skill gap/keyword tags | Jobs page — matchedSkills/missingSkills from insights | ✅ WIRED |

### REQ-4: Resume Studio
**Doc ref:** TRACEABILITY-MATRIX row 2, D5, D-0015, D-0018
**Wireframe:** `design/screens/resume-studio.html`

| Element | Code | Status |
|---|---|---|
| Resume version list | `apps/api/app/routers/resumes.py:16-18` — GET /resumes | ✅ WIRED |
| Version diff (before/after) | `apps/api/app/routers/resumes.py:69-91` — /resumes/{id}/diff with evidenceRef | ✅ WIRED |
| Tailor against a job | `apps/api/app/agents/tailor_agent.py:63-93` — TailoringAgent.run() | ✅ WIRED |
| Fabrication guard (no invented metrics) | `apps/api/app/services/resume_tailor.py:149-192` — unsupported_tokens() | ✅ WIRED |
| Evidence grounding | `apps/api/app/services/resume_tailor.py:237-257` — _validate() checks evidenceRef | ✅ WIRED |
| Format hash preservation | `apps/api/app/services/resume_parser.py:16-119` — SHA-256 of raw PDF bytes | ✅ WIRED |
| PDF download (side-by-side comparison) | `apps/api/app/routers/resumes.py:92-166` — GET /resumes/{id}/download → 2-page PDF | 🔧 FIXED (this session, was 501) |
| Base resume immutable | `apps/api/app/agents/tailor_agent.py:85` — formatHash carried through, source never touched | ✅ WIRED |
| Multiple resume roots | `apps/api/app/routers/resumes.py:20-67` — POST /resumes ingest endpoint | ✅ WIRED |

### REQ-5: Story Bank
**Doc ref:** TRACEABILITY-MATRIX row 3, D6
**Wireframe:** `design/screens/story-bank.html`

| Element | Code | Status |
|---|---|---|
| Story list with categories | `apps/web/src/app/dashboard/stories/page.tsx` — STAR cards, filter by category | ✅ WIRED |
| Story extraction from resume | `apps/api/app/agents/story_extractor.py` — mines STAR stories from resume text | ✅ WIRED |
| Manual create/edit STAR form | `apps/web/src/components/stories/story-form.tsx` | ✅ WIRED |
| Story stats (total, quantified, starred) | Stories page — live stats from API | ✅ WIRED |
| Copy to clipboard | Stories page — Insert button per story | ✅ WIRED |

### REQ-6: Application Tracker
**Doc ref:** TRACEABILITY-MATRIX row 4, D2, D7
**Wireframe:** `design/screens/application-tracker.html` (25 elements, design-ids at01–at41)

| Element | Code | Status |
|---|---|---|
| 8-stage kanban board | `apps/web/src/app/dashboard/applications/page.tsx` — board view with stages | ✅ WIRED |
| Board/Sankey/Timeline views | Applications page — view tabs | ✅ WIRED |
| Auto-apply warning banner | Applications page — yellow shield banner | ✅ WIRED |
| Pending approvals banner | Applications page — links to /dashboard/approvals | ✅ WIRED |
| Filter/Sort controls | `apps/web/src/components/applications/tracker-lib.ts` — FilterKey/SortKey | ✅ WIRED |
| Real application data | `apps/api/app/routers/applications.py:61-83` — GET /applications joined with Job | ✅ WIRED |
| Sankey flow (real data) | `apps/api/app/routers/applications.py:27-63` — funnel_sankey() real DB query | 🔧 FIXED (this session) |
| Email/CRM cross-links on cards | `apps/web/src/app/dashboard/applications/page.tsx:189-218` — CardLink component | ✅ WIRED |
| Detail panel on card click | Applications page — openDetail() fetches /applications/{id} | ✅ WIRED |
| Submit application | `apps/api/app/routers/applications.py:108-149` — POST /applications/{id}/submit | ✅ WIRED |

### REQ-7: Cover Letter Studio
**Doc ref:** TRACEABILITY-MATRIX row 6, D1, D3
**Wireframe:** `design/screens/cover-letter-studio.html`

| Element | Code | Status |
|---|---|---|
| Job selector dropdown | `apps/web/src/app/dashboard/cover-letters/page.tsx` — real job list | ✅ WIRED |
| LLM-generated cover letters | `apps/api/app/agents/cover_letter_agent.py:50-143` — CoverLetterAgent | ✅ WIRED |
| Fabrication guard on letters | `apps/api/app/agents/cover_letter_agent.py:84` — guard.check() per draft | ✅ WIRED |
| Corrective drafting loop | `apps/api/app/agents/cover_letter_agent.py:107-119` — ≤3 drafts with flag terms fed back | ✅ WIRED |
| Approval gate (pending) | `apps/api/app/agents/cover_letter_agent.py:124-136` — ApprovalRequest created | ✅ WIRED |
| Evidence grounding % | Cover letters page — shows "75% grounded" | ✅ WIRED |
| PDF export | `apps/api/app/routers/cover_letters.py:347-400` — GET /cover-letters/{id}/pdf (reportlab) | ✅ WIRED |

### REQ-8: Approvals
**Doc ref:** TRACEABILITY-MATRIX row 5, D2, D8
**Wireframe:** `design/screens/approval-modal.html`

| Element | Code | Status |
|---|---|---|
| Pending approval queue | `apps/web/src/app/dashboard/approvals/page.tsx` — list with approve/reject | ✅ WIRED |
| Approve/Reject buttons | Approvals page + `apps/api/app/routers/approvals.py` — POST approve/reject | ✅ WIRED |
| Status filter (Pending/Approved/Rejected/All) | Approvals page — filter tabs | ✅ WIRED |
| 48h expiry badge | `apps/api/app/services/approval_service.py` — expiry checks, disabled actions | ✅ WIRED |
| Approval→Application sync | `apps/api/app/services/approval_service.py` — _sync_application() | ✅ WIRED |

### REQ-9: Agents & Monitor
**Doc ref:** TRACEABILITY-MATRIX rows 7-8, D1
**Wireframe:** `design/screens/agents.html` + `design/screens/agent-monitor.html`

| Element | Code | Status |
|---|---|---|
| 21-agent catalog grid | `apps/web/src/app/dashboard/agents/page.tsx` — AgentConfigGrid + catalog | ✅ WIRED |
| 6 AI provider cards | `apps/web/src/components/agents/ProviderConnections.tsx` | ✅ WIRED |
| Agent run history | `apps/api/app/routers/agents.py:378-388` — GET /agents/runs | ✅ WIRED |
| Pipeline trigger (Run All) | `apps/api/app/routers/agents.py:476-484` — POST /agents/pipeline/run | ✅ WIRED |
| Real cost estimate per run | `apps/api/app/routers/agents.py:248-264` — token count × per-model pricing | ✅ WIRED |
| Agent status (active/paused/idle) | Agents page — live status from /api/agents | ✅ WIRED |

### REQ-10: Analytics
**Doc ref:** TRACEABILITY-MATRIX row 9, D9
**Wireframe:** `design/screens/analytics.html`

| Element | Code | Status |
|---|---|---|
| Funnel chart with period selector | `apps/web/src/app/dashboard/analytics/page.tsx` — 7d/30d/90d/all tabs | ✅ WIRED |
| ATS score distribution | `apps/api/app/routers/analytics.py` — GET /analytics/ats-distribution | ✅ WIRED |
| Agent ROI panel | `apps/api/app/routers/analytics.py` — GET /analytics/agent-roi | ✅ WIRED |
| Stage conversion rates | `apps/api/app/routers/analytics.py` — GET /analytics/conversion → rendered on page | ✅ WIRED |
| Real-time market pulse | `apps/web/src/components/analytics/MarketPulse.tsx` | ✅ WIRED |

---

## DEFERRED SCREENS (Out-of-Phase per docs)

| Screen | Deferral evidence |
|---|---|
| Interview Center | TRACEABILITY-MATRIX row 13: "Interview prep flows deferred" |
| Networking CRM | TRACEABILITY-MATRIX row 14: "Contact/networking CRM deferred" |
| Offers | TRACEABILITY-MATRIX row 15: "Offer-stage tooling deferred" |
| Email Center | TRACEABILITY-MATRIX row 12: "Phase 3+ scope" |
| Settings | TRACEABILITY-MATRIX row 16: "Settings/profile management deferred" |
| Mobile (approval/dashboard) | TRACEABILITY-MATRIX row 17: "Mobile parity explicitly deferred" |

---

## DEFECTS FIXED THIS SESSION

| ID | Severity | Defect | Fix | Code |
|---|---|---|---|---|
| SA-01 | HIGH | Sankey funnel hardcoded 847/412/156/23/4 | Real DB query | `apps/api/app/routers/applications.py:27-63` |
| SA-02 | MED | Resume PDF download returned 501 | Real side-by-side PDF via reportlab | `apps/api/app/routers/resumes.py:92-166` |
| SA-03 | MED | Interview Center crashed on null session | Null guard with empty state | `apps/web/src/app/dashboard/interviews/page.tsx:39-54` |
| SA-04 | MED | Email Center crashed on null recruiterProfile | Null guard | `apps/web/src/app/dashboard/email/page.tsx:386-396` |

---

## QUALITY GATES

| Gate | Result | Command |
|---|---|---|
| Pytest | 200 passed (baseline) | `pytest apps/api/tests/ -q` |
| Vitest | 135 passed | `pnpm vitest run` |
| Playwright E2E | 24 tests | `pnpm playwright test` |
| Ruff | Clean | `ruff check app/` |
| Mypy | 55 files, no issues | `mypy app/ --ignore-missing-imports` |
| ESLint | 0 warnings, 0 errors | `next lint` |
| TSC (TypeScript) | 0 issues | `tsc --noEmit` |
| Build | Clean | `pnpm build` |
| Production | 200 OK | `curl https://5cb5f0620.abacusai.cloud/` |

---

## CODE MAP — KEY FILES

```
apps/api/app/
  routers/
    applications.py  — tracker API + sankey funnel
    jobs.py          — job discovery API + insights
    resumes.py       — resume CRUD + diff + PDF download
    cover_letters.py — cover letter CRUD + PDF export
    agents.py        — agent catalog, runs, pipeline
    approvals.py     — approval gate state machine
    analytics.py     — funnel, ATS distribution, ROI, conversion
    auth.py          — JWT auth endpoints
    workspaces.py    — interview/networking/email/offers/settings
    stories.py       — story bank CRUD
  agents/
    tailor_agent.py       — resume tailoring
    cover_letter_agent.py — cover letter generation
    fit_scorer.py         — ATS fit scoring
    scout_agent.py        — job discovery
    story_extractor.py    — resume→story extraction
  services/
    resume_tailor.py      — bullet rewriting + fabrication guard
    fabrication_guard.py  — entity claim verification
    llm_client.py         — record-replay LLM with budget caps
    ats_engine.py         — keyword match + semantic similarity
    resume_parser.py      — PDF text extraction + format hash

apps/web/src/
  app/dashboard/
    page.tsx           — Dashboard home
    jobs/page.tsx      — Job Discovery (1168 lines)
    resume/page.tsx    — Resume Studio
    stories/page.tsx   — Story Bank
    applications/page.tsx — Application Tracker (667 lines, 8-stage kanban)
    agents/page.tsx    — Manage Agents (417 lines, 21 agents)
    approvals/page.tsx — Approval queue
    cover-letters/page.tsx — Cover Letter Studio
    analytics/page.tsx — Analytics dashboard
    interviews/page.tsx — Interview Center (null-safe)
    networking/page.tsx — Networking CRM
    email/page.tsx     — Email Center (null-safe)
    offers/page.tsx    — Offer Comparison
    settings/page.tsx  — Settings & Profile
  components/
    sidebar.tsx        — 12-item Schema-A sidebar
    applications/      — tracker-lib, tracker-api, SankeyFlow
    agents/            — AgentConfigGrid, ProviderConnections, TestRunModal
    approvals/         — ApprovalModal, api, lib
    cover-letters/     — EvidenceTracePanel, VoiceDnaPanel, VersionsPanel
    analytics/         — MarketPulse
    offers/            — OfferCard, EmptyState, PriorityWeights
    stories/           — story-card, story-form, story-aside
    dashboard/         — DashboardStats
  lib/api/
    client.ts          — apiRequest helper with demo auto-login
    jobs.ts, resumes.ts, stories.ts, workspaces.ts, applications.ts,
    agents.ts, analytics.ts, approvals.ts, coverLetters.ts
```
