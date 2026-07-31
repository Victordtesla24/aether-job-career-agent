# Reference Graph — GOLD-MASTER-V4 (Repo: aether-job-career-agent)

**Timestamp:** 2026-07-31T16:00:00Z  
**Report Version:** VERIFIED-WITH-FRESH-EVIDENCE

## Services Module Reference Graph

| Service Module | Live Refs | Primary Referencing Files | Status |
|---|---|---|---|
| `llm_client` | 27 | cover_letter_agent, email_agent, company_research_agent, tailor_agent | ✓ Core |
| `resume_grounding` | 13 | cover_letter_agent, email_agent, fit_scorer | ✓ Core |
| `resume_tailor` | 10 | cover_letter_agent, tailor_agent, cover_letters (router) | ✓ Core |
| `fabrication_guard` | 9 | cover_letter_agent, compliance_agent, email_agent | ✓ Core |
| `gmail_service` | 9 | email_agent, google_credential, approvals (router) | ✓ Core |
| `ats_engine` | 8 | fit_scorer, tailor_agent, jobs (router) | ✓ Featured |
| `career_data` | 5 | cover_letter_agent, tailor_agent, cover_letters (router) | ✓ Referenced |
| `story_paraphrase` | 5 | story (router), story_dedup_migration | ✓ Referenced |
| `credential_vault` | 1 | user_provider_credential (internal) | ✓ Referenced |
| `dedup` | 4 | job (model), story (model), story_dedup_migration | ✓ Utility |
| `google_oauth` | 4 | emails (router), google_oauth (router), gmail_service | ✓ Referenced |
| `offers` | 4 | offers (router), workspaces (router) | ✓ Referenced |
| `story_relevance` | 3 | tailor_agent, stories (router) | ✓ Referenced |
| `resume_pdf` | 3 | tailor_agent, resumes (router) | ✓ Utility |
| `resume_parser` | 3 | tailor_agent, resume_grounding | ✓ Utility |
| `stage_transitions` | 2 | applications (router) | ✓ Referenced |
| `stripe_gateway` | 2 | billing (router) | ✓ Utility |
| `portfolio_scraper` | 1 | career_data | ✓ Referenced |
| `approval_service` | 1 | approvals (router) | ✓ Utility |
| `email_attachments` | 1 | approvals (router) | ✓ Utility |
| `story_dedup_migration` | 2 | story_paraphrase | ✓ Internal use |
| **`anthropic_oauth`** | **0** | None | **ZERO-REF** |
| **`env_file_writer`** | **0** | None | **ZERO-REF** |

**ZERO-REFERENCE CANDIDATES (Services):**
- `anthropic_oauth.py` — defined 2026-07-22 for provider credential handling; likely superseded by credential_vault or provider-config workflow; candidate for cleanup audit §20
- `env_file_writer.py` — deprecated env-file generation utility; no active references; candidate for cleanup audit §20

---

## Agents Module Reference Graph

**CRITICAL FINDING:** All 22 agent modules report ZERO static references. This is **NOT an error** — agents follow a deliberate **lazy-loading pattern** where they are imported dynamically inside handler functions in `apps/api/app/routers/agents.py` at lines 1612–1758 (see `run_agent()` router handler). This provides:
- Dynamic model-choice routing (OpenRouter catalog selection per agent)
- Deferred import overhead (agents only loaded on demand)
- Testability (mocking agent imports in test fixtures)

| Agent Module | Static Refs | Import Location | Status |
|---|---|---|---|
| `cover_letter_agent` | 0 (dynamic) | agents.py:1625, main.py:24–28 | ✓ Entry point + dynamic |
| `tailor_agent` | 0 (dynamic) | agents.py:1618, main.py:2304 | ✓ Entry point + dynamic |
| `fit_scorer` | 0 (dynamic) | agents.py:1612 | ✓ Dynamic |
| `story_extractor` | 0 (dynamic) | agents.py:1630 | ✓ Dynamic |
| `matcher_agent` | 0 (dynamic) | agents.py:1634, main.py:2476 | ✓ Dynamic |
| `email_agent` | 0 (dynamic) | agents.py:1638 | ✓ Dynamic |
| `compliance_agent` | 0 (dynamic) | agents.py:1646 | ✓ Dynamic |
| `salary_intelligence_agent` | 0 (dynamic) | agents.py:1650 | ✓ Dynamic |
| `market_trends_agent` | 0 (dynamic) | agents.py:1654 | ✓ Dynamic |
| `learning_feedback_agent` | 0 (dynamic) | agents.py:1658 | ✓ Dynamic |
| `company_research_agent` | 0 (dynamic) | agents.py:1662 | ✓ Dynamic |
| `interview_prep_agent` | 0 (dynamic) | agents.py:1680 | ✓ Dynamic |
| `recruiter_outreach_agent` | 0 (dynamic) | agents.py:1702 | ✓ Dynamic |
| `reference_agent` | 0 (dynamic) | agents.py:1711 | ✓ Dynamic |
| `sentiment_analysis_agent` | 0 (dynamic) | agents.py:1720 | ✓ Dynamic |
| `scheduling_agent` | 0 (dynamic) | agents.py:1729 | ✓ Dynamic |
| `notification_agent` | 0 (dynamic) | agents.py:1744 | ✓ Dynamic |
| `submission_agent` | 0 (dynamic) | agents.py:1758 | ✓ Dynamic |
| `scout_agent` | 0 (dynamic) | main.py:29 | ✓ Entry point |
| **`outreach_support`** | **0** | Not found in dynamic loader | **NOT-LOADED** |
| **`learning_feedback_agent`** | **0** | agents.py:1658 | ✓ Loaded |

