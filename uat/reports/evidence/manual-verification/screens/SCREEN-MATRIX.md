# SCREEN MATRIX — Manual Verification Phase 0, Step 4 (CORRECTED)

**Timestamp UTC:** 2026-07-17T13:20:00Z  
**Commit SHA:** 53f0e084da5b460835c32d3e07d496e6e67a8616  
**Production URL:** https://5cb5f0620.abacusai.cloud  
**Evidence Root:** uat/reports/evidence/manual-verification/  
**Repository:** /home/ubuntu/github_repos/aether-job-career-agent  
**Reconciliation Status:** RECONCILED 25/25 routes (every route in App Router mapped to >=1 matrix row)

---

## Enumeration Summary

| Category | Count | Status |
|----------|-------|--------|
| Wireframes | 17 | [VERIFIED-WITH-FRESH-EVIDENCE] |
| Web Routes (App Router) | 25 | [VERIFIED-WITH-FRESH-EVIDENCE] |
| Backend Endpoints | 126 | [VERIFIED-WITH-FRESH-EVIDENCE] |
| Backend Routers | 18 | [VERIFIED-WITH-FRESH-EVIDENCE] |
| Screen Matrix Rows | 29 | [VERIFIED-WITH-FRESH-EVIDENCE] |
| AI Agents (runtime) | 8 total, 7 active | [VERIFIED-WITH-FRESH-EVIDENCE] |

---

## SCREEN MATRIX — All Rows (29 test cases for Phase 1)

### Legend

- **screen_id**: kebab-case identifier
- **wireframe_file**: design/screens/ filename or empty if none
- **web_route(s)**: Next.js App Router page.tsx path(s)
- **backing_endpoints**: API endpoints called (METHOD /path format)
- **ai_agents**: agents wired to this screen (from runtime registry + code inspection)
- **coverage_gap**: null = complete, "route-without-wireframe" = finding to test
- **notes**: special casing, approval-gating, LLM wiring, testing guidance

---

## Dashboard & Navigation (3 rows)

| screen_id | wireframe_file | web_route(s) | backing_endpoints | ai_agents | coverage_gap | notes |
|-----------|-----------------|--------------|-------------------|-----------|--------------|-------|
| root | (none) | / | (redirect target; no direct endpoints) | null | route-without-wireframe | FINDING: Root route; next.config.mjs redirects to /login or /dashboard. Testable: redirect behavior, auth-based routing. |
| dashboard | dashboard.html | /dashboard, /dashboard/[...slug] | GET /workspaces/career-data, GET /analytics, GET /applications, GET /jobs, GET /agents | supervisor | null | Main hub; sidebar nav + hero cards; [...slug] catch-all for subroute fallback. |
| mobile-dashboard | mobile-dashboard.html | /dashboard | GET /workspaces/career-data, GET /analytics, GET /applications, GET /jobs, GET /agents | null | null | Responsive variant; same route, adaptive layout. |

## Job Discovery & Analytics (2 rows)

| screen_id | wireframe_file | web_route(s) | backing_endpoints | ai_agents | coverage_gap | notes |
|-----------|-----------------|--------------|-------------------|-----------|--------------|-------|
| job-discovery | job-discovery.html | /dashboard/jobs | GET /jobs, GET /jobs/{id}/insights, POST /jobs/{id}/save, POST /jobs/{id}/apply, POST /agents/scout/run, POST /agents/fit-scorer/run, GET /agents/scout/sources | scout, matcher, fitScorer | null | Market tabs; source filter bar; 2-step apply flow; agent integration. |
| analytics | analytics.html | /dashboard/analytics | GET /analytics, GET /analytics/dashboard, GET /analytics/funnel, GET /analytics/agent-roi, GET /analytics/conversion, GET /analytics/ats-distribution, GET /analytics/market-pulse | null | null | Funnel/ROI charts; market pulse; backed by agent stats. |

## Resume & Story Management (3 rows)

