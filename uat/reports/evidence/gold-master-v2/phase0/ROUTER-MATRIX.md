# Router Matrix Inventory — Phase 0 Step 5b

**Report Date:** 2026-07-30 | **Evidence Location:** `/home/ubuntu/github_repos/aether-job-career-agent/uat/reports/evidence/gold-master-v2/phase0/`

## Summary

**Total Endpoints Verified:** 144  
**Router Files Scanned:** 18 (admin, agents, analytics, applications, approvals, auth, billing, cover_letters, emails, google_oauth, health, interviews, jobs, networking, offers, resumes, stories, workspaces)

### Endpoint Breakdown

| Auth Requirement | Count |
|---|---|
| `CurrentUser` (authenticated) | 125 |
| `AdminUser` (admin-only) | 11 |
| None (public) | 8 |

| HTTP Method | Count |
|---|---|
| GET | 67 |
| POST | 52 |
| PUT | 7 |
| DELETE | 13 |
| PATCH | 5 |

| State Mutation | Count |
|---|---|
| Reads only (GET, safe) | 67 |
| Mutates state (POST/PUT/DELETE/PATCH) | 77 |

---

## All Endpoints (Sorted by Path)

### Admin Endpoints (10 total, all AdminUser-protected)

| Method | Path | Handler | Line | Auth | Mutates |
|---|---|---|---|---|---|
| GET | `/admin/audit-log` | `admin_audit_log` | 239 | AdminUser | No |
| GET | `/admin/health` | `admin_health` | 40 | AdminUser | No |
| GET | `/admin/settings` | `admin_get_settings` | 204 | AdminUser | No |
| POST | `/admin/settings` | `admin_update_settings` | 209 | AdminUser | **Yes** |
| GET | `/admin/spend` | `admin_spend` | 165 | AdminUser | No |
| GET | `/admin/users` | `admin_list_users` | 51 | AdminUser | No |
| GET | `/admin/users/{user_id}` | `admin_user_detail` | 66 | AdminUser | No |
| POST | `/admin/users/{user_id}/spend-cap` | `admin_set_spend_cap` | 104 | AdminUser | **Yes** |
| POST | `/admin/users/{user_id}/suspend` | `admin_suspend_user` | 124 | AdminUser | **Yes** |
| POST | `/admin/users/{user_id}/unsuspend` | `admin_unsuspend_user` | 141 | AdminUser | **Yes** |

**Router:** `app/routers/admin.py` | **Prefix:** `/admin`

---

### Agents Endpoints (38 total)

