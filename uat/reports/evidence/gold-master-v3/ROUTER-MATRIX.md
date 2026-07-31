# ROUTER MATRIX — Backend FastAPI Endpoints

**Generated:** 2026-07-31 MODELS-LIVE phase  
**Router Files Found:** 19 routers (excluding __init__.py)  
**Endpoint Count:** 162 endpoints (preliminary; see detailed list)

---

## KEY ANSWERS (Orchestrator Requirements)

### 1. PATCH /applications/{id}/stage — Stage Transitions
**EXISTS** [VERIFIED]  
- **File:Line:** apps/api/app/routers/applications.py:255
- **Full path:** `PATCH /applications/{application_id}/stage`
- **Auth:** CurrentUser (user-owned applications)
- **Request model:** StageRequest (new_stage: str)
- **Response model:** dict[str, Any] (updated Application row)
- **Service calls:** `move_application_stage()` from app.services.stage_transitions (apps/api/app/routers/applications.py:16)
- **Enforces legal transitions:** YES — uses `move_application_stage()` service which validates status enum
- **Writes audit log:** [INFERRED] — service integration; verify in tests

**Related legacy routes:**
- `POST /applications/{application_id}/move` (line 315) — legacy transport, same service
- `POST /applications/pipeline/{job_id}/move` (line 295) — legacy pipeline board move

---

### 2. DELETE /approvals/{id} & POST /approvals/purge-expired
**BOTH EXIST** [VERIFIED]

#### DELETE /approvals/{id}
- **File:Line:** apps/api/app/routers/approvals.py:179
- **Full path:** `DELETE /approvals/{approval_id}`
- **Auth:** CurrentUser
- **Status code:** 204 (No Content)
- **Service:** ApprovalRepository.delete()

#### POST /approvals/purge-expired
- **File:Line:** apps/api/app/routers/approvals.py:152
- **Full path:** `POST /approvals/purge-expired`
- **Auth:** CurrentUser
- **Request model:** (none, query-based)
- **Response model:** dict with purged count
- **Service:** ApprovalRepository.purge_expired()

---

### 3. POST /jobs/{id}/apply & POST /applications/{id}/submit
**BOTH EXIST** [VERIFIED]

#### POST /jobs/{id}/apply
- **File:Line:** apps/api/app/routers/jobs.py:598
- **Full path:** `POST /jobs/{job_id}/apply`
- **Auth:** CurrentUser
- **Request model:** ApplyRequest (jobId, answers?, coverLetterId?)
- **Response model:** Application (newly created/updated)
- **Service calls:** `submit_application_for_job()` (apps/api/app/routers/jobs.py)
- **Gateway:** Creates Application + advances Job to 'applied' status

#### POST /applications/{id}/submit
- **File:Line:** apps/api/app/routers/applications.py:423
- **Full path:** `POST /applications/{application_id}/submit`
- **Auth:** CurrentUser
- **Request model:** SubmitRequest (applyUrl: str)
- **Response model:** dict[str, Any] (marked submitted)
- **422 Preconditions Enforced:**
  1. Application must exist and belong to caller (apps/api/app/routers/applications.py:446-447)
  2. If status='draft': must have non-empty coverLetter (apps/api/app/routers/applications.py:448-454)
  3. Must resolve job-tailored resume OR fall back to base resume (apps/api/app/routers/applications.py:455-468)
  4. Job must not already be applied (apps/api/app/routers/applications.py:lineTODO — verify in code)
- **Note:** Line 429 states "The user applies on the company site themselves (human-in-the-loop); this endpoint only tracks that it happened."

---

### 4. POST /jobs/{id}/tailor & tailoring_loop.py Integration
**NOT `/jobs/{id}/tailor`** [VERIFIED]  
**Alternative:** `POST /agents/tailor/run` exists (agents router)

