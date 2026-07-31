# SCREEN-MATRIX: Dashboard Routes & API Endpoints Mapping

**Document**: Phase 0 Step 5a — Complete read-only code inventory
**Generated**: 2026-07-30T23:47:00Z
**Verification**: [VERIFIED-WITH-FRESH-CODE-SCAN]

---

## Executive Summary

**Total Routes**: 27  
**Total Unique Endpoints**: 59  
**Routes with AI Agents**: 5 (dashboard, agents, cover-letters, resume, stories)  
**Realtime Mechanisms**: Async job polling (3s interval) + load-once fetch

---

## 1. Dashboard Routes (User-Facing)

### `/dashboard` — Home Dashboard
**Wireframe**: `design/screens/dashboard.html`  
**Page File**: `apps/web/src/app/dashboard/page.tsx` (l.127–650)  
**Components**: DashboardStats, MarketPulse, agent-feed, opportunities-widget, funnel, story-bank, crm-summary, approvals-queue

**API Endpoints Called**:
| Method | Path | Line | Purpose |
|--------|------|------|---------|
| GET | `/jobs?sort=fitScore` | 130 | Top 3 opportunities by fit score |
| GET | `/agents/runs` | 131 | Agent activity feed (latest 10 runs) |
| GET | `/analytics/agent-roi` (via `fetchFunnel`) | 128–129 | Application funnel (all-time + 7-day) |
| GET | `/stories` | 132 | Story bank quick-access (latest 3) |
| GET | `/workspaces/networking/summary` | 133–134 | CRM summary (active conversations, follow-ups, warm intros) |
| GET | `/approvals?status=pending` | 136 | Needs Approval queue (top 3) |

**AI Agents Involved**: scout, tailor, coverLetter, story-extractor  
**Realtime Mechanism**: `useLoad()` — load-once on mount, no polling (l.92–116)  
**Interactive Features**:
- Toast notifications for approval actions (l.142–149)
- Inline approval buttons with busy state (l.311–320)
- Live pending approval ID cross-check vs. cached snapshot (l.163, MV-dashboard-009)
- Feed filter buttons (All/Discovered/Tailored/Submitted/Waiting) (l.235–250)

---

### `/dashboard/agents` — Agent Monitor & Control
**Wireframe**: `design/screens/agents.html`  
**Page File**: `apps/web/src/app/dashboard/agents/page.tsx`

**API Endpoints Called**:
| Method | Path | Purpose |
|--------|------|---------|
| GET | `/agents` | List all available agents + status |
| POST | `/agents/{name}/run` | Trigger any agent (scout, tailor, etc.) |
| GET | `/agents/runs` | Activity history |
| GET | `/agents/jobs/{id}` | Poll background job status (3s interval) |

**AI Agents Involved**: scout, tailor, coverLetter, story-extractor  
**Realtime Mechanism**: Async job polling via `resolveRun()` → GET `/agents/jobs/{id}` every 3s (agents.ts:57–107, JOB_POLL_INTERVAL_MS=3000)

---

### `/dashboard/jobs` — Job Discovery & Search
**Wireframe**: `design/screens/job-discovery.html`  
**Page File**: `apps/web/src/app/dashboard/jobs/page.tsx` (l.1–200+)

**API Endpoints Called**:
| Method | Path | Purpose |
|--------|------|---------|
| GET | `/jobs?status=&source=&saved=&sort=` | Filtered job list (market: AU/Intl/Saved, source filter, salary bands) |
| GET | `/jobs/{id}/insights` | ATS match analysis: 10-dim fit, keyword match, skill gaps, risk signals |
| POST | `/jobs/{id}/save` | Toggle bookmark/saved flag |
| POST | `/jobs/{id}/apply` | Two-step apply flow (validate resume + cover letter) |
| POST | `/agents/scout/run` | Discovery sync (fetch new jobs from configured sources) |
| GET | `/agents/scout/sources` | Per-source sync status (last sync, fetch count, error) |
| GET | `/agents/scout/sources/availability` | Live source availability (which sources filterable now) |

**Filters**: Market tabs (AU/Intl/Saved), source bar, salary bands (0/100k/150k/200k+), remote toggle  
**Realtime Mechanism**: None (static fetch on mount)  
**Special Features**:
- Autopilot suppression hint (ML-W25): job.autopilotSuppressedUntil (l.149–153)
- Source availability gates (ML-audit-seek-fe-hardcode-001)