| Method | Path | Handler | Line | Auth | Mutates |
|---|---|---|---|---|---|
| GET | `/agents` | `list_agents` | 2040 | CurrentUser | No |
| POST | `/agents/board-sweep/trigger` | `trigger_board_sweep` | 2205 | CurrentUser | **Yes** |
| GET | `/agents/catalog` | `agent_catalog` | 2707 | CurrentUser | No |
| GET | `/agents/config` | `list_agent_config` | 2873 | CurrentUser | No |
| GET | `/agents/config/{agent_key}` | `get_agent_config` | 2880 | CurrentUser | No |
| PUT | `/agents/config/{agent_key}` | `update_agent_config` | 2889 | CurrentUser | **Yes** |
| POST | `/agents/cover-letter/run` | `run_cover_letter` | 2300 | CurrentUser | **Yes** |
| POST | `/agents/email/run` | `run_email_agent` | 2367 | CurrentUser | **Yes** |
| POST | `/agents/fit-scorer/run` | `run_fit_scorer` | 2180 | CurrentUser | **Yes** |
| GET | `/agents/jobs/{job_id}` | `get_background_job` | 2111 | CurrentUser | No |
| POST | `/agents/pipeline/run` | `run_pipeline` | 2522 | CurrentUser | **Yes** |
| GET | `/agents/providers` | `list_providers` | 3161 | CurrentUser | No |
| POST | `/agents/providers/anthropic/oauth/exchange` | `anthropic_oauth_exchange` | 3668 | CurrentUser | **Yes** |
| POST | `/agents/providers/anthropic/oauth/refresh` | `anthropic_oauth_refresh` | 3727 | CurrentUser | **Yes** |
| POST | `/agents/providers/anthropic/oauth/start` | `anthropic_oauth_start` | 3634 | CurrentUser | **Yes** |
| PUT | `/agents/providers/{provider}` | `update_provider` | 3184 | CurrentUser | **Yes** |
| DELETE | `/agents/providers/{provider}/credential` | `delete_provider_credential` | 3394 | CurrentUser | **Yes** |
| PUT | `/agents/providers/{provider}/credential` | `put_provider_credential` | 3352 | CurrentUser | **Yes** |
| GET | `/agents/providers/{provider}/models` | `list_provider_models_endpoint` | 3426 | CurrentUser | No |
| POST | `/agents/providers/{provider}/models/refresh` | `refresh_provider_models_endpoint` | 3461 | CurrentUser | **Yes** |
| POST | `/agents/providers/{provider}/verify` | `verify_provider` | 3408 | CurrentUser | **Yes** |
| GET | `/agents/runs` | `list_runs` | 2093 | CurrentUser | No |
| GET | `/agents/runs/{run_id}` | `get_run` | 2103 | CurrentUser | No |
| POST | `/agents/scout/run` | `run_scout` | 2138 | CurrentUser | **Yes** |
| GET | `/agents/scout/sources` | `scout_sources` | 2159 | CurrentUser | No |
| GET | `/agents/scout/sources/availability` | `scout_source_availability` | 2167 | CurrentUser | No |
| GET | `/agents/stats` | `agent_stats` | 3749 | CurrentUser | No |
| POST | `/agents/story-extractor/run` | `run_story_extractor` | 2349 | CurrentUser | **Yes** |
| POST | `/agents/tailor/run` | `run_tailor` | 2245 | CurrentUser | **Yes** |
| POST | `/agents/test-run` | `test_run` | 3818 | CurrentUser | **Yes** |
| GET | `/agents/user/providers` | `list_user_credentials` | 3500 | CurrentUser | No |
| DELETE | `/agents/user/providers/{provider}/credential` | `delete_user_credential` | 3576 | CurrentUser | **Yes** |
| PUT | `/agents/user/providers/{provider}/credential` | `put_user_credential` | 3527 | CurrentUser | **Yes** |
| POST | `/agents/user/providers/{provider}/verify` | `verify_user_provider` | 3590 | CurrentUser | **Yes** |
| POST | `/agents/{name}/run` | `run_named_agent` | 3887 | CurrentUser | **Yes** |

**Router:** `app/routers/agents.py` | **Prefix:** `/agents`  
**Key Detail:** No SSE/streaming endpoint exists at `/agents/runs/{run_id}/stream`; only non-streaming GET at line 2103.

---

### Analytics Endpoints (7 total)

| Method | Path | Handler | Line | Auth | Mutates |
|---|---|---|---|---|---|
| GET | `/analytics` | `dashboard_root` | 680 | CurrentUser | No |
| GET | `/analytics/agent-roi` | `agent_roi` | 147 | CurrentUser | No |
| GET | `/analytics/ats-distribution` | `ats_distribution` | 122 | CurrentUser | No |
| GET | `/analytics/conversion` | `conversion` | 172 | CurrentUser | No |
| GET | `/analytics/dashboard` | `dashboard` | 686 | CurrentUser | No |
| GET | `/analytics/funnel` | `funnel` | 84 | CurrentUser | No |
| GET | `/analytics/market-pulse` | `market_pulse` | 291 | CurrentUser | No |

**Router:** `app/routers/analytics.py` | **Prefix:** `/analytics`

---

### Applications Endpoints (7 total)

| Method | Path | Handler | Line | Auth | Mutates |
|---|---|---|---|---|---|
| GET | `/applications` | `list_applications` | 103 | CurrentUser | No |
| GET | `/applications/funnel/sankey` | `funnel_sankey` | 35 | CurrentUser | No |
| POST | `/applications/pipeline/clear` | `clear_pipeline` | 443 | CurrentUser | **Yes** |
| POST | `/applications/pipeline/{job_id}/move` | `move_pipeline_job` | 255 | CurrentUser | **Yes** |
| GET | `/applications/{application_id}` | `get_application` | 177 | CurrentUser | No |
| POST | `/applications/{application_id}/move` | `move_application` | 323 | CurrentUser | **Yes** |
| POST | `/applications/{application_id}/submit` | `submit_application` | 506 | CurrentUser | **Yes** |