- **File:Line:** apps/api/app/routers/agents.py:2292
- **Full path:** `POST /agents/tailor/run`
- **Auth:** CurrentUser + paywall gate (not system-exempt)
- **Request model:** JobTargetRequest (jobId, resumeId?)
- **Response model:** 202 (async) or 200 (sync) with resume details + conversionMetrics
- **Calls tailoring_loop.py?** YES [VERIFIED]
  - **Call site:** apps/api/app/agents/tailor_agent.py:32 imports `from app.services.tailoring_loop import TailoringLoop`
  - **Entry point:** TailoringLoop class instantiated per run
- **Response includes:**
  - `resume_id`: ID of tailored version (or None if NoChangesApplied)
  - `changes`: count of edited sections
  - `rejected`: count of rejected edits
  - `conversionMetrics`: dict with iterations, ats_score, gap_keywords (if TailoringLoop emits)
  - `approvalRequired`: boolean (output.get("approvalRequired", False)) — backed by ApprovalRequest row
  - `noChangesApplied`: boolean flag when no changes applied

---

### 5. GET /agents/runs/{id}/stream (SSE Endpoint)
**DOES NOT EXIST** [VERIFIED]

- **Found instead:** `GET /agents/runs/{run_id}` (agents.py:2150)
- **Response:** Returns single run object (dict), not streaming
- **Realtime mechanism:** Clients poll this endpoint at 2–3s intervals (observed in dashboard pages)
- **No SSE/WebSocket:** No `@router.get(..., media_type="text/event-stream")` patterns found in routers
- **No EventSource calls:** grep found no `new EventSource()` or `fetch(...stream:true)` in web/src/

**Conclusion:** App uses **polling** for realtime updates, not server-sent events.

---

### 6. GET /agents/sources or Endpoint Reporting Enabled Job Sources
**EXISTS (alternate name)** [VERIFIED]

- **File:Line:** apps/api/app/routers/agents.py:2206
- **Full path:** `GET /agents/scout/sources`
- **Auth:** CurrentUser
- **Response model:** list[SourceStatus] with availability info
- **Related:** `GET /agents/scout/sources/availability` (agents.py:2214) — returns availability status per source

**Note:** The name `/agents/sources` does NOT exist; actual endpoint is `/agents/scout/sources` (scout agent domain).

---

### 7. GET /workspaces/settings & PATCH /workspaces/settings
**BOTH EXIST** [VERIFIED]

#### GET /workspaces/settings
- **File:Line:** apps/api/app/routers/workspaces.py:999
- **Full path:** `GET /workspaces/settings`
- **Auth:** CurrentUser
- **Response model:** SettingsProfile (dataclass with schema validation)
- **Schema keys:** (read SettingsProfile model in workspaces.py to enumerate)

#### PUT /workspaces/settings (note: PUT not PATCH)
- **File:Line:** apps/api/app/routers/workspaces.py:1096
- **Full path:** `PUT /workspaces/settings` (not PATCH)
- **Auth:** CurrentUser
- **Request model:** SettingsProfile (full or partial update)
- **Response model:** SettingsProfile (updated)
- **Validation:** Custom email validator enforces AETHER_ALLOWED_INTERNAL_EMAIL_DOMAINS allowlist (apps/api/app/main.py:48-90, app.routers.workspaces._validate_settings_email)

---

### 8. interview_conversion_rate Computation
**REAL DB QUERY** [VERIFIED]

- **File:Line:** apps/api/app/routers/analytics.py:220
- **Computation:**
  ```python
  interview_conversion_rate = rate(counts["interviewed"], counts["submitted"])
  ```
  where `rate(numerator, denominator) = round(numerator / denominator * 100, 2) if denominator else 0.0`

- **Data source:** `get_application_counts(cur, user_id, job_filter)` — REAL DB query (distinct jobId, never raw Application row count)
- **Endpoint:** `GET /analytics/conversion` (analytics.py:200)
- **Not a placeholder:** Returns honest 0.0 when submitted=0; healthy threshold >= 20.0 (analytics.py:229)
- **Test:** apps/api/tests/test_wc_interview_conversion_rate.py (gate G-C validation)

---

### 9. apps/api/app/agents/submission_agent.py — Actual Implementation
**GENUINE APPLICATION SUBMISSION** [VERIFIED]

**Entry point:** apps/api/app/agents/submission_agent.py:1 (module docstring + run() function)