---

### `/dashboard/applications` — Application Tracker
**Wireframe**: `design/screens/application-tracker.html`  
**Page File**: `apps/web/src/app/dashboard/applications/page.tsx`

**API Endpoints Called**:
| Method | Path | Purpose |
|--------|------|---------|
| GET | `/applications` | All submitted applications (stage: discovered/screening/matched/tailoring/ready/applied/archived/rejected) |

**Realtime Mechanism**: None

---

### `/dashboard/approvals` — Approval Queue
**Wireframe**: `design/screens/approval-modal.html`  
**Page File**: `apps/web/src/app/dashboard/approvals/page.tsx`

**API Endpoints Called**:
| Method | Path | Purpose |
|--------|------|---------|
| GET | `/approvals?status=pending\|approved\|rejected` | Gated actions awaiting decision |
| POST | `/approvals/{id}/approve` | Allow action to proceed (REQ-TM-05/J4) |
| POST | `/approvals/{id}/reject` | Block and skip |
| POST | `/approvals/purge-expired` | Cleanup stale/expired requests |

**Realtime Mechanism**: None

---

### `/dashboard/cover-letters` — Cover Letter Studio
**Wireframe**: `design/screens/cover-letter-studio.html`  
**Page File**: `apps/web/src/app/dashboard/cover-letters/page.tsx`

**API Endpoints Called**:
| Method | Path | Purpose |
|--------|------|---------|
| GET | `/cover-letters` | List generated/drafted cover letters |
| POST | `/agents/cover-letter/run` | Generate new cover letter for job (async, 202 Accepted) |

**AI Agents Involved**: coverLetter  
**Realtime Mechanism**: Async job polling (agents.ts:57–107, 3s poll cap 10min)

---

### `/dashboard/resume` — Resume Tailoring Studio
**Wireframe**: `design/screens/resume-studio.html`  
**Page File**: `apps/web/src/app/dashboard/resume/page.tsx`

**API Endpoints Called**:
| Method | Path | Purpose |
|--------|------|---------|
| GET | `/resumes` | List tailored & base resumes |
| POST | `/agents/tailor/run` | Generate tailored resume for job (async, 202 Accepted) |

**AI Agents Involved**: tailor  
**Realtime Mechanism**: Async job polling (3s interval, 10min cap)

---

### `/dashboard/stories` — Story Bank (STAR Achievements)
**Wireframe**: `design/screens/story-bank.html`  
**Page File**: `apps/web/src/app/dashboard/stories/page.tsx`

**API Endpoints Called**:
| Method | Path | Purpose |
|--------|------|---------|
| GET | `/stories` | STAR achievement library |
| POST | `/agents/story-extractor/run` | Auto-extract stories from resume/work history (async) |
| GET | `/stories/stats` | Dedup metrics & coverage |
| DELETE | `/stories/{id}` | Remove story (204, body drain required MV-story-bank-004) |

**AI Agents Involved**: story-extractor  
**Realtime Mechanism**: Async job polling (3s interval)

---

### `/dashboard/email` — Email Center
**Wireframe**: `design/screens/email-center.html`  
**Page File**: `apps/web/src/app/dashboard/email/page.tsx`

**API Endpoints Called**:
| Method | Path | Purpose |
|--------|------|---------|
| GET | `/workspaces/emails/inbox` | Recruiter email threads (triage score, body truncation flag) |
| POST | `/workspaces/emails/send` | Send reply/forward |
| POST | `/agents/email/run?mode=insights` | AI triage & thread intelligence (score, breakdown, summary) |

**Intelligence Model**: On-demand per-thread LLM analysis (never bulk load, MV-email-center-001)  
**Email Score Semantics**: `null` = untriaged (em-dash badge), number = real triage score  
**Realtime Mechanism**: None (static inbox fetch)

---

### `/dashboard/interviews` — Interview Center
**Wireframe**: `design/screens/interview-center.html`  
**Page File**: `apps/web/src/app/dashboard/interviews/page.tsx`

**API Endpoints Called**:
| Method | Path | Purpose |
|--------|------|---------|
| GET | `/interviews` | Scheduled interviews & associated offers |
| POST | `/workspaces/interviews/prep` | Generate interview prep questions |