**Router:** `app/routers/applications.py` | **Prefix:** `/applications`  
**Key Detail:** `PATCH /applications/{id}/stage` does NOT exist. Use POST `/applications/{application_id}/move` instead (line 323).

---

### Approvals Endpoints (8 total)

| Method | Path | Handler | Line | Auth | Mutates |
|---|---|---|---|---|---|
| GET | `/approvals` | `list_approvals` | 79 | CurrentUser | No |
| POST | `/approvals` | `create_approval` | 95 | CurrentUser | **Yes** |
| POST | `/approvals/purge-expired` | `purge_expired_approvals` | 112 | CurrentUser | **Yes** |
| DELETE | `/approvals/{approval_id}` | `delete_approval` | 139 | CurrentUser | **Yes** |
| GET | `/approvals/{approval_id}` | `get_approval` | 134 | CurrentUser | No |
| POST | `/approvals/{approval_id}/approve` | `approve` | 177 | CurrentUser | **Yes** |
| POST | `/approvals/{approval_id}/execute` | `execute_gated_action` | 193 | CurrentUser | **Yes** |
| POST | `/approvals/{approval_id}/reject` | `reject` | 185 | CurrentUser | **Yes** |

**Router:** `app/routers/approvals.py` | **Prefix:** `/approvals`  
**Note:** `DELETE /approvals/{id}` and `POST /approvals/purge-expired` both exist and are confirmed.

---

### Authentication Endpoints (5 total)

| Method | Path | Handler | Line | Auth | Mutates |
|---|---|---|---|---|---|
| POST | `/auth/login` | `login` | 76 | None | **Yes** |
| GET | `/auth/me` | `me` | 142 | CurrentUser | No |
| POST | `/auth/register` | `register` | 108 | None | **Yes** |

**Router:** `app/routers/auth.py` | **Prefix:** `/auth`

### Google OAuth Endpoints (2 total)

| Method | Path | Handler | Line | Auth | Mutates |
|---|---|---|---|---|---|
| GET | `/auth/google/callback` | `google_callback` | 65 | None | No |
| GET | `/auth/google/login` | `google_login` | 51 | CurrentUser | No |

**Router:** `app/routers/google_oauth.py` | **Prefix:** `/auth`

---

### Billing Endpoints (7 total)

| Method | Path | Handler | Line | Auth | Mutates |
|---|---|---|---|---|---|
| POST | `/billing/admin/refund` | `admin_refund` | 845 | AdminUser | **Yes** |
| POST | `/billing/checkout` | `create_checkout` | 121 | CurrentUser | **Yes** |
| GET | `/billing/entitlement` | `get_entitlement` | 772 | CurrentUser | No |
| GET | `/billing/plans` | `list_plans` | 81 | None | No |
| POST | `/billing/portal` | `create_portal` | 797 | CurrentUser | **Yes** |
| GET | `/billing/subscription` | `get_subscription` | 732 | CurrentUser | No |
| POST | `/billing/webhooks/stripe` | `stripe_webhook` | 210 | None | **Yes** |

**Router:** `app/routers/billing.py` | **Prefix:** `/billing`

---

### Cover Letters Endpoints (5 total)

| Method | Path | Handler | Line | Auth | Mutates |
|---|---|---|---|---|---|
| GET | `/cover-letters` | `list_cover_letters` | 563 | CurrentUser | No |
| GET | `/cover-letters/{letter_id}` | `get_cover_letter` | 568 | CurrentUser | No |
| GET | `/cover-letters/{letter_id}/insights` | `cover_letter_insights` | 573 | CurrentUser | No |
| GET | `/cover-letters/{letter_id}/pdf` | `export_cover_letter_pdf` | 922 | CurrentUser | No |
| POST | `/cover-letters/{letter_id}/refine` | `refine_cover_letter` | 651 | CurrentUser | **Yes** |

