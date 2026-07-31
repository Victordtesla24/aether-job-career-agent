# SCREEN MATRIX — Frontend Routes and API Integration

**Generated:** 2026-07-31 MODELS-LIVE phase  
**Route Count:** 32 page.tsx files discovered  
**Wireframe Count:** 17 wireframes in design/screens/

---

## Wireframe Inventory

| Wireframe (design/screens/) | Routes Mapped To | Status |
|---|---|---|
| agent-monitor.html | (none found) | UNBUILT |
| agents.html | /dashboard/agents | VERIFIED |
| analytics.html | /dashboard/analytics | VERIFIED |
| application-tracker.html | /dashboard/applications | VERIFIED |
| approval-modal.html | /dashboard/approvals | VERIFIED |
| cover-letter-studio.html | /dashboard/cover-letters | VERIFIED |
| dashboard.html | /dashboard | VERIFIED |
| email-center.html | /dashboard/email | VERIFIED |
| interview-center.html | /dashboard/interviews | VERIFIED |
| job-discovery.html | /dashboard/jobs | VERIFIED |
| mobile-approval.html | (mobile variant, shares /dashboard/approvals) | INFERRED |
| mobile-dashboard.html | (mobile variant, shares /dashboard) | INFERRED |
| networking.html | /dashboard/networking | VERIFIED |
| offer-comparison.html | /dashboard/offers | VERIFIED |
| resume-studio.html | /dashboard/resume | VERIFIED |
| settings.html | /dashboard/settings | VERIFIED |
| story-bank.html | /dashboard/stories | VERIFIED |

**Finding:** agent-monitor.html has no corresponding route (screen unbuilt).

---

## Frontend Routes (32 routes)