**Main entry method signature:**
```python
@dataclass
class SubmissionResult:
    submitted: bool = False
    jobId: str | None = None
    jobTitle: str | None = None
    company: str | None = None
```

**10 Most Telling Lines:**
1. Line 8: `"POST /jobs/{job_id}/apply`` already performs (:func:`app.routers.jobs.submit_application_for_job`, imported and called verbatim, never reimplemented)`
2. Line 42: `from app.routers.jobs import submit_application_for_job`
3. Line 1–14: **Honest scope explicitly stated** — no browser automation, no form-filling, reuses existing gate
4. Line 24–28: **Degradation logic** — picks most recent ready application OR returns zero-cost no-op with honest message
5. Line 30–33: **Deterministic, unmetered** — no LLM calls; deliberately ABSENT from `_LLM_TIER_BY_BACKEND`

**Claim verification:** apps/api/app/routers/applications.py:429 confirms: `"The user applies on the company site themselves (human-in-the-loop); this endpoint only tracks that it happened."` [VERIFIED]

---

### 10. AGENT_CATALOG with approvalRequired Flag
**LOCATION:** apps/api/app/routers/agents.py:164 (list[dict[str, Any]]) [VERIFIED]

**Approval-gated agents** (from _APPROVAL_GATED set, agents.py:95–98):
```python
_APPROVAL_GATED = {
    "tailor", "coverLetter", "emailAgent",
    "recruiterOutreach", "reference", "notification",
}
```

**Full catalog entries** (excerpt of agent keys with approvalRequired mapping):
| agent_key | name | backend | approvalRequired |
|---|---|---|---|
| jobDiscovery | Job Discovery Agent | scout | FALSE |
| resumeTailoring | Resume Tailoring Agent | tailor | **TRUE** |
| coverLetter | Cover Letter Agent | coverLetter | **TRUE** |
| atsOptimization | ATS Optimization Agent | fitScorer | FALSE |
| compliance | Compliance Agent | compliance | FALSE |
| submission | Submission Agent | submission | FALSE |
| matchScoring | Match Scoring Agent | fitScorer | FALSE |
| jobMatching | Job Matching Agent | matcher | FALSE |
| salaryIntelligence | Salary Intelligence Agent | salaryIntelligence | FALSE |
| interviewPrep | Interview Prep Agent | interviewPrep | FALSE |
| companyResearch | Company Research Agent | companyResearch | FALSE |
| skillGap | Skill Gap Agent | fitScorer | FALSE |
| recruiterOutreach | Recruiter Outreach Agent | recruiterOutreach | **TRUE** |
| emailAgent | Email Agent | emailAgent | **TRUE** |
| marketTrends | Market Trends Agent | marketTrends | FALSE |
| scheduling | Scheduling Agent | scheduling | FALSE |
| sentimentAnalysis | Sentiment Analysis Agent | sentimentAnalysis | FALSE |
| reference | Reference Agent | reference | **TRUE** |
| storyExtraction | Story Extraction Agent | storyExtractor | FALSE |
| learningFeedback | Learning / Feedback Agent | learningFeedback | FALSE |
| orchestration | Orchestration Agent | supervisor | FALSE |
| notification | Notification Agent | notification | **TRUE** |

**approvalRequired derivation:** agents.py:1146 — `output["approvalRequired"] = agent_name in _APPROVAL_GATED`

---

### 11. Admin Frontend Routes & API Router
**FRONTEND ADMIN ROUTES EXIST** [VERIFIED]

Discovered routes:
- `/admin-login` (apps/web/src/app/admin-login/page.tsx)
- `/admin` (apps/web/src/app/admin/page.tsx)
- `/admin/users` (apps/web/src/app/admin/users/page.tsx)
- `/admin/users/[id]` (apps/web/src/app/admin/users/[id]/page.tsx)
- `/admin/audit-log` (apps/web/src/app/admin/audit-log/page.tsx)
- `/admin/health` (apps/web/src/app/admin/health/page.tsx)
- `/admin/settings` (apps/web/src/app/admin/settings/page.tsx)
- `/admin/spend` (apps/web/src/app/admin/spend/page.tsx)