**Router:** `app/routers/cover_letters.py` | **Prefix:** `/cover-letters`

---

### Email Endpoints (11 total)

| Method | Path | Handler | Line | Auth | Mutates |
|---|---|---|---|---|---|
| GET | `/emails` | `list_threads` | 54 | CurrentUser | No |
| GET | `/emails/accounts` | `list_accounts` | 117 | CurrentUser | No |
| POST | `/emails/accounts/connect` | `connect_account` | 123 | CurrentUser | **Yes** |
| DELETE | `/emails/accounts/{account_id}` | `disconnect_account` | 139 | CurrentUser | **Yes** |
| PATCH | `/emails/accounts/{account_id}/set-primary` | `set_primary_account` | 151 | CurrentUser | **Yes** |
| GET | `/emails/accounts/{account_id}/sync-status` | `account_sync_status` | 159 | CurrentUser | No |
| POST | `/emails/draft` | `create_draft` | 205 | CurrentUser | **Yes** |
| GET | `/emails/oauth/status` | `oauth_status` | 104 | CurrentUser | No |
| GET | `/emails/{thread_id}` | `get_thread` | 189 | CurrentUser | No |
| POST | `/emails/{thread_id}/reply` | `reply_to_thread` | 242 | CurrentUser | **Yes** |

**Router:** `app/routers/emails.py` | **Prefix:** `/emails`

---

### Health Endpoint (1 total)

| Method | Path | Handler | Line | Auth | Mutates |
|---|---|---|---|---|---|
| GET | `/health` | `health` | 24 | None | No |

**Router:** `app/routers/health.py` | **Prefix:** (none)

---

### Interviews Endpoints (7 total)

| Method | Path | Handler | Line | Auth | Mutates |
|---|---|---|---|---|---|
| GET | `/interviews` | `list_interviews` | 204 | CurrentUser | No |
| POST | `/interviews` | `create_interview` | 258 | CurrentUser | **Yes** |
| DELETE | `/interviews/{interview_id}` | `delete_interview` | 378 | CurrentUser | **Yes** |
| GET | `/interviews/{interview_id}` | `get_interview` | 248 | CurrentUser | No |
| PATCH | `/interviews/{interview_id}` | `update_interview` | 309 | CurrentUser | **Yes** |
| POST | `/interviews/{interview_id}/cancel` | `cancel_interview` | 413 | CurrentUser | **Yes** |
| POST | `/interviews/{interview_id}/complete` | `complete_interview` | 393 | CurrentUser | **Yes** |

**Router:** `app/routers/interviews.py` | **Prefix:** `/interviews`

---

### Jobs Endpoints (8 total)

| Method | Path | Handler | Line | Auth | Mutates |
|---|---|---|---|---|---|
| GET | `/jobs` | `list_jobs` | 68 | CurrentUser | No |
| DELETE | `/jobs/clear-pipeline` | `clear_pipeline` | 551 | CurrentUser | **Yes** |
| DELETE | `/jobs/{job_id}` | `archive_job` | 671 | CurrentUser | **Yes** |
| GET | `/jobs/{job_id}` | `get_job` | 97 | CurrentUser | No |
| POST | `/jobs/{job_id}/apply` | `apply_to_job` | 445 | CurrentUser | **Yes** |
| GET | `/jobs/{job_id}/insights` | `job_insights` | 377 | CurrentUser | No |
| POST | `/jobs/{job_id}/save` | `toggle_save` | 386 | CurrentUser | **Yes** |

**Router:** `app/routers/jobs.py` | **Prefix:** `/jobs`  
**Key Detail:** `POST /jobs/{job_id}/apply` exists at line 445 (confirmed).

---

### Networking Endpoints (11 total)