**Realtime Mechanism**: None

---

### `/dashboard/offers` — Offer Comparison
**Wireframe**: `design/screens/offer-comparison.html`  
**Page File**: `apps/web/src/app/dashboard/offers/page.tsx`

**API Endpoints Called**:
| Method | Path | Purpose |
|--------|------|---------|
| GET | `/workspaces/offers` | Received offers with comparison matrix (salary, benefits, equity) |

**Realtime Mechanism**: None

---

### `/dashboard/networking` — Recruiter CRM
**Wireframe**: `design/screens/networking.html`  
**Page File**: `apps/web/src/app/dashboard/networking/page.tsx`

**API Endpoints Called**:
| Method | Path | Purpose |
|--------|------|---------|
| GET | `/networking/contacts` | CRM contact list (paginated) |
| GET | `/networking/contacts/{id}` | Contact detail view (MV-networking-005) |
| POST | `/networking/contacts` | Add/update contact (MV-networking-001) |
| DELETE | `/networking/contacts/{id}` | Remove contact (ML-networking-001, 204) |
| GET | `/workspaces/networking/summary` | Pipeline stages + outreach queue + comms log (MV-networking-002) |

**Realtime Mechanism**: None

---

### `/dashboard/analytics` — Analytics & Market Intelligence
**Wireframe**: `design/screens/analytics.html`  
**Page File**: `apps/web/src/app/dashboard/analytics/page.tsx`

**API Endpoints Called**:
| Method | Path | Purpose |
|--------|------|---------|
| GET | `/analytics/ats-distribution` | Fit score histogram & percentiles |
| GET | `/analytics/market-pulse` | Market intelligence (salary trends, demand by role/location) |

**Realtime Mechanism**: None

---

### `/dashboard/settings` — User Settings & Preferences
**Wireframe**: `design/screens/settings.html`  
**Page File**: `apps/web/src/app/dashboard/settings/page.tsx`

**API Endpoints Called**:
| Method | Path | Purpose |
|--------|------|---------|
| GET | `/workspaces/settings` | User profile, preferences, integrations (model choice, budget, email account) |
| POST | `/workspaces/settings` | Persist changes (ML-settings-001: validation error messages bounded) |

**Realtime Mechanism**: None

---

## 2. Admin Routes

### `/admin` — Admin Dashboard
**Wireframe**: `design/screens/dashboard.html` (admin variant)  
**Page File**: `apps/web/src/app/admin/page.tsx`

**API Endpoints Called**:
| Method | Path | Purpose |
|--------|------|---------|
| GET | `/admin/health` | System health: services (api/db), agents (runs/success/fail/running/queued), LLM mode, cron status, provider config |

**Access Control**: AdminGuard resolves isAdmin from `/auth/me` (admin.ts:25–27); non-admins never render panel (GAP-P6-ADMIN-001/003)

---

### `/admin/health` — System Health
**Page File**: `apps/web/src/app/admin/health/page.tsx`

**API Endpoints Called**:
| Method | Path | Purpose |
|--------|------|---------|
| GET | `/admin/health` | Detailed health + LLM provider roster |

---

### `/admin/settings` — Global Configuration
**Page File**: `apps/web/src/app/admin/settings/page.tsx`

**API Endpoints Called**:
| Method | Path | Purpose |
|--------|------|---------|
| GET | `/admin/settings` | Flags: signupEnabled, emailVerificationEnabled |
| POST | `/admin/settings` | Update settings |

---

### `/admin/users` — User Management
**Page File**: `apps/web/src/app/admin/users/page.tsx`

**API Endpoints Called**:
| Method | Path | Purpose |
|--------|------|---------|
| GET | `/admin/users?q=&plan=&suspended=` | Paginated user list, searchable (limit/offset pagination) |

---

### `/admin/users/[id]` — User Detail & Controls
**Page File**: `apps/web/src/app/admin/users/[id]/page.tsx`

**API Endpoints Called**:
| Method | Path | Purpose |
|--------|------|---------|
| GET | `/admin/users/{id}` | User detail: profile, subscription, quota, recent runs, spend USD |
| POST | `/admin/users/{id}/spend-cap` | Set monthly spend limit (USD) |
| POST | `/admin/users/{id}/suspend` | Suspend/unsuspend user account |