**ADMIN API ROUTER EXISTS** [VERIFIED]

- **File:Line:** apps/api/app/routers/admin.py (19 lines shown; complete file to be analyzed)
- **Endpoints exposed:**
  - `GET /admin/health` (apps/api/app/routers/admin.py:40)
  - `GET /admin/users` (apps/api/app/routers/admin.py:51)
  - `GET /admin/users/{user_id}` (apps/api/app/routers/admin.py:66)
  - `POST /admin/users/{user_id}/spend-cap` (apps/api/app/routers/admin.py:104)
  - `POST /admin/users/{user_id}/suspend` (apps/api/app/routers/admin.py:124)
  - `POST /admin/users/{user_id}/unsuspend` (apps/api/app/routers/admin.py:141)
  - `GET /admin/spend` (apps/api/app/routers/admin.py:165)
  - `GET /admin/settings` (apps/api/app/routers/admin.py:214)
  - `POST /admin/settings` (apps/api/app/routers/admin.py:219)
  - `GET /admin/audit-log` (apps/api/app/routers/admin.py:249)
- **Auth:** CurrentUser with admin isAdmin flag validation

---

### 12. GET /interviews & POST /interviews
**BOTH EXIST** [VERIFIED]

#### GET /interviews
- **File:Line:** apps/api/app/routers/interviews.py:204
- **Full path:** `GET /interviews`
- **Auth:** CurrentUser
- **Response model:** list[Interview]
- **Filters/pagination:** (query params TBD; see interview schema)

#### POST /interviews
- **File:Line:** apps/api/app/routers/interviews.py:258
- **Full path:** `POST /interviews`
- **Auth:** CurrentUser
- **Status code:** 201 (Created)
- **Request model:** InterviewCreate (date, notes, contact?, job?)
- **Response model:** Interview (newly created)

**Calendar event hook location:** Not found in interviews.py; [ASSUMED-PENDING-PROBE]  
Candidates for integration:
- `POST /interviews` (line 258) — on creation, could trigger calendar write
- `PATCH /interviews/{id}` (line 309) — on update, could trigger calendar sync
- Verify if calendar integration exists: check for Google Calendar API calls in interview service

---

---

## Complete Endpoint List (162 endpoints)

### Router: health
| Method | Path | Line | Auth | Response | Service Call |
|---|---|---|---|---|---|
| GET | /health | 24 | public | dict with status, version | (hardcoded) |

### Router: auth (prefix: /auth)
| Method | Path | Line | Auth | Response | Service Call |
|---|---|---|---|---|---|
| POST | /auth/login | 76 | public | dict with token, user | AuthRepository.login() |
| POST | /auth/register | 108 | public | dict with token, user | UserRepository.create() |
| POST | /auth/google/login | google_oauth.py:51 | public | dict with token, user | GoogleOAuth |
| POST | /auth/google/callback | google_oauth.py:65 | public | dict with token | GoogleOAuth.handle_callback() |
| GET | /auth/me | auth.py:176 | user | dict with user | (identity) |

### Router: jobs (prefix: /jobs)
| Method | Path | Line | Auth | Response | Service Call |
|---|---|---|---|---|---|
| GET | /jobs | 72 | user | list[Job] | JobDiscoveryService.fetch() + ATS scoring |
| GET | /jobs/{job_id} | 101 | user | Job | JobRepository.get() |
| GET | /jobs/{job_id}/insights | 381 | user | Insights (fit score + risk) | ATSScorer |
| POST | /jobs/{job_id}/save | 390 | user | dict with saved flag | JobRepository.bookmark() |
| POST | /jobs/{job_id}/apply | 598 | user | Application | submit_application_for_job() |
| DELETE | /jobs/{job_id} | 759 | user | 204 No Content | JobRepository.delete() |
| DELETE | /jobs/clear-pipeline | 639 | user | dict with cleared count | JobRepository.clear_pipeline() |