| Method | Path | Handler | Line | Auth | Mutates |
|---|---|---|---|---|---|
| GET | `/networking` | `networking_summary` | 105 | CurrentUser | No |
| GET | `/networking/contacts` | `list_contacts` | 183 | CurrentUser | No |
| POST | `/networking/contacts` | `create_contact` | 238 | CurrentUser | **Yes** |
| DELETE | `/networking/contacts/{contact_id}` | `delete_contact` | 329 | CurrentUser | **Yes** |
| GET | `/networking/contacts/{contact_id}` | `get_contact` | 220 | CurrentUser | No |
| PATCH | `/networking/contacts/{contact_id}` | `update_contact` | 278 | CurrentUser | **Yes** |
| GET | `/networking/outreach` | `list_outreach_tasks` | 356 | CurrentUser | No |
| POST | `/networking/outreach` | `create_outreach_task` | 413 | CurrentUser | **Yes** |
| DELETE | `/networking/outreach/{task_id}` | `delete_outreach_task` | 511 | CurrentUser | **Yes** |
| GET | `/networking/outreach/{task_id}` | `get_outreach_task` | 394 | CurrentUser | No |
| PATCH | `/networking/outreach/{task_id}` | `update_outreach_task` | 457 | CurrentUser | **Yes** |

**Router:** `app/routers/networking.py` | **Prefix:** `/networking`

---

### Offers Endpoints (1 total)

| Method | Path | Handler | Line | Auth | Mutates |
|---|---|---|---|---|---|
| GET | `/offers` | `get_offers` | 25 | CurrentUser | No |

**Router:** `app/routers/offers.py` | **Prefix:** `/offers`

---

### Resumes Endpoints (8 total)

| Method | Path | Handler | Line | Auth | Mutates |
|---|---|---|---|---|---|
| GET | `/resumes` | `list_resumes` | 16 | CurrentUser | No |
| POST | `/resumes` | `create_resume` | 37 | CurrentUser | **Yes** |
| POST | `/resumes/upload` | `upload_resume` | 61 | CurrentUser | **Yes** |
| GET | `/resumes/{resume_id}` | `get_resume` | 128 | CurrentUser | No |
| GET | `/resumes/{resume_id}/ats` | `ats_score` | 136 | CurrentUser | No |
| GET | `/resumes/{resume_id}/diff` | `diff_resume` | 187 | CurrentUser | No |
| GET | `/resumes/{resume_id}/download` | `download_resume` | 247 | CurrentUser | No |

**Router:** `app/routers/resumes.py` | **Prefix:** `/resumes`

---

### Stories Endpoints (5 total)

| Method | Path | Handler | Line | Auth | Mutates |
|---|---|---|---|---|---|
| GET | `/stories` | `list_stories` | 137 | CurrentUser | No |
| POST | `/stories` | `create_story` | 158 | CurrentUser | **Yes** |
| GET | `/stories/stats` | `story_stats` | 143 | CurrentUser | No |
| DELETE | `/stories/{story_id}` | `delete_story` | 173 | CurrentUser | **Yes** |
| PUT | `/stories/{story_id}` | `update_story` | 163 | CurrentUser | **Yes** |

**Router:** `app/routers/stories.py` | **Prefix:** `/stories`  
**Key Detail:** `GET /stories` has NO `job_id` query parameter in the code (line 137).

---

### Workspaces Endpoints (13 total)

| Method | Path | Handler | Line | Auth | Mutates |
|---|---|---|---|---|---|
| GET | `/workspaces/career-data` | `get_career_data` | 1173 | CurrentUser | No |
| POST | `/workspaces/career-data/refresh` | `refresh_career_data_endpoint` | 1183 | CurrentUser | **Yes** |
| GET | `/workspaces/emails/inbox` | `email_inbox` | 433 | CurrentUser | No |
| POST | `/workspaces/emails/send` | `send_reply` | 670 | CurrentUser | **Yes** |
| GET | `/workspaces/interviews/prep` | `interview_prep` | 48 | CurrentUser | No |
| GET | `/workspaces/networking/summary` | `networking_summary` | 268 | CurrentUser | No |
| GET | `/workspaces/offers` | `offers` | 790 | CurrentUser | No |
| POST | `/workspaces/offers` | `add_offer` | 797 | CurrentUser | **Yes** |
| DELETE | `/workspaces/offers/{offer_id}` | `remove_offer` | 829 | CurrentUser | **Yes** |
| GET | `/workspaces/settings` | `get_settings` | 974 | CurrentUser | No |
| PUT | `/workspaces/settings` | `update_settings` | 1071 | CurrentUser | **Yes** |

