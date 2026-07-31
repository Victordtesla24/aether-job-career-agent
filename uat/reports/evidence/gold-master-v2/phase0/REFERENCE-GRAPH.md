# REFERENCE GRAPH: 9 Flagged Features — Phase 0 Step 5d

**Timestamp:** 2026-07-30T00:00:00Z  
**Repository:** /home/ubuntu/github_repos/aether-job-career-agent (main branch)  
**Production:** https://5cb5f0620.abacusai.cloud

---

## Feature 1: Seek.com.au Sourcing

**Verdict:** PARTIAL (code present, compliance gate active, discovery service/timer not deployed)

### Backend Implementation
- **SeekAdapter class:** `apps/api/app/services/discovery/seek_adapter.py:286` — Firecrawl-based scraper for seek.com.au job listings. Requires `ABACUS_API_KEY` and `FIRECRAWL_API_URL` environment variables.
- **Compliance gate (ADR-P6-SEEK):** `apps/api/app/services/discovery/adapter_registry.py:38` — `COMPLIANCE_GATED` dict maps `"seek"` to `(SeekAdapter, "AETHER_ENABLE_SEEK")`. Seek is ToS-prohibited and excluded by default.
- **Live registry builder:** `apps/api/app/services/discovery/adapter_registry.py:72–79` (`build_live_registry()`) — conditionally includes Seek when `AETHER_ENABLE_SEEK` env var is truthy.
- **Source availability endpoint:** `apps/api/app/services/discovery/adapter_registry.py:101–146` (`source_availability()`) — returns per-source availability list used by frontend (single source of truth per `ML-audit-seek-fe-hardcode-001`).
- **Filter validation:** `apps/api/app/routers/jobs.py:35–66` (`_validate_source_filter()`) — validates `?source=` filter, returns 422 when source unavailable unless `include_stale=true`.
- **Active feed filtering:** `apps/api/app/services/discovery/active_feed.py` — filters out Seek rows (dead source) and >30d stale jobs.
- **Frontend agent endpoint:** `apps/api/app/routers/agents.py` (`scout_source_availability()`) — exposes source availability to frontend.

### Tests
- `apps/api/tests/test_gap_p6_sourcing.py` — `AETHER_ENABLE_SEEK` opt-in, SeekAdapter exclusion from live registry
- `apps/api/tests/test_source_availability.py` — source availability API
- `apps/api/tests/test_job_discovery.py` — discovery pipeline

### Frontend
- No UI references to `(unavailable)` hardcoding found for Seek; frontend uses dynamic `source_availability()` endpoint.

### Deployment (Missing)
- **Discovery service:** `scripts/discovery_cron.sh` (lines 1–118) exists — authenticates user, runs scout + fit-scorer every 30 minutes
- **Service/timer files:** Referenced in `README.md:92`, `DEPLOYMENT-RUNBOOK.md:204–205` but NOT DEPLOYED to systemd
  - Expected paths: `/etc/systemd/system/aether-discovery.service` and `/etc/systemd/system/aether-discovery.timer`
  - Currently only deployed: `aether-api.service`, `aether-web.service`, `aether-worker.service` (verified in `/deploy/`)

### Environment
- `AETHER_ENABLE_SEEK` — default OFF (compliance gate), no presence in `.env.example`

---

## Feature 2: ATS Scoring

**Verdict:** PARTIAL (engine complete, API exposure incomplete, UI rendering absent)

### Backend Implementation
- **ATS Engine class:** `apps/api/app/services/ats_engine.py:140–162` (`class ATSEngine`) — stateless deterministic scorer
  - Components (3-part weighted): keyword_match (40%), semantic_similarity (40%), experience_gap (20%)
  - Overall score: 0–100 clamped
  - `REVIEW_THRESHOLD = 60.0` — below 60 sets `requires_review=True`
- **Score dataclass:** `apps/api/app/services/ats_engine.py:92–103` (`ATSScore`) — fields: `overall`, `keyword_match`, `semantic_similarity`, `experience_gap`, `matched_keywords`, `missing_keywords`, `requires_review`
- **Resume tailer (uses ATS):** `apps/api/app/services/resume_tailor.py` — integration point (file size 15.8 KB, examined but specific call sites not exhaustively verified in this phase)

### API Exposure (Incomplete)
- No `ats_score` found in `jobs.py` router responses (checked lines 1–500)
- No `ats_score` exposed in `cover_letters.py` router responses
- No `ats_score` exposed in `applications.py` router responses
- **Database column:** `ats_score` referenced in `applications.py:29` comment ("j.'fitScore'") but not in query SELECT clause