| Route | Page File | Wireframe | API Endpoints Called | Agents Invoked | Realtime | Auth |
|---|---|---|---|---|---|---|
| / | apps/web/src/app/layout.tsx | NONE | (root layout) | (none) | none | public |
| /login | apps/web/src/app/login/page.tsx | NONE | POST /auth/login, POST /auth/register, GET /auth/me | (none) | none | public |
| /signup | apps/web/src/app/signup/page.tsx | NONE | POST /auth/register, GET /auth/me | (none) | none | public |
| /forgot-password | apps/web/src/app/forgot-password/page.tsx | NONE | POST /auth/forgot-password, POST /auth/reset-password | (none) | none | public |
| /pricing | apps/web/src/app/pricing/page.tsx | NONE | GET /agents/catalog (optional), GET /billing/plans | (none) | none | public |
| /terms | apps/web/src/app/terms/page.tsx | NONE | (static content) | (none) | none | public |
| /privacy-policy | apps/web/src/app/privacy-policy/page.tsx | NONE | (static content) | (none) | none | public |
| /dashboard | apps/web/src/app/dashboard/page.tsx | dashboard.html | GET /applications, GET /analytics/conversion, GET /agents/runs, GET /workspaces/settings | jobDiscovery, orchestration | polling 5s | user |
| /dashboard/jobs | apps/web/src/app/dashboard/jobs/page.tsx | job-discovery.html | GET /jobs, GET /jobs/{id}/insights, POST /jobs/{id}/save, POST /jobs/{id}/apply, POST /agents/scout/run, POST /agents/fit-scorer/run | scout, fitScorer | polling 2s | user |
| /dashboard/agents | apps/web/src/app/dashboard/agents/page.tsx | agents.html | GET /agents, GET /agents/catalog, GET /agents/config, GET /agents/runs, POST /agents/{name}/run, GET /agents/providers | (all agents) | polling 3s | user |
| /dashboard/applications | apps/web/src/app/dashboard/applications/page.tsx | application-tracker.html | GET /applications, GET /analytics/ats-distribution, PATCH /applications/{id}/stage, POST /agents/board-sweep/trigger | board-sweep | polling 4s | user |
| /dashboard/approvals | apps/web/src/app/dashboard/approvals/page.tsx | approval-modal.html | GET /approvals, GET /approvals/{id}, POST /approvals/{id}/approve, POST /approvals/{id}/reject, POST /approvals/{id}/execute | (none) | polling 3s | user |
| /dashboard/cover-letters | apps/web/src/app/dashboard/cover-letters/page.tsx | cover-letter-studio.html | GET /cover-letters, GET /cover-letters/{id}, POST /agents/cover-letter/run, POST /cover-letters/{id}/refine, POST /cover-letters/{id}/pdf | coverLetter | polling 2s | user |
| /dashboard/resume | apps/web/src/app/dashboard/resume/page.tsx | resume-studio.html | GET /resumes, GET /resumes/{id}, POST /resumes, POST /resumes/upload, POST /agents/tailor/run, GET /agents/config/resumeTailoring | resumeTailoring | polling 2s | user |
| /dashboard/interviews | apps/web/src/app/dashboard/interviews/page.tsx | interview-center.html | GET /interviews, POST /interviews, GET /workspaces/interviews/prep, POST /agents/interview-prep/run | interviewPrep | polling 3s | user |
| /dashboard/email | apps/web/src/app/dashboard/email/page.tsx | email-center.html | GET /emails, GET /emails/accounts, POST /emails/accounts/connect, GET /emails/{thread_id}, POST /emails/{thread_id}/reply, POST /agents/email/run | emailAgent | polling 2s | user |
| /dashboard/networking | apps/web/src/app/dashboard/networking/page.tsx | networking.html | GET /networking, GET /networking/contacts, POST /networking/contacts, POST /agents/recruiter-outreach/run, GET /workspaces/networking/summary | recruiterOutreach | polling 3s | user |
| /dashboard/offers | apps/web/src/app/dashboard/offers/page.tsx | offer-comparison.html | GET /offers, POST /offers, DELETE /offers/{id}, GET /workspaces/offers | (none) | none | user |
| /dashboard/stories | apps/web/src/app/dashboard/stories/page.tsx | story-bank.html | GET /stories, POST /stories, PUT /stories/{id}, DELETE /stories/{id}, POST /agents/story-extractor/run | storyExtraction | polling 2s | user |
| /dashboard/analytics | apps/web/src/app/dashboard/analytics/page.tsx | analytics.html | GET /analytics/funnel, GET /analytics/conversion, GET /analytics/ats-distribution, GET /analytics/agent-roi, GET /analytics/market-pulse | (none) | polling 5s | user |
| /dashboard/settings | apps/web/src/app/dashboard/settings/page.tsx | settings.html | GET /workspaces/settings, PUT /workspaces/settings, GET /agents/config, PUT /agents/config/{agent_key}, GET /agents/providers, PUT /agents/user/providers/{provider}/credential, DELETE /agents/user/providers/{provider}/credential | (none) | polling 3s | user |
| /dashboard/[...slug] | apps/web/src/app/dashboard/[...slug]/page.tsx | (dynamic) | (routes to dashboard sub-pages) | (none) | none | user |
| /admin-login | apps/web/src/app/admin-login/page.tsx | NONE | POST /admin/login (implied) | (none) | none | public |
| /admin | apps/web/src/app/admin/page.tsx | NONE | GET /admin/users, GET /admin/spend, GET /admin/settings | (none) | polling 5s | admin |
| /admin/users | apps/web/src/app/admin/users/page.tsx | NONE | GET /admin/users, POST /admin/users/{id}/spend-cap, POST /admin/users/{id}/suspend, POST /admin/users/{id}/unsuspend | (none) | polling 3s | admin |
| /admin/users/[id] | apps/web/src/app/admin/users/[id]/page.tsx | NONE | GET /admin/users/{id}, POST /admin/users/{id}/spend-cap, POST /admin/users/{id}/suspend, POST /admin/users/{id}/unsuspend | (none) | polling 3s | admin |
| /admin/audit-log | apps/web/src/app/admin/audit-log/page.tsx | NONE | GET /admin/audit-log | (none) | polling 5s | admin |
| /admin/health | apps/web/src/app/admin/health/page.tsx | NONE | GET /admin/health, GET /health | (none) | polling 2s | admin |
| /admin/settings | apps/web/src/app/admin/settings/page.tsx | NONE | GET /admin/settings, POST /admin/settings | (none) | none | admin |
| /admin/spend | apps/web/src/app/admin/spend/page.tsx | NONE | GET /admin/spend | (none) | polling 5s | admin |

---

## Findings

### Wireframes Without Routes (Unbuilt Screens)
- **agent-monitor.html** — No route found; this screen is not implemented in the current app

### Routes Without Wireframes (Undesigned Screens)
- **/login, /signup, /forgot-password, /pricing, /terms, /privacy-policy** — Auth & marketing pages (undesigned wireframes; handled as system screens)
- **/admin-login, /admin, /admin/users, /admin/users/[id], /admin/audit-log, /admin/health, /admin/settings, /admin/spend** — Admin panel (undesigned wireframes; security-gated system screens)
- **/dashboard/[...slug]** — Dynamic routing fallback (undesigned)

### Key Observations
1. **17 wireframes mapped** to 25+ app routes (counting /admin suite as separate pages)
2. **Realtime mechanisms:** Polling intervals dominant (2–5s per route), no SSE/WebSocket detected
3. **Agent invocation:** 12+ agent keys actively wired into dashboard (scout, fitScorer, tailor, coverLetter, interviewPrep, emailAgent, recruiterOutreach, etc.)
4. **Auth tiers:** Public (login/pricing), User (dashboard/*), Admin (/admin/*)
5. **API patterns:** Consistent client.ts-based fetch/axios calls; endpoint paths match FastAPI router definitions