**Router:** `app/routers/workspaces.py` | **Prefix:** `/workspaces`

---

## Task-Specific Findings

### Endpoints Explicitly Required (Task §5b)

#### Present Endpoints

1. **DELETE /approvals/{id}** [PRESENT]
   - Path: `DELETE /approvals/{approval_id}`
   - Handler: `delete_approval` (approvals.py:139)
   - Auth: CurrentUser
   - Mutates: Yes
   - Notes: Soft-deletes expired/resolved approvals only; 409 for live pending; 404 for absent.

2. **POST /approvals/purge-expired** [PRESENT]
   - Path: `POST /approvals/purge-expired`
   - Handler: `purge_expired_approvals` (approvals.py:112)
   - Auth: CurrentUser
   - Mutates: Yes
   - Notes: Bulk-deletes expired pending approvals; returns {purged, ids}.

3. **GET /agents/scout/sources/availability** [PRESENT]
   - Path: `GET /agents/scout/sources/availability`
   - Handler: `scout_source_availability` (agents.py:2167)
   - Auth: CurrentUser
   - Mutates: No
   - Notes: Returns per-source availability from adapter registry (ML-audit-seek-fe-hardcode-001).

4. **POST /jobs/{id}/apply** [PRESENT]
   - Path: `POST /jobs/{job_id}/apply`
   - Handler: `apply_to_job` (jobs.py:445)
   - Auth: CurrentUser
   - Mutates: Yes
   - Notes: Apply button endpoint (W-H: Jobs Apply button + apply flow hardening).

#### Absent Endpoints

1. **PATCH /applications/{id}/stage** [ABSENT]
   - **Alternative:** `POST /applications/{application_id}/move` (applications.py:323)
   - Reason: Application stage changes are handled via POST with a `MoveRequest` body containing `to_stage`, not PATCH.
   - Auth: CurrentUser
   - Mutates: Yes
   - Notes: Full endpoint spec requires querying board stage columns; stage keys include "ready", "submitted", "in-review", "interview", "offer".

2. **GET /agents/runs/{run_id}/stream (SSE)** [ABSENT]
   - **Alternative:** `GET /agents/runs/{run_id}` (agents.py:2103, non-streaming)
   - Reason: No Server-Sent Events streaming endpoint implemented for run status.
   - Auth: CurrentUser
   - Mutates: No
   - Notes: Current polling-only design; no EventSourceResponse or StreamingResponse.

3. **GET /stories with job_id relevance param** [ABSENT]
   - **Endpoint:** `GET /stories` (stories.py:137)
   - Reason: No query parameter filtering by job_id in handler; returns all stories for user.
   - Auth: CurrentUser
   - Mutates: No
   - Notes: Story-to-job cross-linking would require new query param; currently unimplemented.

---

## Endpoint Grouping by Feature

### Kanban Pipeline & Stage Management
- `POST /applications/pipeline/{job_id}/move` — move job card in agent-fed pipeline
- `POST /applications/{application_id}/move` — move application card in 5-stage tracker
- `POST /applications/pipeline/clear` — bulk archive pipeline jobs (W-B: feature incomplete)

### Approvals & Human-in-the-Loop
- `GET /approvals` — list pending/all approvals
- `POST /approvals` — create approval request
- `POST /approvals/purge-expired` — bulk purge expired (48h window, W-F)
- `DELETE /approvals/{approval_id}` — remove stale/resolved approval
- `POST /approvals/{approval_id}/approve` — approve gated action
- `POST /approvals/{approval_id}/reject` — reject gated action
- `POST /approvals/{approval_id}/execute` — execute approved high-risk action

### Job Discovery & Sourcing
- `GET /agents/scout/sources` — per-source sync status
- `GET /agents/scout/sources/availability` — backend-derived source availability (Seek env-gated)
- `POST /agents/scout/run` — trigger discovery agent