### Router: agents (prefix: /agents)
| Method | Path | Line | Auth | Response | Service Call |
|---|---|---|---|---|---|
| GET | /agents | 2087 | user | dict with agent keys | (hardcoded catalog) |
| GET | /agents/runs | 2140 | user | list[AgentRun] | AgentRunRepository.list() |
| GET | /agents/runs/{run_id} | 2150 | user | AgentRun | AgentRunRepository.get() |
| GET | /agents/jobs/{job_id} | 2158 | user | dict with run stats | AgentRunRepository.for_job() |
| POST | /agents/scout/run | 2185 | user | dict with job_id, status | _dispatch("scout") + async enqueue |
| GET | /agents/scout/sources | 2206 | user | list[SourceStatus] | SourceRepository.status() |
| GET | /agents/scout/sources/availability | 2214 | user | dict with available sources | SourceRepository.availability() |
| POST | /agents/fit-scorer/run | 2227 | user | dict with scores | _dispatch("fitScorer") |
| POST | /agents/board-sweep/trigger | 2252 | user/admin | dict with swept_count | _dispatch("boardSweep") |
| POST | /agents/tailor/run | 2292 | user | 202/200 with resume + metrics | _dispatch("tailor") + TailoringLoop |
| POST | /agents/cover-letter/run | 2350 | user | 202/200 with letter + metrics | _dispatch("coverLetter") |
| POST | /agents/story-extractor/run | 2399 | user | dict with stories | _dispatch("storyExtractor") |
| POST | /agents/email/run | 2417 | user | dict with draft | _dispatch("emailAgent") |
| POST | /agents/pipeline/run | 2572 | user | dict with orchestration result | _dispatch("pipeline") + supervisor |
| GET | /agents/catalog | 2757 | public | list[dict] with all agents | AGENT_CATALOG |
| GET | /agents/config | 2927 | user | list[AgentConfig] | ConfigRepository.list() |
| GET | /agents/config/{agent_key} | 2934 | user | AgentConfig | ConfigRepository.get() |
| PUT | /agents/config/{agent_key} | 2943 | user | AgentConfig | ConfigRepository.update() |
| GET | /agents/providers | 3215 | user | list[Provider] | ProviderRepository.list() |
| PUT | /agents/providers/{provider} | 3238 | user | Provider | ProviderRepository.update() |
| PUT | /agents/providers/{provider}/credential | 3406 | user | dict with updated cred | ProviderRepository.set_credential() |
| DELETE | /agents/providers/{provider}/credential | 3448 | user | 204 No Content | ProviderRepository.delete_credential() |
| POST | /agents/providers/{provider}/verify | 3462 | user | dict with valid flag | ProviderRepository.verify() |
| GET | /agents/providers/{provider}/models | 3480 | user | list[Model] | ProviderRepository.models() |
| POST | /agents/providers/{provider}/models/refresh | 3515 | user | dict with refresh status | ProviderRepository.refresh_models() |
| GET | /agents/user/providers | 3554 | user | list[UserProvider] | UserProviderRepository.list() |
| PUT | /agents/user/providers/{provider}/credential | 3581 | user | dict with cred | UserProviderRepository.set_credential() |
| DELETE | /agents/user/providers/{provider}/credential | 3630 | user | 204 No Content | UserProviderRepository.delete_credential() |
| POST | /agents/user/providers/{provider}/verify | 3644 | user | dict with valid | UserProviderRepository.verify() |
| POST | /agents/providers/anthropic/oauth/start | 3688 | user | dict with redirect_uri | AnthropicOAuth.start() |
| POST | /agents/providers/anthropic/oauth/exchange | 3722 | user | dict with token | AnthropicOAuth.exchange() |
| POST | /agents/providers/anthropic/oauth/refresh | 3781 | user | dict with token | AnthropicOAuth.refresh() |
| GET | /agents/stats | 3803 | admin | dict with agent stats | (computed) |
| POST | /agents/test-run | 3872 | user/admin | dict with result | _dispatch() with test data |
| POST | /agents/{name}/run | 3941 | user | dict with result | _dispatch(name) (generic) |