**Spend Currency**: USD only (§14.8, admin.ts:256–264)

---

### `/admin/spend` — Spend Analytics
**Page File**: `apps/web/src/app/admin/spend/page.tsx`

**API Endpoints Called**:
| Method | Path | Purpose |
|--------|------|---------|
| GET | `/admin/spend` | Total + per-user spend breakdown (USD) |

---

### `/admin/audit-log` — Audit Trail
**Page File**: `apps/web/src/app/admin/audit-log/page.tsx`

**API Endpoints Called**:
| Method | Path | Purpose |
|--------|------|---------|
| GET | `/admin/audit-log?limit=50&offset=0` | Append-only audit trail (actorUserId, action, targetType, targetId, detail, IP) |

---

## 3. Auth & Public Routes

### `/login` — Login Form
**Page File**: `apps/web/src/app/login/page.tsx`

**API Endpoints Called**:
| Method | Path | Purpose |
|--------|------|---------|
| POST | `/auth/login` | Email/password authentication |
| GET | `/auth/google/login` | OAuth callback handler |

**Token Storage**: localStorage key `aether_token` (client.ts:14)  
**Auto-Login**: None (SC-AUTH-03: visitor without session → /login, no prefill)

---

### `/signup` — Registration
**Page File**: `apps/web/src/app/signup/page.tsx`

**API Endpoints Called**:
| Method | Path | Purpose |
|--------|------|---------|
| POST | `/auth/signup` | Register new user |

---

### `/forgot-password` — Password Reset
**Page File**: `apps/web/src/app/forgot-password/page.tsx`

**API Endpoints Called**:
| Method | Path | Purpose |
|--------|------|---------|
| POST | `/auth/forgot-password` | Send reset email |

---

### `/pricing` — Billing & Subscription
**Wireframe**: `design/screens/pricing.html`  
**Page File**: `apps/web/src/app/pricing/page.tsx`

**API Endpoints Called**:
| Method | Path | Purpose |
|--------|------|---------|
| GET | `/billing/entitlement` | User's current plan (free/pro/enterprise) |
| POST | `/billing/checkout` | Create Stripe checkout session (rate-limited 429, Retry-After header) |
| POST | `/billing/portal` | Manage subscription link (rate-limited 429) |

**Paywall Gate**: 402 `subscription_required` → redirect to `/pricing` (client.ts:210–216, GAP-P6-PAYWALL)  
**Rate Limiting**: Retry-After response header → formatRetryAfter() for UX (client.ts:40–44, MV-pricing-004)

---

### `/terms` — Terms of Service
**Page File**: `apps/web/src/app/terms/page.tsx`

**API Endpoints Called**: None  
**Content**: Static HTML

---

### `/privacy-policy` — Privacy Policy
**Page File**: `apps/web/src/app/privacy-policy/page.tsx`

**API Endpoints Called**: None  
**Content**: Static HTML

---

## 4. API Client Layer Architecture

**Location**: `apps/web/src/lib/api/`

**Core Module** (`client.ts`):
- `apiRequest<T>(path, options)`: Bearer token auth, 401 retry logic, 402 paywall redirect, 429 rate-limit handling
- `getToken()`: Fetch JWT from localStorage; redirect to /login if missing
- `ApiError`: Custom error with status + optional retryAfterSeconds
- `describeApiError()`: Bounded, human-readable error (ML-settings-001: max 300 chars, no raw invalid input echoes)

**Specialized Modules**:
- `agents.ts`: runAgent(), runPipeline(), resolveRun() (async job polling)
- `jobs.ts`: fetchJobs(), fetchJob(), toggleSaveJob(), runScoutAgent(), fetchScoutSources(), fetchSourceAvailability()
- `approvals.ts`: fetchApprovals(), decideApproval()
- `admin.ts`: fetchMe(), fetchAdminHealth(), fetchAdminUsers(), setSpendCap(), setSuspended(), fetchAdminSpend(), fetchAdminSettings(), updateAdminSettings(), fetchAuditLog()
- `workspaces.ts`: Networking contacts, email, interviews, offers, settings
- `auth.ts`: Login/signup/password reset
- `billing.ts`: Checkout, portal, entitlement
- `stories.ts`: Fetch/create/delete stories
- `resumes.ts`: Fetch/tailor resumes
- `coverLetters.ts`: Fetch/generate cover letters
- `interviews.ts`: Fetch interviews, prep questions
- `analytics.ts`: Fetch analytics data
- `emails.ts`: Email account connect