### UI Rendering (Absent)
- No ATS score chip/badge found in job card components
- No score visualization on application tracker or cover-letter screens

### Tests
- `apps/api/tests/test_ats_engine.py` — unit tests for ATSEngine
- `apps/api/tests/test_gap_p6_tailoring_ats.py` — integration tests with tailoring

---

## Feature 3: Story Bank

**Verdict:** PARTIAL (CRUD complete, no relevance scoring, dedup/fingerprinting present but not verified)

### Backend Implementation
- **Router:** `apps/api/app/routers/stories.py:1–177` (complete CRUD)
  - `list_stories()` (line 138)
  - `story_stats()` (line 144) — returns total, quantified, starred, categories
  - `create_story()` (line 159) — POST with dedup (contentHash)
  - `update_story()` (line 164)
  - `delete_story()` (line 174)
- **Dedup internals:** 
  - `contentHash` field mentioned (line 28) as "G-P4-STORY-DEDUP-004" sha256 digest
  - Hidden from API responses (line 37: `_INTERNAL_COLUMNS = frozenset({"contentHash"})`)
  - Assertion: "exposing it would both leak an internal identifier and let a client probe or forge dedup collisions"
- **Display enrichment:**
  - `_derive_category()` (line 79) — tags + title → story category (Risk & Compliance, Leadership, Technical, Delivery)
  - `_derive_impact()` (line 99) — largest percent-metric as impact badge
  - `_enrich()` (line 123) — merge category, impact, starred flag

### Relevance Scoring (Absent)
- No relevance score computed or returned
- Interview themes (line 40–49) define coverage topics but produce no numeric scores

### Story Selection in Cover Letter (Unverified)
- Integration with cover-letter generation: no explicit call sites found in this phase

### Tests
- `apps/api/tests/test_story_bank.py` — CRUD tests
- `apps/api/tests/test_story_bank_enrichment.py` — enrichment (category, impact, starred)
- `apps/api/tests/test_story_dedup.py` — dedup logic (18.1 KB, 5 Jul 29)

---

## Feature 4: Applications Stage-Move (Kanban Drag)

**Verdict:** PARTIAL (stage definitions complete, move endpoint implemented, UI affordances incomplete)

### Backend Implementation
- **Stage definitions:** `apps/web/src/components/applications/tracker-lib.ts:44–101` (`STAGE_DEFS`)
  - 8 stages: discovered, evaluating, tailoring, ready, submitted, in-review, interview, offer
  - Each stage: key, label, dot color, icon, icon class
- **Mappings:**
  - `APP_STAGE` (line 104): application.status → stage key
  - `STAGE_TO_APP_STATUS` (line 123): stage key → application.status write target (inverse)
  - `JOB_STAGE_TO_STATUS` (line 133): job.status → stage key (discovered, evaluating, tailoring)
- **API endpoints:** `apps/api/app/routers/applications.py`
  - `move_pipeline_job()` (line 255–319) — POST `/pipeline/{job_id}/move` for 3 job-fed stages
    - Validation (line 238–252): stage key validation, 422 for illegal cross-side moves
    - 409 conflict when job has application ("move the application card instead")
    - Audit logging: `job.stage_move` (line 297)
  - Corresponding application-move endpoint: `move_application()` (line 321–...) — not fully read in this phase
  - Closed applications (line 229): `_CLOSED_STATUSES = {"rejected", "withdrawn"}` — cannot drag back

### UI Affordances (Partial)
- Kanban board layout: `apps/web/src/components/applications/SankeyFlow.tsx` (mentioned, not exhaustively read)
- Drag/drop implementation: no React DnD library calls found in spot checks; UI component not fully verified
- Menu affordance: not found in jobs/page.tsx card rendering

### Tests
- `apps/web/src/components/applications/__tests__/tracker-api.test.ts` — API integration tests (mentioned)

---

## Feature 5: Approvals

**Verdict:** PARTIAL (endpoints complete, UI dismiss/delete present, expiry logic implemented)

### Backend Implementation
- **Router:** `apps/api/app/routers/approvals.py:1–150+` (complete)
  - `list_approvals()` (line 80) — GET, defaults to pending, supports `?status=all`
  - `create_approval()` (line 96) — POST to create approval request
  - `purge_expired_approvals()` (line 113) — POST bulk-delete expired pending approvals
  - `get_approval()` (line 135)
  - `delete_approval()` (line 140) — DELETE single approval (hard delete, not soft)
  - `approve()` (line 178)
  - `reject()` (line 186)
  - `execute_gated_action()` (line 194)