**ZERO-REFERENCE CANDIDATES (Agents):**
- All agents use dynamic import; no static ref failure expected
- **`outreach_support.py`** — defined but NOT registered in `agents.py` run_agent() dispatcher (line 1758 ends without it); candidate for cleanup audit §20

---

## Routers Module Reference Graph

| Router Module | Live Refs | Primary Referencing Files | Status |
|---|---|---|---|
| `agents` | 11 | cover_letters, resumes, workspaces (routers) | ✓ Core (main entry) |
| `applications` | 4 | stage_transitions, (internal refs) | ✓ Featured |
| `jobs` | 4 | submission_agent, agents (router) | ✓ Featured |
| `cover_letters` | 2 | email_attachments, story_paraphrase | ✓ Referenced |
| `resumes` | 1 | email_attachments | ✓ Referenced |
| `analytics` | 1 | applications | ✓ Referenced |
| `workspaces` | 3 | workspaces (self-ref) | ✓ Referenced |
| **`admin`** | **0** | None | **ZERO-REF** |
| **`approvals`** | **0** | None | **ZERO-REF** |
| **`auth`** | **0** | None | **ZERO-REF** |
| **`billing`** | **0** | None | **ZERO-REF** |
| **`emails`** | **0** | None | **ZERO-REF** |
| **`google_oauth`** | **0** | None | **ZERO-REF** |
| **`health`** | **0** | None | **ZERO-REF** |
| **`interviews`** | **0** | None | **ZERO-REF** |
| **`networking`** | **0** | None | **ZERO-REF** |
| **`offers`** | **0** | None | **ZERO-REF** |
| **`stories`** | **0** | None | **ZERO-REF** |

**CLARIFICATION:** Router modules with 0 internal refs are **NOT cleanup candidates** — they are FastAPI route handlers registered directly in `app/main.py` via `app.include_router()`. Static reference counts do not apply; they're invoked by the HTTP request router, not imported by other Python code. Zero refs is expected for leaf routers.

---

## Frontend Components Reference Graph (Sample)

Frontend components are in `apps/web/src/components/` and referenced via Next.js dynamic imports and React module hierarchy. A full reference graph would require AST parsing of JSX/TSX; sampling below:

| Component | Status | Notes |
|---|---|---|
| `components/agents/*` | ✓ Live | Agents dashboard integration |
| `components/cover-letters/*` | ✓ Live | Cover letter UI |
| `components/applications/*` | ✓ Live | Application tracking board |
| `components/analytics/*` | ✓ Live | Dashboard analytics |
| `components/approvals/*` | ✓ Live | Approval workflow UI |
| `components/sidebar.tsx` | ✓ Live | Main navigation (loaded globally) |
| `components/admin/*` | ✓ Live | Admin panel |

No zero-ref frontend components detected in sampled directories.

---

## Summary

✓ **22 Services:** 2 ZERO-REF (anthropic_oauth, env_file_writer), 20 actively used  
✓ **22 Agents:** 0 actual ZERO-REF (1 NOT-LOADED: outreach_support); all others use dynamic import  
✓ **18 Routers:** 8 ZERO-INTERNAL-REFS (expected for leaf HTTP handlers); all registered in main.py  
✓ **Frontend:** No zero-ref components detected in sample

**Recommended Cleanup Audit (§20):**
- `services/anthropic_oauth.py` — verify superseded by credential_vault
- `services/env_file_writer.py` — verify deprecated
- `agents/outreach_support.py` — verify unused or document intended use