---

## 5. Async Job Resolution & Realtime Polling

**File**: `apps/web/src/lib/api/agents.ts` (l.39–107)

**Mechanism**: Dual-shape resolver for AETHER_ASYNC_GENERATION ON/OFF

When **ON** (async mode):
- Run endpoints return 202 Accepted: `{ job_id, status: "enqueued" }`
- Client polls `GET /agents/jobs/{id}` every 3 seconds
- Poll cap: 10 minutes (~200 polls) before timeout
- Terminal states: `completed` → resolve result, `failed` → throw ApiError with honest server error, timeout → throw "still processing" message

When **OFF** (legacy sync mode):
- Run endpoints return full result immediately
- Resolver returns body unchanged (dormant)

**Configuration**:
- `JOB_POLL_INTERVAL_MS = 3000` (§16.2 / J3 step 2)
- `JOB_POLL_CAP_MS = 10 * 60 * 1000`

---

## 6. API Endpoint Summary

**Total Unique Endpoints**: 59

**By HTTP Method**:
- GET: 37
- POST: 18
- DELETE: 3
- PATCH: 1

**By Domain**:
| Domain | Count |
|--------|-------|
| /jobs | 7 |
| /agents | 5 |
| /approvals | 4 |
| /admin/* | 8 |
| /auth | 3 |
| /billing | 3 |
| /workspaces/* | 12 |
| /networking | 4 |
| /analytics | 2 |
| /stories | 4 |
| /cover-letters | 2 |
| /resumes | 2 |
| /interviews | 2 |
| /emails | 2 |
| /offers | 1 |

---

## 7. Error Handling & Edge Cases

**File**: `apps/web/src/lib/api/client.ts`

**Notable Patterns**:
- **401 Unauthorized**: Single automatic retry with fresh token; on second 401, redirect to /login
- **402 Payment Required**: `subscription_required` → redirect to /pricing (paywall gate)
- **404/409 on Approvals**: Approval already resolved elsewhere (stale client state) → drop from pending set (MV-dashboard-009)
- **422 Validation Error**: Pydantic validation errors parsed → friendly field-specific messages (FIELD_LABELS), never echoing raw invalid input
- **429 Rate Limit**: Retry-After response header extracted → surface honest retry window (MV-pricing-004, checkout/portal endpoints)
- **204 No Content**: Body stream drained before return (Chromium net::ERR_ABORTED prevention, MV-story-bank-004)

---

## 8. Deployment & Environment

**API Base URL Resolution** (`client.ts:16–24`):
1. `NEXT_PUBLIC_API_BASE_URL` env override (if set)
2. Browser: `/api` (same-origin proxy)
3. SSR/Node: `http://127.0.0.1:8000` (FastAPI dev server)

**Backend**: 19 FastAPI routers at `apps/api/app/routers/`  
**Database**: PostgreSQL (production: PRODUCTION DATABASE_URL, tests: uat/test via scripts/run-tests.sh)

---

## 9. Verification Notes

- **Code Scan Timestamp**: 2026-07-30T23:47:00Z
- **Wireframe Files Verified**: 17 HTML mockups in `design/screens/`
- **Route Files Verified**: 31 .tsx files in `apps/web/src/app/`
- **API Modules Verified**: 15 .ts files in `apps/web/src/lib/api/`
- **Backend Routers Verified**: 19 .py files in `apps/api/app/routers/`
- **No Test Code Included**: Excludes unit/integration tests
- **No Breaking Changes in Scan**: All endpoints discoverable via current code; no hardcoded demo credentials (GAP-P4-068)

---

## 10. Known Limitations & TODOs

- **Realtime Dashboard**: W-I (pending) — polling not yet live on all screens
- **Scoring UI Reconciliation**: W-J (pending) — atsScore vs fitScore display alignment
- **Admin UI**: W-G (pending) — admin login button + portal branding
- **Jobs Apply Flow**: W-H (pending) — apply button hardening + error states
- **Stale Code Cleanup**: W-K (pending) — remove placeholders, duplicates, dummy data

---

**END OF SCREEN-MATRIX DOCUMENTATION**