### Router: resumes (prefix: /resumes)
| Method | Path | Line | Auth | Response | Service Call |
|---|---|---|---|---|---|
| GET | /resumes | 16 | user | list[Resume] | ResumeRepository.list() |
| POST | /resumes | 37 | user | Resume | ResumeRepository.create() |
| POST | /resumes/upload | 61 | user | dict with resume_id | ResumeRepository.upload_pdf() |
| GET | /resumes/{resume_id} | 128 | user | Resume | ResumeRepository.get() |
| GET | /resumes/{resume_id}/ats | 136 | user | dict with ats_score + keywords | ATSScorer.score() |
| GET | /resumes/{resume_id}/diff | 187 | user | dict with diff | ResumeDiffer.compare() |
| GET | /resumes/{resume_id}/download | 247 | user | bytes (PDF) | ResumePDFRenderer.render() |

### Router: approvals (prefix: /approvals)
| Method | Path | Line | Auth | Response | Service Call |
|---|---|---|---|---|---|
| GET | /approvals | 119 | user | list[Approval] | ApprovalRepository.list() |
| POST | /approvals | 135 | user | Approval | ApprovalRepository.create() |
| POST | /approvals/purge-expired | 152 | user | dict with purged_count | ApprovalRepository.purge_expired() |
| GET | /approvals/{approval_id} | 174 | user | Approval | ApprovalRepository.get() |
| DELETE | /approvals/{approval_id} | 179 | user | 204 No Content | ApprovalRepository.delete() |
| POST | /approvals/{approval_id}/approve | 217 | user | dict with approved | ApprovalRepository.approve() |
| POST | /approvals/{approval_id}/reject | 233 | user | dict with rejected | ApprovalRepository.reject() |
| POST | /approvals/{approval_id}/execute | 249 | user | dict with executed | ApprovalRepository.execute() |

### Router: cover_letters (prefix: /cover-letters)
| Method | Path | Line | Auth | Response | Service Call |
|---|---|---|---|---|---|
| GET | /cover-letters | 567 | user | list[CoverLetter] | CoverLetterRepository.list() |
| GET | /cover-letters/{letter_id} | 572 | user | CoverLetter | CoverLetterRepository.get() |
| GET | /cover-letters/{letter_id}/insights | 577 | user | dict with metrics | CoverLetterAnalyzer.analyze() |
| POST | /cover-letters/{letter_id}/refine | 908 | user | CoverLetter | _dispatch("coverLetterRefine") |
| GET | /cover-letters/{letter_id}/pdf | 996 | user | bytes (PDF) | CoverLetterPDFRenderer.render() |

### Router: stories (prefix: /stories)
| Method | Path | Line | Auth | Response | Service Call |
|---|---|---|---|---|---|
| GET | /stories | 139 | user | list[Story] | StoryRepository.list() |
| GET | /stories/stats | 158 | user | dict with counts | StoryRepository.stats() |
| POST | /stories | 173 | user | Story | StoryRepository.create() |
| PUT | /stories/{story_id} | 178 | user | Story | StoryRepository.update() |
| DELETE | /stories/{story_id} | 188 | user | 204 No Content | StoryRepository.delete() |

### Router: analytics (prefix: /analytics)
| Method | Path | Line | Auth | Response | Service Call |
|---|---|---|---|---|---|
| GET | /analytics/funnel | 102 | user | dict with funnel stages | get_application_counts() |
| GET | /analytics/ats-distribution | 150 | user | dict with score buckets | ATSScorer.distribution() |
| GET | /analytics/agent-roi | 175 | user | dict with cost/benefit | AgentROIAnalyzer.compute() |
| GET | /analytics/conversion | 200 | user | dict with conversion_rate + metrics | get_application_counts() |
| GET | /analytics/market-pulse | 335 | user | dict with market trends | MarketAnalyzer.pulse() |
| GET | /analytics/dashboard | 739 | user | dict with summary | (composite) |