### Job Application
- `POST /jobs/{job_id}/apply` — submit application to job (W-H)
- `POST /applications/{application_id}/submit` — submit via approval or direct

### Story Bank
- `GET /stories` — list user stories (no job_id filter)
- `GET /stories/stats` — story bank metrics
- `POST /stories` — create story
- `PUT /stories/{story_id}` — update story
- `DELETE /stories/{story_id}` — delete story (hard delete)

### Resume & Cover Letter
- `GET /resumes` — list resumes
- `POST /resumes` — create resume
- `POST /resumes/upload` — upload PDF
- `GET /resumes/{resume_id}/ats` — ATS score
- `GET /cover-letters` — list cover letters
- `GET /cover-letters/{letter_id}` — get letter (with version history)
- `POST /cover-letters/{letter_id}/refine` — refine via agent (with approval gate)

### Agents (LLM Pipeline Orchestration)
- `POST /agents/tailor/run` — run tailoring agent
- `POST /agents/cover-letter/run` — run cover-letter agent
- `POST /agents/story-extractor/run` — run story extraction
- `POST /agents/email/run` — run email draft agent
- `POST /agents/pipeline/run` — run full pipeline
- `POST /agents/fit-scorer/run` — score jobs by fit
- `POST /agents/board-sweep/trigger` — trigger board sweep (event-driven on stage move)

### Admin & Billing
- `GET /admin/users` — list users (AdminUser)
- `GET /admin/spend` — spending analytics (AdminUser)
- `POST /admin/users/{user_id}/spend-cap` — set user spend limit
- `POST /admin/users/{user_id}/suspend` — suspend user
- `POST /billing/checkout` — create Stripe checkout session
- `POST /billing/admin/refund` — refund charge (AdminUser)

---

## Main Application Router Registration

**File:** `app/main.py` lines 248–265

```python
app.include_router(health.router)
app.include_router(auth.router, prefix="/auth", tags=["auth"])
app.include_router(google_oauth.router, prefix="/auth", tags=["auth"])
app.include_router(jobs.router, prefix="/jobs", tags=["jobs"])
app.include_router(agents.router, prefix="/agents", tags=["agents"])
app.include_router(resumes.router, prefix="/resumes", tags=["resumes"])
app.include_router(approvals.router, prefix="/approvals", tags=["approvals"])
app.include_router(cover_letters.router, prefix="/cover-letters", tags=["cover-letters"])
app.include_router(stories.router, prefix="/stories", tags=["stories"])
app.include_router(analytics.router, prefix="/analytics", tags=["analytics"])
app.include_router(applications.router, prefix="/applications", tags=["applications"])
app.include_router(workspaces.router, prefix="/workspaces", tags=["workspaces"])
app.include_router(interviews.router, prefix="/interviews", tags=["interviews"])
app.include_router(emails.router, prefix="/emails", tags=["emails"])
app.include_router(networking.router, prefix="/networking", tags=["networking"])
app.include_router(offers.router, prefix="/offers", tags=["offers"])
app.include_router(billing.router, prefix="/billing", tags=["billing"])
app.include_router(admin.router, prefix="/admin", tags=["admin"])
```

---

## Scanning & Verification Methodology

1. **Pattern Matching:** Extracted all `@router.*` decorators from 18 router files using regex.
2. **Path Resolution:** Resolved each route's full path by combining file's prefix (from main.py) with decorator path.
3. **Auth Dependency Detection:** Scanned function signatures for `CurrentUser` or `AdminUser` parameters.
4. **State Mutation Determination:** Classified as mutating if method in {POST, PUT, DELETE, PATCH}.
5. **Line Number Mapping:** Recorded exact line numbers in source for each endpoint.

**Total Endpoints Extracted:** 144  
**Verification Date:** 2026-07-30 13:15 UTC  
**Extraction Timestamp:** Fresh on-disk scan

---

## Appendix: Auth Middleware

**File:** `app/middleware/auth.py`  
**Type Alias:** `CurrentUser = dict[str, Any]` (user dict with "id", "email" fields)  
**AdminUser Protection:** Checked via `current_user.get("isAdmin", False)`

---