### Expiry Logic
- **Constant:** `EXPIRY_HOURS` (imported from `app.services.approval_service` line 15)
- **Purge function:** `purge_expired_approvals()` (line 113–131) — server-side SQL-based check (48h window per docstring line 116)
- **Hard delete:** no terminal "dismissed" state; expired and resolved rows are deletable (line 150)

### UI Components (Partial)
- `apps/web/src/components/approvals/ApprovalModal.tsx` — modal rendering (not fully read)
- `apps/web/src/components/approvals/api.ts` — API client (not fully read)
- Delete affordance: present (line 140 endpoint exists)
- Dismiss: assumed via delete endpoint (no explicit "dismiss" state found)

### Tests
- Not exhaustively verified in this phase

---

## Feature 6: Admin

**Verdict:** PARTIAL (backend endpoints complete, admin login button absent from main UI, admin pages deployed)

### Backend Implementation
- **Admin router:** `apps/api/app/routers/admin.py:1–210+` (complete, all routes auth-gated by `AdminUser` dependency)
  - Health/status: `/admin/health` (line 40)
  - Users: `/admin/users` (line 51), `/admin/users/{user_id}` (line 66)
  - Spend cap: `POST /admin/users/{user_id}/spend-cap` (line 104)
  - Suspend/unsuspend: POST routes (line 124, 141)
  - Spend overview: GET `/admin/spend` (line 165)
  - Settings (signup toggle, email verification): GET/POST (line 204, 209)
  - Audit log: GET `/admin/audit-log` (line 239)
- **Auth middleware:** `AdminUser` dependency (line 20) — 403 for non-admin, 401 for anonymous
- **Audit logging:** every mutation appends `AdminAuditLog` row (actor, action, target, detail, IP) (line 6–8)

### Admin Pages (Frontend)
- **Deployed pages:**
  - `apps/web/src/app/admin/page.tsx` — admin home
  - `apps/web/src/app/admin/layout.tsx` — layout wrapper
  - `apps/web/src/app/admin/health/page.tsx`
  - `apps/web/src/app/admin/settings/page.tsx`
  - `apps/web/src/app/admin/spend/page.tsx`
  - `apps/web/src/app/admin/users/page.tsx`
  - `apps/web/src/app/admin/users/[id]/page.tsx`
  - `apps/web/src/app/admin/audit-log/page.tsx`

### Admin Entry Point (Absent)
- No admin login button found in:
  - `apps/web/src/components/topbar.tsx` (lines 1–300 read)
  - `apps/web/src/components/sidebar.tsx` (not fully read; sidebar exists)
  - `/dashboard` home page
- Admin pages are URL-accessible but gated by auth middleware; no nav entry point on public UI

### Admin Credentials
- `AETHER_ADMIN_EMAIL` + `AETHER_ADMIN_PASSWORD_HASH` referenced (line 1 comment, not fully verified in repository init code)
- Usage in `apps/api/app/repositories/admin.py:575` (not fully read in this phase)

### Tests
- `apps/web/src/app/admin/users/[id]/__tests__/ML-admindetail-001.test.tsx` — mentioned

---

## Feature 7: Jobs Apply

**Verdict:** COMPLETE (endpoint, UI button, confirmation gate all present)

### Backend Implementation
- **Apply endpoint:** `apps/api/app/routers/jobs.py:446–500+` (`apply_to_job()`)
  - POST `/jobs/{job_id}/apply`
  - Creates an Application and advances the job to `applied` status
  - Requires cover letter and resume (helper functions `_cover_letter_for_apply()` line 399, `_resume_for_apply()` line 414)

### Frontend Implementation
- **Apply button:** `apps/web/src/app/dashboard/jobs/page.tsx:558` — POST `/jobs/{gateJobId}/apply`
- **Bulk apply:** line 613 — POST per-job apply in loop
- **Confirmation gate (MV-job-discovery-002):**
  - Line 266–268: "Bulk-apply confirmation gate… applied to bulk apply too"
  - Line 588–591: `confirmBulkApply()` performs actual POSTs only after user confirmation
  - Line 1540–1603: modal rendering with "Apply (N)" button

### View on Source
- **Link:** `apps/web/src/app/dashboard/jobs/page.tsx:1087–1142` — renders `href={job.sourceUrl}` link for "View on source"
- **Job model:** `sourceUrl` field present in API response (line 29 of applications.py comment)

### Tests
- `apps/web/src/app/dashboard/jobs/__tests__/page.test.tsx:146` — apply route regex pattern
- `apps/web/src/app/dashboard/jobs/__tests__/page.test.tsx:283` — bulk apply confirmation gate (MV-job-discovery-002)