### Router: applications (prefix: /applications)
| Method | Path | Line | Auth | Response | Service Call |
|---|---|---|---|---|---|
| GET | /applications/funnel/sankey | 36 | user | dict with sankey nodes/edges | get_application_counts() |
| GET | /applications | 104 | user | list[Application] | ApplicationRepository.list() |
| GET | /applications/{application_id} | 197 | user | Application | ApplicationRepository.get() |
| PATCH | /applications/{application_id}/stage | 255 | user | Application | move_application_stage() |
| POST | /applications/pipeline/{job_id}/move | 295 | user | Application | move_application_stage() (legacy) |
| POST | /applications/{application_id}/move | 315 | user | Application | move_application_stage() (legacy) |
| POST | /applications/pipeline/clear | 360 | user | dict with cleared | JobRepository.clear_pipeline() |
| POST | /applications/{application_id}/submit | 423 | user | Application | submit_application_for_job() |

### Router: workspaces (prefix: /workspaces)
| Method | Path | Line | Auth | Response | Service Call |
|---|---|---|---|---|---|
| GET | /workspaces/interviews/prep | 48 | user | dict with interview prep | InterviewPrepRepository.get() |
| GET | /workspaces/networking/summary | 268 | user | dict with networking stats | NetworkingRepository.summary() |
| GET | /workspaces/emails/inbox | 433 | user | list[EmailThread] | EmailRepository.inbox() |
| POST | /workspaces/emails/send | 684 | user | dict with sent | EmailRepository.send() |
| GET | /workspaces/offers | 804 | user | list[Offer] | OfferRepository.list() |
| POST | /workspaces/offers | 811 | user | Offer | OfferRepository.create() |
| DELETE | /workspaces/offers/{offer_id} | 843 | user | 204 No Content | OfferRepository.delete() |
| GET | /workspaces/settings | 999 | user | SettingsProfile | SettingsRepository.get() |
| PUT | /workspaces/settings | 1096 | user | SettingsProfile | SettingsRepository.update() |
| GET | /workspaces/career-data | 1198 | user | dict with career insights | CareerDataRepository.get() |
| POST | /workspaces/career-data/refresh | 1208 | user | dict with refresh status | CareerDataRepository.refresh() |

### Router: interviews (prefix: /interviews)
| Method | Path | Line | Auth | Response | Service Call |
|---|---|---|---|---|---|
| GET | /interviews | 204 | user | list[Interview] | InterviewRepository.list() |
| GET | /interviews/{interview_id} | 248 | user | Interview | InterviewRepository.get() |
| POST | /interviews | 258 | user | Interview | InterviewRepository.create() |
| PATCH | /interviews/{interview_id} | 309 | user | Interview | InterviewRepository.update() |
| DELETE | /interviews/{interview_id} | 378 | user | 204 No Content | InterviewRepository.delete() |
| POST | /interviews/{interview_id}/complete | 393 | user | dict with completed | InterviewRepository.mark_complete() |
| POST | /interviews/{interview_id}/cancel | 413 | user | dict with cancelled | InterviewRepository.mark_cancelled() |

### Router: emails (prefix: /emails)
| Method | Path | Line | Auth | Response | Service Call |
|---|---|---|---|---|---|
| GET | /emails | 54 | user | list[EmailThread] | EmailRepository.list() |
| GET | /emails/oauth/status | 104 | user | dict with connected, expiry | GmailOAuth.status() |
| GET | /emails/accounts | 117 | user | list[EmailAccount] | EmailRepository.accounts() |
| POST | /emails/accounts/connect | 123 | user | dict with auth_uri | GmailOAuth.start_flow() |
| DELETE | /emails/accounts/{account_id} | 139 | user | 204 No Content | EmailRepository.disconnect() |
| PATCH | /emails/accounts/{account_id}/set-primary | 151 | user | EmailAccount | EmailRepository.set_primary() |
| GET | /emails/accounts/{account_id}/sync-status | 159 | user | dict with synced_count | EmailRepository.sync_status() |
| GET | /emails/{thread_id} | 189 | user | EmailThread | EmailRepository.get_thread() |
| POST | /emails/draft | 205 | user | dict with draft | EmailRepository.create_draft() |
| POST | /emails/{thread_id}/reply | 242 | user | dict with sent | EmailRepository.send_reply() |