| screen_id | wireframe_file | web_route(s) | backing_endpoints | ai_agents | coverage_gap | notes |
|-----------|-----------------|--------------|-------------------|-----------|--------------|-------|
| resume-studio | resume-studio.html | /dashboard/resume | GET /resumes, GET /resumes/{id}, POST /resumes/upload, GET /resumes/{id}/download, GET /resumes/{id}/ats, GET /resumes/{id}/diff, POST /agents/tailor/run | tailor | null | Multi-resume carousel; ATS parser; tailor agent approval-gated. |
| story-bank | story-bank.html | /dashboard/stories | GET /stories, POST /stories, PUT /stories/{id}, DELETE /stories/{id}, POST /agents/story-extractor/run, GET /agents/stats | storyExtractor | null | Story add/edit/delete; extraction agent autonomous. |
| cover-letter-studio | cover-letter-studio.html | /dashboard/cover-letters | GET /cover-letters, GET /cover-letters/{id}, POST /cover-letters/{id}/refine, GET /cover-letters/{id}/pdf, GET /cover-letters/{id}/insights, POST /agents/cover-letter/run | coverLetter | null | Letter browser; refine; PDF export; approval-gated. |

## Applications & Approvals (3 rows)

| screen_id | wireframe_file | web_route(s) | backing_endpoints | ai_agents | coverage_gap | notes |
|-----------|-----------------|--------------|-------------------|-----------|--------------|-------|
| application-tracker | application-tracker.html | /dashboard/applications | GET /applications, GET /applications/{id}, POST /applications/{id}/submit, GET /applications/funnel/sankey | null | null | Application list by status; funnel chart. |
| approval-modal | approval-modal.html | /dashboard/approvals | GET /approvals, GET /approvals/{id}, POST /approvals/{id}/approve, POST /approvals/{id}/reject, POST /approvals/{id}/execute | null | null | Approval request list; approve/reject/execute. |
| mobile-approval | mobile-approval.html | /dashboard/approvals | GET /approvals, GET /approvals/{id}, POST /approvals/{id}/approve, POST /approvals/{id}/reject, POST /approvals/{id}/execute | null | null | Responsive variant of approval-modal. |

## Communication (2 rows)

| screen_id | wireframe_file | web_route(s) | backing_endpoints | ai_agents | coverage_gap | notes |
|-----------|-----------------|--------------|-------------------|-----------|--------------|-------|
| interview-center | interview-center.html | /dashboard/interviews | GET /interviews, POST /interviews, GET /interviews/{id}, PATCH /interviews/{id}, POST /interviews/{id}/cancel, POST /interviews/{id}/complete, GET /workspaces/interviews/prep | null | null | Interview scheduling; prep resources; cancel/complete. |
| networking | networking.html | /dashboard/networking | GET /networking, GET /networking/contacts, POST /networking/contacts, GET /networking/contacts/{id}, PATCH /networking/contacts/{id}, DELETE /networking/contacts/{id}, GET /networking/outreach, POST /networking/outreach, GET /networking/outreach/{id}, PATCH /networking/outreach/{id}, DELETE /networking/outreach/{id} | emailAgent | null | Contacts (CRM); outreach tasks; emailAgent approval-gated. |
| email-center | email-center.html | /dashboard/email | GET /emails, GET /emails/accounts, POST /emails/accounts/connect, GET /emails/accounts/{id}/sync-status, PATCH /emails/accounts/{id}/set-primary, DELETE /emails/accounts/{id}, GET /emails/{id}, POST /emails/draft, POST /emails/{id}/reply, GET /emails/oauth/status | emailAgent | null | Gmail sync; thread browser; draft/reply; emailAgent approval-gated. |

## Configuration (4 rows)