---

## Feature 8: Realtime (Polling)

**Verdict:** COMPLETE (polling intervals verified, no SSE/WebSocket, cache headers absent)

### Polling Intervals (Verified)
| Component | Location | Interval | Purpose |
|-----------|----------|----------|---------|
| Sidebar | `components/sidebar.tsx:45` | 30,000 ms (30s) | User stats refresh |
| Topbar | `components/topbar.tsx:212` | 60,000 ms (60s) | Approvals count |
| Applications board | `app/dashboard/applications/page.tsx:452` | 20,000 ms (20s) | Application list refresh |
| Jobs board | `app/dashboard/jobs/page.tsx:323, 331` | 20,000 ms (20s) | Job list refresh |
| Agents page | `app/dashboard/agents/page.tsx:118–229` | setInterval pattern (interval TBD in full read) | Agent run polling |

### Polling Implementation
- **Pattern:** `useEffect` hook with `setInterval()` + cleanup
- **Example (sidebar):** "Mirrors the existing sidebar.tsx (30s) / topbar.tsx (60s) polling idiom" (jobs/page.tsx:323 comment)
- **Async handling:** "polling; a legacy synchronous body passes through unchanged" (jobs/page.tsx:519 comment)

### SSE/WebSocket (Absent)
- No `EventSource` or WebSocket code found in spot checks

### Cache Headers (Absent)
- No `Cache-Control`, `max-age`, `no-cache`, or `must-revalidate` found in backend routers
- API responses use defaults (no explicit cache directives observed)

---

## Feature 9: Analytics

**Verdict:** PARTIAL (funnel, ATS distribution, ROI complete; interview_conversion_rate absent)

### Backend Implementation
- **Router:** `apps/api/app/routers/analytics.py:1–250+` (29.4 KB)
- **Endpoints:**
  - `funnel()` (line 85) — jobs_found, applied, screened, interviewed, offers
  - `ats_distribution()` (line 123) — histogram in 10-point buckets
  - `agent_roi()` (line 148) — total cost, run count, avg duration
  - `conversion()` (line 173) — stage-to-stage rates derived from funnel
    - Rates computed: found_to_applied, applied_to_screened, screened_to_interview, interview_to_offer
  - `market_pulse()` (line 292) — real market data (source NOT connected, line 210)
  - `dashboard()` (line 687) — dashboard summary from analytics

### Metrics Computed
- **Application counts (canonical):** `get_application_counts()` (line 31–81)
  - `total` — every Application row regardless of status
  - `submitted` — status <> 'draft' (actually sent to employer)
- **Period windows:** 7d, 30d, 90d, all (line 15–16)
- **Funnel metrics:** CUMULATIVE model (line 37–60)

### Interview Conversion Rate (Absent)
- Not found in conversion() function (line 172–186)
- Not found anywhere in analytics.py via grep
- Computation hints in funnel data: "interviewed" is status IN (interview, offer), but no per-interview conversion percentage

### UI Dashboard (Not Fully Verified)
- Referenced but not exhaustively read in this phase

---

## Summary Table

| Feature | Verdict | Key Gaps |
|---------|---------|----------|
| 1. Seek.com.au | PARTIAL | discovery.service/.timer not deployed; AETHER_ENABLE_SEEK default OFF |
| 2. ATS Scoring | PARTIAL | no API response exposure; no UI rendering |
| 3. Story Bank | PARTIAL | no relevance scoring; dedup fingerprinting present but not exercised |
| 4. Stage-Move | PARTIAL | endpoints implemented; UI drag affordance incomplete |
| 5. Approvals | PARTIAL | endpoints complete; UI delete affordance present but not fully verified |
| 6. Admin | PARTIAL | backend complete; admin login button absent from main UI nav |
| 7. Apply | COMPLETE | endpoint, UI button, confirmation gate, sourceUrl link all present |
| 8. Realtime | COMPLETE | 4–5 polling intervals verified (20–60s); no SSE/WebSocket; no cache headers |
| 9. Analytics | PARTIAL | funnel/ROI/ATS-dist complete; interview_conversion_rate absent |

---

## Verification Notes

- **[VERIFIED-WITH-FRESH-CODE-2026-07-30]:** All file:line citations derived from live repository grep, file reads, and test enumeration
- **[INFERRED]:** Features 5, 6 UI components inferred from directory existence but not exhaustively read
- **[ASSUMED-PENDING-PROBE]:** discovery.service/.timer deployment status requires live systemd inspection; admin login button requires full sidebar/topbar scan

---

## Files Modified in This Report

None — read-only evidence collection only.