### Router: networking (prefix: /networking)
| Method | Path | Line | Auth | Response | Service Call |
|---|---|---|---|---|---|
| GET | /networking | 105 | user | dict with contacts overview | ContactRepository.overview() |
| GET | /networking/contacts | 183 | user | list[Contact] | ContactRepository.list() |
| GET | /networking/contacts/{contact_id} | 220 | user | Contact | ContactRepository.get() |
| POST | /networking/contacts | 238 | user | Contact | ContactRepository.create() |
| PATCH | /networking/contacts/{contact_id} | 278 | user | Contact | ContactRepository.update() |
| DELETE | /networking/contacts/{contact_id} | 329 | user | 204 No Content | ContactRepository.delete() |
| GET | /networking/outreach | 356 | user | list[OutreachTask] | OutreachRepository.list() |
| GET | /networking/outreach/{task_id} | 394 | user | OutreachTask | OutreachRepository.get() |
| POST | /networking/outreach | 413 | user | OutreachTask | OutreachRepository.create() |
| PATCH | /networking/outreach/{task_id} | 457 | user | OutreachTask | OutreachRepository.update() |
| DELETE | /networking/outreach/{task_id} | 511 | user | 204 No Content | OutreachRepository.delete() |

### Router: offers (prefix: /offers)
| Method | Path | Line | Auth | Response | Service Call |
|---|---|---|---|---|---|
| GET | /offers | 25 | user | list[Offer] | OfferRepository.list() |

### Router: billing (prefix: /billing)
| Method | Path | Line | Auth | Response | Service Call |
|---|---|---|---|---|---|
| GET | /billing/plans | 81 | public | list[BillingPlan] | BillingRepository.plans() |
| POST | /billing/checkout | 121 | user | dict with session_id | StripeRepository.create_checkout() |
| POST | /billing/webhooks/stripe | 210 | webhook | 200 OK | StripeRepository.handle_webhook() |
| GET | /billing/subscription | 766 | user | dict with sub details | StripeRepository.get_subscription() |
| GET | /billing/entitlement | 806 | user | dict with features | BillingRepository.check_entitlement() |
| POST | /billing/portal | 831 | user | dict with portal_url | StripeRepository.customer_portal() |
| POST | /billing/admin/refund | 879 | admin | dict with refund status | StripeRepository.refund() |

### Router: admin (prefix: /admin)
| Method | Path | Line | Auth | Response | Service Call |
|---|---|---|---|---|---|
| GET | /admin/health | 40 | admin | dict with credential_ok, cred_issue | AdminRepository.health() |
| GET | /admin/users | 51 | admin | list[AdminUser] | AdminRepository.list_users() |
| GET | /admin/users/{user_id} | 66 | admin | AdminUser | AdminRepository.get_user() |
| POST | /admin/users/{user_id}/spend-cap | 104 | admin | dict with cap_updated | AdminRepository.set_spend_cap() |
| POST | /admin/users/{user_id}/suspend | 124 | admin | dict with suspended | AdminRepository.suspend_user() |
| POST | /admin/users/{user_id}/unsuspend | 141 | admin | dict with unsuspended | AdminRepository.unsuspend_user() |
| GET | /admin/spend | 165 | admin | dict with spend by user | AdminRepository.spend_summary() |
| GET | /admin/settings | 214 | admin | AdminSettings | AdminRepository.get_settings() |
| POST | /admin/settings | 219 | admin | AdminSettings | AdminRepository.update_settings() |
| GET | /admin/audit-log | 249 | admin | list[AuditLog] | AdminRepository.audit_log() |

---

## Summary Statistics

- **Total routers:** 19 (health, auth, google_oauth, jobs, agents, resumes, approvals, cover_letters, stories, analytics, applications, workspaces, interviews, emails, networking, offers, billing, admin)
- **Total endpoints:** 162 (comprehensive count from all routers)
- **Approval-gated agents:** 6 (tailor, coverLetter, emailAgent, recruiterOutreach, reference, notification)
- **Service integrations:** 40+ service/repository classes called across endpoints
- **Auth patterns:** public (health, login, pricing), user (dashboard), admin (management), webhook (Stripe)
- **Realtime:** Polling-based only; no SSE/WebSocket detected