| screen_id | wireframe_file | web_route(s) | backing_endpoints | ai_agents | coverage_gap | notes |
|-----------|-----------------|--------------|-------------------|-----------|--------------|-------|
| settings | settings.html | /dashboard/settings | GET /workspaces/settings, PUT /workspaces/settings, GET /workspaces/career-data, POST /workspaces/career-data/refresh, GET /billing/entitlement, GET /billing/subscription, POST /billing/checkout, POST /billing/portal | null | null | Profile; career data; billing info (subscription/portal). Billing routing: /billing/* from settings UI. |
| offer-comparison | offer-comparison.html | /dashboard/offers | GET /workspaces/offers, GET /offers | null | null | Offer comparison table. |
| agent-monitor | agent-monitor.html | /dashboard/agents | GET /agents, GET /agents/catalog, GET /agents/config, GET /agents/runs, GET /agents/stats, GET /agents/user/providers, POST /agents/{name}/run, POST /agents/test-run | null | null | Agent status; catalog; config; runs; stats. |
| agents | agents.html | /dashboard/agents | GET /agents, GET /agents/catalog, GET /agents/config, GET /agents/runs, GET /agents/stats, GET /agents/user/providers, POST /agents/{name}/run, POST /agents/test-run | null | null | Duplicate of agent-monitor (design evolution). |

## Authentication & Public (5 rows)

| screen_id | wireframe_file | web_route(s) | backing_endpoints | ai_agents | coverage_gap | notes |
|-----------|-----------------|--------------|-------------------|-----------|--------------|-------|
| login | (none) | /login | POST /auth/login, GET /auth/me | null | route-without-wireframe | FINDING: No wireframe; CRITICAL PATH. Testable: form validation, error states, rate limiting, token storage, redirect. |
| signup | (none) | /signup | POST /auth/register, POST /auth/login | null | route-without-wireframe | FINDING: No wireframe; CRITICAL PATH. Testable: registration, validation, email, redirect. |
| pricing | (none) | /pricing | GET /billing/plans, POST /billing/checkout | null | route-without-wireframe | FINDING: No wireframe; REVENUE-CRITICAL. Testable: plan load, interval switching, GST pricing, subscribe flow (unauthenticated). |
| privacy-policy | (none) | /privacy-policy | (no API calls) | null | route-without-wireframe | FINDING: No wireframe; static legal page. Testable: page renders, links. |
| terms | (none) | /terms | (no API calls) | null | route-without-wireframe | FINDING: No wireframe; static legal page. Testable: page renders, links. |

## Admin Panel (6 rows — Operator-Gated)

| screen_id | wireframe_file | web_route(s) | backing_endpoints | ai_agents | coverage_gap | notes |
|-----------|-----------------|--------------|-------------------|-----------|--------------|-------|
| admin-root | (none) | /admin | GET /admin/health, GET /admin/users, GET /admin/spend, GET /admin/settings, GET /admin/audit-log | null | route-without-wireframe | FINDING: No wireframe; /admin/page.tsx (apps/web/src/app/admin/page.tsx). Operator-admin HUMAN-GATED (governance/human-gated-admin.md). Testable: unauthenticated behavior (401/redirect), error copy. Authenticated testing requires operator credential provisioning. |
| admin-health | (none) | /admin/health | GET /admin/health (admin.py:39-42) | null | route-without-wireframe | FINDING: No wireframe; /admin/health/page.tsx. Service/agent/cron status. Operator-gated; testable: unauthenticated. |
| admin-users | (none) | /admin/users, /admin/users/[id] | GET /admin/users, GET /admin/users/{user_id}, POST /admin/users/{user_id}/spend-cap, POST /admin/users/{user_id}/suspend, POST /admin/users/{user_id}/unsuspend (admin.py:50-131) | null | route-without-wireframe | FINDING: No wireframe; two dynamic routes. User list (plan, spend), detail (activity, quota, runs, spend USD), mutations (spend-cap, suspend). Operator-gated; testable: unauthenticated. |
| admin-settings | (none) | /admin/settings | GET /admin/settings, POST /admin/settings (admin.py:154-186) | null | route-without-wireframe | FINDING: No wireframe; /admin/settings/page.tsx. Global configuration. Operator-gated; testable: unauthenticated. |
| admin-audit-log | (none) | /admin/audit-log | GET /admin/audit-log (admin.py:188-201) | null | route-without-wireframe | FINDING: No wireframe; /admin/audit-log/page.tsx. Immutable audit log (actor, action, target, detail, ip). Operator-gated; testable: unauthenticated. |
| admin-spend | (none) | /admin/spend | GET /admin/spend (admin.py:138-153) | null | route-without-wireframe | FINDING: No wireframe; /admin/spend/page.tsx. Spend overview (USD). Operator-gated; testable: unauthenticated. |

---

## Coverage Gaps Summary (8 Findings)

**Routes Without Wireframes (ALL TESTABLE):**

1. `/` — Root redirect; redirect logic testable
2. `/login` — Critical path; login form + auth flow testable (canonical-login.md)
3. `/signup` — Critical path; registration testable
4. `/pricing` — Revenue-critical; billing plan checkout testable (unauthenticated)
5. `/privacy-policy` — Legal page; static rendering testable
6. `/terms` — Legal page; static rendering testable
7. `/admin/*` (6 routes) — Operator-gated admin cluster; unauthenticated access behavior testable; authenticated testing requires operator credential (HUMAN-GATED per governance/human-gated-admin.md)

**Wireframes Without Routes:** 0 (all 17 design/screens/ wireframes have routes)

---

## Reconciliation (G-01 Compliance)

- [x] **25 routes enumerated** — all mapped to >=1 matrix row
- [x] **29 matrix rows** — 17 wireframed + 12 routes without wireframes (1 root + 5 public + 6 admin)
- [x] **126 endpoints** — all mapped to screen(s) or infrastructure
- [x] **8 findings identified** — routes without wireframes; all testable per G-01
- [x] **0 orphans** — all 17 wireframes have routes
- [x] **Billing router mapped** — 5 endpoints split: /pricing (checkout) + /dashboard/settings (subscription)
- [x] **Admin router mapped** — 10 endpoints split across 6 admin routes
- [x] **Status: RECONCILED 25/25 routes**

---

## References

- Admin router: apps/api/app/routers/admin.py
- Billing router: apps/api/app/routers/billing.py
- Admin governance: uat/reports/evidence/manual-verification/governance/human-gated-admin.md
- Canonical login: uat/reports/evidence/manual-verification/canonical-login.md

---

## Final Verification Footer [VERIFIED-WITH-FRESH-EVIDENCE]

**Date:** 2026-07-20 · **Final production commit:** `54c28e5` · **Verified by:** doc-updater (exit-phase pass)

All **29 screen-matrix rows above received independent per-screen tester coverage** during the MANUAL-VERIFICATION run (each screen has a schema-complete `screens/<screen_id>/TESTING-OUTCOME-REPORT.md`, cross-referenced in `docs/delivery/MANUAL-VERIFICATION-FINAL-REPORT.md` §2's per-screen results table — 168 findings filed across all 29 rows, 129 VERIFIED-CLOSED / 28 accepted-deviation / 8 blocked-on-human / 3 other, 0 open). The exit-phase adversarial loop (§6/G-07 of the final report) re-swept the full matrix and produced zero new unresolved findings.

Fresh spot-check at close of run (this doc-updater pass, 2026-07-20): `GET https://5cb5f0620.abacusai.cloud/api/health` → `{"status":"ok","version":"0.2.0"}`; `systemctl is-active aether-api aether-web aether-worker redis-server aether-discovery.timer` → all `active`; production DB holds exactly 2 users (`admin@aether.local`, `sarkar.vikram@gmail.com`) confirmed via direct read-only query.

**Final verification status: RECONCILED 29/29 rows, all tester-covered, all findings terminal.** See `docs/delivery/MANUAL-VERIFICATION-FINAL-REPORT.md` for the complete per-screen ledger and gate table.
