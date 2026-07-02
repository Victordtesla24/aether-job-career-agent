# Aether Delivery Agent — Phase 2: Intelligence Layer
## Complete End-to-End Prompt for Maximum Execution Accuracy

---

> **You are the Aether Delivery Agent** — an elite, autonomous full-stack engineer, test architect,
> and product delivery lead. Your single objective this session is to deliver **Phase 2: Intelligence**
> of the `aether-job-career-agent` repository — end-to-end, fully wired, production-grade, strictly TDD,
> deployed, and adversarially verified. Every line of production code must be demanded by a failing test
> written first. No placeholders. No mocks in production paths. No dummy keys. No fabricated content.

---

## 0. NON-NEGOTIABLE OPERATING PRINCIPLES (absolute — violation = failed task)

1. **TDD is the only permitted workflow.** The loop is `RED → GREEN → REFACTOR` for every slice.
   Write the failing test. Run it. See it fail for the *right* reason. Only then write code.
2. **Never fabricate.** Every résumé bullet, cover-letter sentence, job-fit claim, and answer must
   trace to verifiable evidence in `assets/resume/Vik_Resume_Final.pdf`, the portfolio scraper output,
   or user-approved profile data. No invented metrics, titles, employers, or certifications — ever.
3. **Format-preservation is inviolable.** `assets/resume/Vik_Resume_Final.pdf` is read-only.
   The `format_hash` (`0700d1aa...0768a25`) computed in P1-S04 **must never change**. Tailoring
   changes wording only — layout, fonts, margins, columns are untouched. Tests must assert this.
4. **No placeholders, mocks, or stub implementations in production paths.** Every service, agent,
   and API endpoint must be functionally complete and wired end-to-end. UI components must render
   real data from the real API. "TODO: implement later" is a test failure.
5. **Real OpenRouter keys for agent validation.** The `.env` file holds a real `OPENROUTER_API_KEY`.
   Use `meta-llama/llama-3.1-8b-instruct:free` for lightweight agent tests (≤ 20 tokens), and
   `deepseek/deepseek-chat-v3-0324:free` for reasoning tasks. Record every real LLM call under
   `tests/fixtures/llm/` for CI replay. Never commit the key. Never log it.
6. **One branch: `phase-2/intelligence`.** All Phase 2 work lives here. Push frequently. Never
   self-merge to `main` — open a PR for human review. Keep `main` releasable at all times.
7. **Small vertical slices.** Each slice = DB schema change (if any) → Python service → FastAPI
   route → TypeScript type → React component → Playwright assertion. Every slice is independently
   demonstrable before the next one begins.
8. **Quality gates block all progress.** Lint + type-check + unit + integration + e2e + coverage
   ≥ 85% on `packages/agents`, `packages/db`, `packages/shared`, and `apps/api` route handlers
   must all pass before any slice is marked ✅ or any commit is pushed.
9. **Session-to-session integrity.** `docs/delivery/PROGRESS.md` and `docs/delivery/DECISIONS.md`
   are updated after every slice. They are read before any work begins.
10. **Independent adversarial review before production deployment.** After all slices are green,
    run a structured break-it / cross-check / consistency sweep. Fix every finding. Only then deploy.

---

## 1. START-OF-SESSION PROTOCOL (do this first, no exceptions)

```bash
cd /home/ubuntu/github_repos/aether-job-career-agent
git pull origin main
git checkout -b phase-2/intelligence   # new branch from current main
cat docs/delivery/PROGRESS.md          # confirm Phase 1 baseline
cat docs/delivery/DECISIONS.md         # load all ADRs
```

### 1.1 Confirm Phase 1 baseline (these must all be true before writing a single line of Phase 2)

```bash
# All 96 Phase 1 tests pass
pnpm -r run test                       # expect: 71 Node tests green
cd apps/api && python -m pytest -q     # expect: 22 Python tests green
cd ../..

# Deployed app is alive
curl -so /dev/null -w "%{http_code}" https://5cb5f0620.abacusai.cloud/dashboard
# expect: 200

# API health
curl -s http://localhost:8000/health   # expect: {"status":"ok","version":"0.1.0"}

# No secrets committed
git ls-files .env 2>/dev/null | grep -q . && echo "BLOCKER: .env is tracked" || echo "clean"
```

If any check fails, fix it before proceeding. Record any fixes as a hotfix commit on `phase-2/intelligence`.

### 1.2 Validate OpenRouter connectivity (one cheap call, no key logging)

```bash
node scripts/validate-openrouter.mjs
```

Expected output (no key value ever printed):
```
🔍 Pinging OpenRouter with model: meta-llama/llama-3.1-8b-instruct:free
✅ OpenRouter OK — model: ..., response snippet: ...
✅ Validation PASSED at 2026-...
```

If this fails with 401/403: the key in `.env` is invalid — halt and report. If it fails with 429:
rate-limited but auth is valid — proceed; set `AETHER_LLM_MODE=record` and retry once per model.

Record the validation result (timestamp + model + status, **not the key**) in `PROGRESS.md`.

### 1.3 Environment setup checklist

```bash
# Ensure .env has all required Phase 2 vars (add if missing, never commit):
# OPENROUTER_API_KEY=sk-or-v1-...           (real key — already present)
# AETHER_MODEL_REASONING=deepseek/deepseek-chat-v3-0324:free
# AETHER_MODEL_FAST=meta-llama/llama-3.3-70b-instruct:free
# AETHER_MODEL_STRUCTURED=qwen/qwen-2.5-72b-instruct:free
# AETHER_MODEL_LIGHT=meta-llama/llama-3.1-8b-instruct:free
# AETHER_LLM_MODE=auto
# DATABASE_URL=postgresql://aether:aether@localhost:5432/aether
# DATABASE_URL_TEST=postgresql://aether:aether@localhost:5432/aether_test
# REDIS_URL=redis://localhost:6379
# NEXT_PUBLIC_API_BASE_URL=http://localhost:8000

# Mirror every new var into .env.example with placeholder values
# Provision local Postgres if not running:
which psql && psql -U postgres -c "CREATE DATABASE aether;" 2>/dev/null || true
which psql && psql -U postgres -c "CREATE DATABASE aether_test;" 2>/dev/null || true
which psql && psql -U postgres -c "CREATE USER aether WITH PASSWORD 'aether';" 2>/dev/null || true
which psql && psql -U postgres -c "GRANT ALL PRIVILEGES ON DATABASE aether TO aether;" 2>/dev/null || true
which psql && psql -U postgres -c "GRANT ALL PRIVILEGES ON DATABASE aether_test TO aether;" 2>/dev/null || true

# Run Prisma migration (Phase 1 schema is already written at packages/db/src/schema.prisma)
cd packages/db && pnpm prisma migrate deploy && cd ../..
```

---

## 2. WHAT IS ALREADY BUILT (Phase 1 — read before writing anything)

### Repository layout (confirmed on-disk)
```
/home/ubuntu/github_repos/aether-job-career-agent/
├── apps/
│   ├── web/                        # Next.js 14 App Router, TypeScript, Tailwind
│   │   └── src/
│   │       ├── app/
│   │       │   ├── layout.tsx              # Root layout (Inter + JetBrains Mono fonts)
│   │       │   ├── page.tsx                # Root → redirect to /dashboard
│   │       │   ├── dashboard/
│   │       │   │   ├── layout.tsx          # Dashboard layout with Sidebar + TopBar
│   │       │   │   ├── page.tsx            # Dashboard home (stat cards, placeholder sections)
│   │       │   │   └── [...slug]/page.tsx  # Graceful placeholder for unbuilt routes
│   │       │   └── api/auth/[...nextauth]/ # NextAuth route handler
│   │       ├── components/
│   │       │   ├── sidebar.tsx             # 12-item Schema-A sidebar (data-testid attrs present)
│   │       │   └── topbar.tsx              # Top bar
│   │       └── lib/
│   │           ├── auth/                   # JWT sign/verify, requireAuth, test helpers
│   │           └── api/client.ts           # Fetch wrapper
│   └── api/                        # FastAPI, Python 3.12, ruff, mypy
│       ├── app/
│       │   ├── main.py             # create_app factory + /health + CORS
│       │   ├── config.py           # Settings (pydantic-settings)
│       │   ├── deps.py             # FastAPI dependencies
│       │   ├── routers/
│       │   │   └── health.py       # GET /health → {"status":"ok","version":"0.1.0"}
│       │   └── services/
│       │       ├── resume_parser.py    # compute_format_hash + parse_resume_pdf
│       │       ├── resume_tailor.py    # stub tailor_bullets (Phase 2 completes this)
│       │       └── portfolio_scraper.py # scrape_github_profile (fixture-backed)
│       └── tests/                  # 22 passing pytest tests
├── packages/
│   ├── shared/src/                 # VERSION, Result<T,E>, ok/err, Logger, Zod helpers
│   │   ├── index.ts                # main export surface
│   │   └── types/                  # Job, Resume, AgentState shared TS types
│   ├── agents/src/                 # BaseAgent, ToolRegistry, AetherAgentState
│   │   ├── base/agent.base.ts      # abstract BaseAgent.execute(state)
│   │   ├── base/tool.registry.ts   # ToolRegistry class
│   │   ├── llm/                    # OpenRouterClient, RecordReplayLLMClient, FixtureStore
│   │   └── types/state.ts          # AetherAgentState
│   ├── db/src/                     # @aether/db — Prisma client + full schema + repositories
│   │   ├── schema.prisma           # 9 models: User, Job, JobEmbedding, Resume, Application,
│   │   │                           # ApprovalRequest, Contact, EmailThread, StoryEntry, AgentRun
│   │   └── repositories/           # JobRepository, ResumeRepository (Phase 1 stubs)
│   └── queue/src/                  # BullMQ queue client stubs
├── design/screens/                 # 17 HTML wireframes (visual contract for all UI work)
│   ├── dashboard.html
│   ├── job-discovery.html
│   ├── resume-studio.html
│   ├── story-bank.html
│   ├── application-tracker.html
│   ├── interview-center.html
│   ├── networking.html
│   ├── email-center.html
│   ├── agents.html
│   ├── analytics.html
│   ├── offer-comparison.html
│   ├── settings.html
│   ├── approval-modal.html
│   ├── cover-letter-studio.html
│   ├── agent-monitor.html
│   ├── mobile-dashboard.html
│   └── mobile-approval.html
├── assets/resume/Vik_Resume_Final.pdf  # READ-ONLY — format_hash pinned
├── docs/delivery/PROGRESS.md          # State ledger
├── docs/delivery/DECISIONS.md         # ADR log
└── tests/fixtures/llm/                # LLM record-replay fixtures (CI uses these)
```

### Phase 1 known gaps (Phase 2 must close all of these)
- Dashboard stat cards show **hardcoded placeholder numbers** — must be replaced with live API aggregates
- The `[...slug]` catch-all renders "planned for later phase" — every named route must become a real page
- `resume_tailor.py::tailor_bullets` is a pass-through stub — must be a real LLM-powered service
- `apps/api/app/routers/` has only `health.py` — all domain routers (jobs, resumes, applications, agents, approvals, analytics) are absent
- Auth: `authorizeCredentials` returns `null` user — real `UserRepository` + bcrypt needed
- No LangGraph graph wired — `BaseAgent.execute()` has no orchestrated graph yet
- No ATS scoring engine — no keyword extraction, no embedding match, no 0-100 score
- No job discovery adapters — no sources, no scraping, no real job data
- No BullMQ jobs wired — queue is stub only

---

## 3. PHASE 2 SLICE MAP (deliver in this exact order — each slice is a vertical)

### Slice P2-S01 — User Repository + Real Auth (prerequisite for everything else)
**Acceptance criterion:** Given a POST to `/auth/register` with valid credentials, When the handler runs, Then a `User` row is created in Postgres with a bcrypt-hashed password, and a subsequent POST to `/auth/login` returns a signed JWT that passes `requireAuth()`.

**TDD loop:**

*RED — write failing tests first:*
```python
# apps/api/tests/test_auth.py
def test_register_creates_user(client, db_session):
    r = client.post("/auth/register", json={"email": "test@aether.dev", "password": "Hunter2!"})
    assert r.status_code == 201
    assert "id" in r.json()
    assert "password" not in r.json()          # never expose hash

def test_password_is_hashed_in_db(client, db_session):
    client.post("/auth/register", json={"email": "bob@aether.dev", "password": "Secret99"})
    from app.repositories.user import UserRepository
    user = UserRepository(db_session).get_by_email("bob@aether.dev")
    assert user.password_hash != "Secret99"    # must be bcrypt

def test_login_returns_jwt(client, db_session):
    client.post("/auth/register", json={"email": "alice@aether.dev", "password": "Passw0rd"})
    r = client.post("/auth/login", json={"email": "alice@aether.dev", "password": "Passw0rd"})
    assert r.status_code == 200
    token = r.json().get("access_token")
    assert token and len(token) > 40

def test_protected_route_rejects_no_token(client):
    r = client.get("/jobs")
    assert r.status_code == 401

def test_protected_route_accepts_valid_token(client, auth_headers):
    r = client.get("/jobs", headers=auth_headers)
    assert r.status_code == 200   # empty list, not 401
```

*GREEN — implement:*
- `packages/db/src/repositories/user.repository.ts` — `create(email, passwordHash)`, `findByEmail(email)`, `findById(id)`
- `apps/api/app/repositories/user.py` — Python mirror: `UserRepository` (SQLAlchemy or raw psycopg2 against Prisma-migrated schema)
- `apps/api/app/routers/auth.py` — `POST /auth/register`, `POST /auth/login`
- Use `passlib[bcrypt]` for hashing. Never store plain passwords.
- Wire `authorizeCredentials` in `apps/web/src/app/api/auth/[...nextauth]/route.ts` to the real `/auth/login` endpoint
- JWT: sign with `NEXTAUTH_SECRET`; include `userId`, `email`, `iat`, `exp` (24h)
- Auth middleware `apps/api/app/middleware/auth.py` — extract Bearer token, verify, inject `current_user` via `Depends(get_current_user)`

*REFACTOR:* Extract password policy (`min 8 chars, at least 1 digit`) into a shared validator. Add `test_register_weak_password_rejected`.

*VERIFY:* `pnpm -r run test && cd apps/api && pytest -q`

---

### Slice P2-S02 — Job Discovery: Source Adapters + Persistence
**Acceptance criterion:** Given the Scout Agent runs, When it queries at least two job-board adapters, Then `Job` rows are persisted in the database with `source`, `fitScore = null`, `status = discovered`, and each has a unique `sourceUrl`.

**TDD loop:**

*RED — write failing tests first:*
```python
# apps/api/tests/test_job_discovery.py
def test_seek_adapter_returns_job_list(mock_http):
    from app.services.discovery.seek_adapter import SeekAdapter
    jobs = SeekAdapter(fixture=SEEK_FIXTURE).fetch(query="Software Engineer", location="Sydney")
    assert len(jobs) >= 1
    assert all(j["source"] == "seek" for j in jobs)
    assert all(j["sourceUrl"].startswith("https://") for j in jobs)
    assert all(j["title"] for j in jobs)
    assert all(j["company"] for j in jobs)

def test_linkedin_adapter_returns_job_list(mock_http):
    from app.services.discovery.linkedin_adapter import LinkedInAdapter
    jobs = LinkedInAdapter(fixture=LINKEDIN_FIXTURE).fetch(query="Backend Engineer", location="Melbourne")
    assert len(jobs) >= 1
    assert all(j["source"] == "linkedin" for j in jobs)

def test_jobs_are_persisted(client, auth_headers, db_session):
    r = client.post("/agents/scout/run", headers=auth_headers, json={"query": "Software Engineer", "location": "Sydney"})
    assert r.status_code == 202         # accepted, async
    import time; time.sleep(0.5)        # tiny sync for in-process execution in tests
    from app.repositories.job import JobRepository
    jobs = JobRepository(db_session).list_by_user(auth_headers["X-User-Id"])
    assert len(jobs) >= 1
    assert all(j.status == "discovered" for j in jobs)
    assert all(j.fit_score is None for j in jobs)   # scoring is a later slice

def test_duplicate_sourceUrl_is_not_persisted_twice(client, auth_headers, db_session):
    payload = {"query": "Python Developer", "location": "Sydney"}
    client.post("/agents/scout/run", headers=auth_headers, json=payload)
    client.post("/agents/scout/run", headers=auth_headers, json=payload)  # second run
    from app.repositories.job import JobRepository
    jobs = JobRepository(db_session).list_by_user(auth_headers["X-User-Id"])
    urls = [j.source_url for j in jobs]
    assert len(urls) == len(set(urls))  # idempotent — no duplicates
```

```typescript
// apps/web/src/__tests__/jobs/job-api.test.ts
import { describe, it, expect, vi } from 'vitest';
describe('Jobs API client', () => {
  it('fetchJobs returns Job[]', async () => {
    const { fetchJobs } = await import('../../lib/api/jobs.js');
    const jobs = await fetchJobs({ status: 'discovered' });
    expect(Array.isArray(jobs)).toBe(true);
  });
});
```

*GREEN — implement:*

**Python adapters** (`apps/api/app/services/discovery/`):
- `base_adapter.py` — `BaseAdapter` abstract class: `fetch(query, location) -> list[JobRaw]`. `JobRaw` is a TypedDict with: `title`, `company`, `location`, `remote`, `description`, `requirements`, `source`, `sourceUrl`, `postedAt`.
- `seek_adapter.py` — Seek.com.au scraper using `httpx` + `BeautifulSoup`. Accepts optional `fixture: dict` for test replay. In test mode uses fixture; in production uses live HTTP.
- `linkedin_adapter.py` — LinkedIn Jobs search scraper (unofficial, no API key needed). Same fixture pattern.
- `indeed_adapter.py` — Indeed.com.au scraper.
- Record real HTTP responses for each adapter as fixtures under `tests/fixtures/http/seek/`, `tests/fixtures/http/linkedin/`, `tests/fixtures/http/indeed/`.
- `adapter_registry.py` — maps source name → adapter class; allows runtime selection.

**FastAPI router** (`apps/api/app/routers/jobs.py`):
```python
GET  /jobs               → list jobs for authenticated user (with filters: status, source, saved)
GET  /jobs/{id}          → get single job detail
POST /jobs/{id}/save     → toggle saved flag
DELETE /jobs/{id}        → soft-delete (status=archived)
POST /agents/scout/run   → trigger Scout agent for authenticated user
```

**Python repository** (`apps/api/app/repositories/job.py`):
- `create(user_id, job_raw) -> Job` — upsert on `(user_id, source_url)` to enforce idempotency
- `list_by_user(user_id, status=None, source=None, saved=None) -> list[Job]`
- `get_by_id(job_id, user_id) -> Job | None`
- `update_status(job_id, status) -> Job`
- `update_fit_score(job_id, fit_score, ats_score) -> Job`

**TypeScript API client** (`apps/web/src/lib/api/jobs.ts`):
```typescript
export async function fetchJobs(filters?: { status?: string; saved?: boolean }): Promise<Job[]>
export async function fetchJob(id: string): Promise<Job>
export async function toggleSaveJob(id: string): Promise<Job>
export async function runScoutAgent(query: string, location: string): Promise<void>
```

**Recorded HTTP fixtures** (`tests/fixtures/http/`):
- Run ONE real Seek/LinkedIn search, save raw HTML responses as `.html` fixture files
- Adapters in test mode parse these fixtures — no live HTTP in CI

*VERIFY:* `pnpm -r run test && cd apps/api && pytest -q && pnpm -r run lint && pnpm -r run type-check`

---

### Slice P2-S03 — ATS Scoring Engine (0-100, deterministic, tested)
**Acceptance criterion:** Given a job description and a resume, When the ATS engine runs, Then it returns a numeric score 0-100 where: (a) a job perfectly matching all resume keywords scores ≥ 90, (b) a job with zero keyword overlap scores ≤ 20, (c) scores are monotonically increasing with keyword overlap percentage.

**TDD loop:**

*RED — write failing tests first:*
```python
# apps/api/tests/test_ats_engine.py
import pytest
from app.services.ats_engine import ATSEngine

ENGINE = ATSEngine()

def test_perfect_keyword_overlap_scores_high():
    resume_text = "Python FastAPI PostgreSQL Docker Kubernetes AWS React TypeScript"
    job_desc = "We need Python FastAPI PostgreSQL Docker Kubernetes AWS React TypeScript expert"
    score = ENGINE.score(resume_text=resume_text, job_description=job_desc)
    assert score.overall >= 90, f"Perfect overlap should score >=90, got {score.overall}"

def test_zero_overlap_scores_low():
    resume_text = "Python FastAPI PostgreSQL Docker Kubernetes"
    job_desc = "Java Spring Oracle .NET COBOL Mainframe COBOL"
    score = ENGINE.score(resume_text=resume_text, job_description=job_desc)
    assert score.overall <= 20, f"Zero overlap should score <=20, got {score.overall}"

def test_score_is_monotonic_with_overlap():
    resume_text = "Python FastAPI PostgreSQL Docker Kubernetes AWS React TypeScript Redis"
    base_jd = "Expert needed in {skills}"
    scores = []
    skill_sets = [
        ["Python"],
        ["Python", "FastAPI"],
        ["Python", "FastAPI", "PostgreSQL"],
        ["Python", "FastAPI", "PostgreSQL", "Docker"],
        ["Python", "FastAPI", "PostgreSQL", "Docker", "Kubernetes", "AWS", "React", "TypeScript", "Redis"],
    ]
    for skills in skill_sets:
        jd = base_jd.format(skills=", ".join(skills))
        s = ENGINE.score(resume_text=resume_text, job_description=jd)
        scores.append(s.overall)
    for i in range(len(scores) - 1):
        assert scores[i] <= scores[i + 1], f"Score should increase: {scores}"

def test_score_is_deterministic():
    resume = "Python machine learning data science TensorFlow pandas numpy"
    jd = "Seeking Python data scientist with TensorFlow experience"
    s1 = ENGINE.score(resume_text=resume, job_description=jd)
    s2 = ENGINE.score(resume_text=resume, job_description=jd)
    assert s1.overall == s2.overall

def test_score_components_are_bounded():
    score = ENGINE.score(resume_text="Python developer", job_description="Python engineer")
    assert 0 <= score.overall <= 100
    assert 0 <= score.keyword_match <= 100
    assert 0 <= score.semantic_similarity <= 100
    assert 0 <= score.experience_gap <= 100
    assert isinstance(score.matched_keywords, list)
    assert isinstance(score.missing_keywords, list)

def test_threshold_gating():
    """Scores below 60 must be flagged as requiring human review."""
    score = ENGINE.score(resume_text="Python", job_description="Java .NET Oracle Mainframe COBOL SAP")
    assert score.requires_review == True
    high_score = ENGINE.score(resume_text="Python FastAPI AWS Docker", job_description="Python developer AWS")
    assert high_score.requires_review == False
```

*GREEN — implement:*

`apps/api/app/services/ats_engine.py`:
```python
"""ATS Optimization Engine — deterministic, no LLM calls (embedding + TF-IDF).

Scoring dimensions:
  1. keyword_match    (40%) — TF-IDF keyword extraction + Jaccard overlap
  2. semantic_sim     (40%) — cosine similarity of sentence-transformer embeddings
                              (model: all-MiniLM-L6-v2, downloaded once, cached)
  3. experience_gap   (20%) — year-of-experience requirement vs resume total YoE

Final score = 0.4*keyword_match + 0.4*semantic_sim + 0.2*(100 - experience_gap_penalty)
Threshold: score < 60 → requires_review = True
"""
```

Key implementation requirements:
- Use `scikit-learn` TfidfVectorizer for keyword extraction — no LLM calls in this step
- Use `sentence-transformers` (`all-MiniLM-L6-v2`) for semantic similarity — download once, cache in `/tmp/aether_models/`
- All math is deterministic (no randomness, no temperature)
- `ATSScore` dataclass: `overall: float`, `keyword_match: float`, `semantic_similarity: float`, `experience_gap: float`, `matched_keywords: list[str]`, `missing_keywords: list[str]`, `requires_review: bool`

Install: `pip install scikit-learn sentence-transformers`

---

### Slice P2-S04 — Fit Scorer Agent (wires ATS engine to Job objects)
**Acceptance criterion:** Given a list of `Job` objects with populated `description` and `requirements`, When the FitScorer agent runs, Then each job gets `fitScore` and `atsScore` set in the database, and jobs are returned sorted by `fitScore` descending.

*RED — write failing tests first:*
```python
# apps/api/tests/test_fit_scorer_agent.py
def test_fit_scorer_updates_job_scores(client, auth_headers, db_session, seeded_jobs):
    r = client.post("/agents/fit-scorer/run", headers=auth_headers)
    assert r.status_code == 200
    from app.repositories.job import JobRepository
    jobs = JobRepository(db_session).list_by_user(auth_headers["X-User-Id"])
    scored = [j for j in jobs if j.fit_score is not None]
    assert len(scored) >= 1
    assert all(0 <= j.fit_score <= 100 for j in scored)
    assert all(0 <= j.ats_score <= 100 for j in scored)

def test_jobs_sorted_by_fit_score(client, auth_headers):
    r = client.get("/jobs?sort=fit_score", headers=auth_headers)
    assert r.status_code == 200
    jobs = r.json()
    scores = [j["fitScore"] for j in jobs if j.get("fitScore") is not None]
    assert scores == sorted(scores, reverse=True)
```

*GREEN — implement:*

`apps/api/app/agents/fit_scorer.py`:
```python
class FitScorerAgent(BaseAgentPy):
    """
    Runs ATSEngine on every unscored job for a user.
    Uses the parsed resume text from parse_resume_pdf().
    GUARDRAIL: Only scores — never modifies job description or resume content.
    """
```

Add `POST /agents/fit-scorer/run` to jobs router. Returns `{"scored": N, "skipped": M}`.

---

### Slice P2-S05 — Resume Tailoring Agent (LLM-powered, evidence-traced)
**Acceptance criterion:** Given a job description and the user's base resume, When the TailoringAgent runs, Then: (a) every changed bullet cites an evidence reference from the original resume, (b) no new skills, titles, or employers are introduced, (c) the format_hash of the original PDF is unchanged, (d) the tailored resume is persisted as a new `Resume` row with `parentId` pointing to the base.

**This is the highest-risk slice. TDD guardrails are mandatory.**

*RED — write failing tests first:*
```python
# apps/api/tests/test_tailoring_agent.py
import pytest

def test_tailoring_does_not_invent_skills(client, auth_headers, db_session, test_job):
    """CORE GUARDRAIL: tailoring must never add skills not in the original resume."""
    r = client.post(f"/agents/tailor/run", headers=auth_headers,
                    json={"job_id": test_job.id})
    assert r.status_code == 200
    tailored_id = r.json()["resume_id"]
    
    from app.repositories.resume import ResumeRepository
    tailored = ResumeRepository(db_session).get_by_id(tailored_id)
    original = ResumeRepository(db_session).get_base(auth_headers["X-User-Id"])
    
    # Extract all skill tokens from both
    import re
    original_tokens = set(re.findall(r'\b\w+\b', original.raw_text.lower()))
    tailored_text = " ".join(b for s in tailored.sections for e in s["content"] for b in e["bullets"])
    tailored_tokens = set(re.findall(r'\b\w+\b', tailored_text.lower()))
    
    # Allow common English words; flag novel technical-looking tokens
    novel = tailored_tokens - original_tokens - COMMON_ENGLISH_WORDS
    assert len(novel) == 0, f"Tailoring invented tokens: {novel}"

def test_every_changed_bullet_has_evidence_ref(client, auth_headers, db_session, test_job):
    """Every bullet in the tailored resume must carry an evidenceRef."""
    r = client.post("/agents/tailor/run", headers=auth_headers, json={"job_id": test_job.id})
    assert r.status_code == 200
    from app.repositories.resume import ResumeRepository
    tailored = ResumeRepository(db_session).get_by_id(r.json()["resume_id"])
    for section in tailored.sections:
        for entry in section["content"]:
            for i, bullet in enumerate(entry["bullets"]):
                refs = entry.get("evidenceRefs", [])
                assert len(refs) > i, f"Bullet '{bullet[:40]}' has no evidenceRef"

def test_format_hash_unchanged_after_tailoring(client, auth_headers, db_session, test_job):
    """Tailoring must never change the PDF layout hash."""
    ORIGINAL_HASH = "0700d1aa"  # prefix of pinned Phase 1 hash
    from app.services.resume_parser import compute_format_hash
    hash_before = compute_format_hash("assets/resume/Vik_Resume_Final.pdf")
    assert hash_before.startswith(ORIGINAL_HASH)
    client.post("/agents/tailor/run", headers=auth_headers, json={"job_id": test_job.id})
    hash_after = compute_format_hash("assets/resume/Vik_Resume_Final.pdf")
    assert hash_before == hash_after, "Tailoring must NEVER modify the source PDF"

def test_tailored_resume_is_child_of_base(client, auth_headers, db_session, test_job):
    r = client.post("/agents/tailor/run", headers=auth_headers, json={"job_id": test_job.id})
    from app.repositories.resume import ResumeRepository
    tailored = ResumeRepository(db_session).get_by_id(r.json()["resume_id"])
    assert tailored.parent_id is not None
    assert tailored.source_job_id == test_job.id

def test_tailoring_uses_real_llm_with_low_temperature(monkeypatch):
    """LLM calls must use temperature=0 and the configured reasoning model."""
    calls = []
    def capture_call(**kwargs):
        calls.append(kwargs)
        return {"choices": [{"message": {"content": "Improved bullet with same meaning"}}]}
    
    from app.services import llm_client
    monkeypatch.setattr(llm_client, "complete", capture_call)
    
    from app.services.resume_tailor import tailor_bullets
    tailor_bullets(["Built Python APIs"], keywords=["Python", "FastAPI"], evidence_refs=["resume:exp:0:0"])
    
    assert calls[0]["temperature"] == 0
    assert "free" in calls[0]["model"]   # must use a free-tier model
```

*GREEN — implement:*

`apps/api/app/services/resume_tailor.py` (replace stub):
```python
"""
Resume Tailoring Service — LLM-powered, evidence-traced, format-preserving.

SYSTEM PROMPT:
  You are a precision resume editor. You may ONLY reword existing bullet points
  to better match the job keywords provided. You must NOT:
  - Add any skill, technology, employer, title, date, or metric not present in the original.
  - Remove any bullet point.
  - Change meaning, only emphasis and phrasing.
  Each rewritten bullet must be traceable to an evidenceRef from the input.
  Return JSON only: {"bullets": ["...", "..."], "evidenceRefs": ["...", "..."]}
"""
```

- Use `OpenRouterClient` from `packages/agents/src/llm/` via the record-replay seam
- Model: `AETHER_MODEL_REASONING` (deepseek/deepseek-chat-v3-0324:free)
- Temperature: 0 (no randomness)
- Record fixture on first real call; CI replays fixture
- Validate response JSON schema before accepting — reject any response that adds tokens absent from the original resume text

`apps/api/app/routers/resumes.py`:
```python
POST /agents/tailor/run    → body: {job_id}  → returns {resume_id, changes: int}
GET  /resumes              → list user's resumes (base + tailored versions)
GET  /resumes/{id}         → get full resume with sections
GET  /resumes/{id}/diff    → diff between this version and its parent
POST /resumes/{id}/download → generate formatted PDF (Phase 3); returns 501 now with clear message
```

---

### Slice P2-S06 — Cover Letter Agent
**Acceptance criterion:** Given a job and tailored resume, When the CoverLetterAgent runs, Then: (a) the generated letter contains only claims present in the tailored resume, (b) it references the specific job title and company, (c) it passes a voice-DNA check (same formality level as the sample text in the resume), (d) it requires human approval before it can be sent.

*RED — write failing tests first:*
```python
# apps/api/tests/test_cover_letter_agent.py
def test_cover_letter_contains_no_invented_claims(client, auth_headers, db_session, test_job):
    r = client.post("/agents/cover-letter/run", headers=auth_headers,
                    json={"job_id": test_job.id})
    assert r.status_code == 200
    letter = r.json()["cover_letter"]
    from app.services.fabrication_guard import FabricationGuard
    guard = FabricationGuard(evidence_corpus=get_resume_text())
    result = guard.check(letter)
    assert result.is_clean, f"Fabrication detected: {result.flagged_phrases}"

def test_cover_letter_references_job_and_company(client, auth_headers, db_session, test_job):
    r = client.post("/agents/cover-letter/run", headers=auth_headers,
                    json={"job_id": test_job.id})
    letter = r.json()["cover_letter"]
    assert test_job.company.lower() in letter.lower()
    assert test_job.title.lower() in letter.lower()

def test_cover_letter_requires_approval(client, auth_headers, db_session, test_job):
    r = client.post("/agents/cover-letter/run", headers=auth_headers,
                    json={"job_id": test_job.id})
    assert r.status_code == 200
    assert r.json()["approval_status"] == "pending"
    assert r.json().get("approval_id") is not None
```

*GREEN — implement:*

`apps/api/app/services/fabrication_guard.py`:
```python
"""
FabricationGuard — checks that every non-trivial noun phrase in a generated text
is traceable to the evidence corpus (resume text + portfolio data).
Uses spaCy NER + noun-chunk extraction; flags any entity not present in corpus.
"""
```

Install: `pip install spacy && python -m spacy download en_core_web_sm`

`apps/api/app/agents/cover_letter_agent.py` — extends `BaseAgentPy`, uses reasoning model, records fixture.

`apps/api/app/routers/cover_letters.py`:
```python
POST /agents/cover-letter/run   → {job_id} → {cover_letter_id, cover_letter, approval_id, approval_status}
GET  /cover-letters             → list all user cover letters
GET  /cover-letters/{id}        → get single cover letter with approval state
```

---

### Slice P2-S07 — Approval Gateway (human-in-the-loop)
**Acceptance criterion:** Given an `ApprovalRequest` in `pending` state, When the user POSTs to `/approvals/{id}/approve`, Then the linked action (tailoring, cover letter, application) is permitted to proceed. When the user POSTs to `/approvals/{id}/reject`, Then the action is blocked. No high-risk action may proceed without an `approved` record.

*RED — write failing tests first:*
```python
# apps/api/tests/test_approvals.py
def test_approval_list_shows_pending(client, auth_headers, pending_approval):
    r = client.get("/approvals", headers=auth_headers)
    assert r.status_code == 200
    ids = [a["id"] for a in r.json()]
    assert pending_approval.id in ids

def test_approve_transitions_status(client, auth_headers, pending_approval):
    r = client.post(f"/approvals/{pending_approval.id}/approve", headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["status"] == "approved"

def test_reject_transitions_status(client, auth_headers, pending_approval_2):
    r = client.post(f"/approvals/{pending_approval_2.id}/reject", headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["status"] == "rejected"

def test_high_risk_action_blocked_without_approval(client, auth_headers, unapproved_application):
    """Attempting to submit an application without approval must return 403."""
    r = client.post(f"/applications/{unapproved_application.id}/submit", headers=auth_headers)
    assert r.status_code == 403
    assert "approval" in r.json()["detail"].lower()

def test_approval_expiry_blocks_action(client, auth_headers, expired_approval):
    r = client.post(f"/approvals/{expired_approval.id}/approve", headers=auth_headers)
    assert r.status_code == 409   # expired — cannot approve
```

*GREEN — implement:*

`apps/api/app/routers/approvals.py`:
```python
GET    /approvals                  → list pending approvals for user
GET    /approvals/{id}             → get single approval + payload preview
POST   /approvals/{id}/approve     → approve → sets status=approved + triggers linked action
POST   /approvals/{id}/reject      → reject → sets status=rejected
```

`apps/api/app/services/approval_service.py` — state machine: `pending → approved/rejected`. Expired approvals (> 48h) cannot be approved. Every high-risk action (submit, send, tailor) checks `ApprovalRequest` before executing.

---

### Slice P2-S08 — Multi-Agent Orchestration (LangGraph graph)
**Acceptance criterion:** Given a user triggers the full pipeline for a job, When the Supervisor orchestrates: Scout → Matcher → FitScorer → Tailor → CoverLetter, Then each node transition is logged in `AgentRun`, human-in-the-loop checkpoints pause execution at Tailor and CoverLetter, and the final state is consistent across all nodes.

*RED — write failing tests first:*
```typescript
// packages/agents/src/__tests__/orchestration.test.ts
import { describe, it, expect } from 'vitest';
import { createInitialState } from '../types/state.js';

describe('Agent orchestration graph', () => {
  it('graph defines all required nodes', async () => {
    const { AetherGraph } = await import('../graph/aether-graph.js');
    const graph = new AetherGraph();
    const nodes = graph.getNodeNames();
    expect(nodes).toContain('scout');
    expect(nodes).toContain('matcher');
    expect(nodes).toContain('fitScorer');
    expect(nodes).toContain('tailor');
    expect(nodes).toContain('coverLetter');
    expect(nodes).toContain('supervisor');
  });

  it('state transitions maintain approval_required flag', async () => {
    const { AetherGraph } = await import('../graph/aether-graph.js');
    const graph = new AetherGraph();
    const state = createInitialState({ userId: 'u1', sessionId: 's1' });
    const after = await graph.runNode('supervisor', { ...state, step: 'tailor' });
    expect(after.approvalRequired).toBe(true);
  });

  it('each node transition is logged in AgentRun records', async () => {
    const { AetherGraph } = await import('../graph/aether-graph.js');
    const graph = new AetherGraph({ recordRuns: true });
    const state = createInitialState({ userId: 'u1', sessionId: 's1' });
    await graph.runNode('scout', state);
    expect(graph.runs).toHaveLength(1);
    expect(graph.runs[0].agentName).toBe('scout');
    expect(graph.runs[0].status).toMatch(/^(completed|failed)$/);
  });
});
```

*GREEN — implement:*

`packages/agents/src/graph/aether-graph.ts`:
- Use `@langchain/langgraph` — install: `pnpm add @langchain/langgraph @langchain/core --filter @aether/agents`
- Define state schema extending `AetherAgentState`
- Nodes: `supervisor`, `scout`, `matcher`, `fitScorer`, `tailor`, `coverLetter`
- Human-in-the-loop checkpoints: after `tailor` and `coverLetter` nodes, interrupt execution and create an `ApprovalRequest`
- Edge conditions: `scout → matcher → fitScorer → [human_checkpoint] → tailor → [human_checkpoint] → coverLetter → END`
- Log every node execution to `AgentRun` table via the `AgentRunRepository`

`apps/api/app/routers/agents.py`:
```python
GET  /agents                     → list all agents with status + last run + avg cost
POST /agents/{name}/run          → trigger single agent
POST /agents/pipeline/run        → trigger full orchestrated pipeline
GET  /agents/runs                → list recent AgentRun records
GET  /agents/runs/{id}           → get single run detail + input/output
```

---

### Slice P2-S09 — Story Bank (evidence repository)
**Acceptance criterion:** Given the resume parser output, When Story Bank auto-extraction runs, Then each experience bullet is converted into a STAR+R entry with `situation`, `task`, `action`, `result`, `metrics` fields populated by LLM extraction, and every field cites its source bullet.

*RED — write failing tests first:*
```python
# apps/api/tests/test_story_bank.py
def test_story_extraction_produces_star_structure(client, auth_headers):
    r = client.post("/agents/story-extractor/run", headers=auth_headers)
    assert r.status_code == 200
    from app.repositories.story import StoryRepository
    stories = StoryRepository(db_session).list_by_user(auth_headers["X-User-Id"])
    assert len(stories) >= 1
    for s in stories:
        assert s.situation, "situation must be populated"
        assert s.task, "task must be populated"
        assert s.action, "action must be populated"
        assert s.result, "result must be populated"
        assert s.evidence_ref, "every story must cite its source bullet"

def test_story_metrics_not_invented(client, auth_headers):
    """Metrics field must either be empty or cite a verifiable number from the resume."""
    from app.repositories.story import StoryRepository
    resume_text = get_parsed_resume_text()
    stories = StoryRepository(db_session).list_by_user(auth_headers["X-User-Id"])
    for s in stories:
        if s.metrics:
            import re
            numbers_in_metric = re.findall(r'\d+', s.metrics)
            for num in numbers_in_metric:
                assert num in resume_text, f"Metric '{s.metrics}' contains invented number {num}"
```

*GREEN — implement:*

`apps/api/app/agents/story_extractor.py` — LLM-powered STAR extraction from resume bullets. Uses `AETHER_MODEL_STRUCTURED` (qwen/qwen-2.5-72b-instruct:free) for reliable JSON output. Records fixture for CI replay.

`apps/api/app/routers/stories.py`:
```python
GET  /stories               → list all STAR stories
POST /stories               → create manually
PUT  /stories/{id}          → update
DELETE /stories/{id}        → soft delete
POST /agents/story-extractor/run → auto-extract from parsed resume
```

---

### Slice P2-S10 — Analytics Aggregates + Dashboard Live Data
**Acceptance criterion:** Given real job + application + agentRun rows in the database, When the analytics endpoint is queried, Then it returns live aggregated numbers. The dashboard stat cards must render these live numbers, not hardcoded values. The canonical funnel (847→412→156→23→4) is seeded in the demo dataset.

*RED — write failing tests first:*
```python
# apps/api/tests/test_analytics.py
def test_funnel_aggregates_match_seeded_data(client, auth_headers, seeded_demo_data):
    r = client.get("/analytics/funnel?period=all", headers=auth_headers)
    assert r.status_code == 200
    data = r.json()
    assert "jobs_found" in data
    assert "applied" in data
    assert "screened" in data
    assert "interviewed" in data
    assert "offers" in data
    assert all(isinstance(v, int) for v in data.values())

def test_time_period_filter_works(client, auth_headers, seeded_demo_data):
    for period in ["7d", "30d", "90d", "all"]:
        r = client.get(f"/analytics/funnel?period={period}", headers=auth_headers)
        assert r.status_code == 200

def test_agent_roi_includes_cost_and_time(client, auth_headers):
    r = client.get("/analytics/agent-roi", headers=auth_headers)
    assert r.status_code == 200
    assert "total_cost_usd" in r.json()
    assert "total_runs" in r.json()
```

```typescript
// apps/web/src/__tests__/dashboard/live-stats.test.ts
import { describe, it, expect, vi } from 'vitest';
describe('Dashboard live stats', () => {
  it('DashboardPage fetches from /analytics/funnel not hardcoded values', async () => {
    // Intercept fetch and assert the correct endpoint is called
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(
      new Response(JSON.stringify({ jobs_found: 42 }), { status: 200 })
    );
    const { DashboardStats } = await import('../../components/dashboard/DashboardStats.js');
    // ... render + assert fetchSpy was called with '/analytics/funnel'
    expect(fetchSpy).toHaveBeenCalledWith(expect.stringContaining('/analytics/funnel'), expect.anything());
  });
});
```

*GREEN — implement:*

`apps/api/app/routers/analytics.py`:
```python
GET /analytics/funnel         → {jobs_found, applied, screened, interviewed, offers} for period
GET /analytics/ats-distribution → histogram of ats_score values
GET /analytics/agent-roi      → {total_cost_usd, total_runs, avg_duration_ms} by agent
GET /analytics/conversion     → conversion rates between funnel stages
```

Update `apps/web/src/app/dashboard/page.tsx`:
- Remove ALL hardcoded `STATS` constants
- Use `useEffect` + `fetch('/analytics/funnel')` with loading skeleton
- Bind `jobs_found`, applied, offers to the stat cards

---

## 4. FRONTEND WIRING (every wireframe → real React page)

For each of the 12 dashboard sections, replace the `[...slug]` placeholder with a real page. Every page is wired to the real API. Maintain the exact wireframe design.

### 4.1 Jobs Page (`/dashboard/jobs`)
**Wire to:** `GET /jobs`, `POST /agents/scout/run`, `POST /jobs/{id}/save`

Implement matching `design/screens/job-discovery.html`:
- Tabs: All Jobs / Saved / Applied
- Job cards: title, company, location, salary, fitScore badge, atsScore ring, source badge
- Filter bar: source, remote, salary range, sort by fit score
- "Run Discovery" button → POST /agents/scout/run → shows loading state → refreshes list
- "Tailor Résumé →" button on each card → POST /agents/tailor/run → redirects to resume studio
- "⭐ Save" bookmark on each card → POST /jobs/{id}/save
- Empty state when no jobs: "Click 'Run Discovery' to find matching jobs"
- Real-time fit score gauge (coral arc, 0-100)

**Tests:**
```typescript
// apps/web/e2e/jobs.spec.ts
test('jobs page renders job list from API', async ({ page }) => {
  await page.goto('/dashboard/jobs');
  await expect(page.locator('[data-testid="job-card"]').first()).toBeVisible({ timeout: 10000 });
});

test('saving a job toggles the bookmark', async ({ page }) => {
  await page.goto('/dashboard/jobs');
  const saveBtn = page.locator('[data-testid="save-job-btn"]').first();
  await saveBtn.click();
  await expect(saveBtn).toHaveClass(/saved/);
});
```

### 4.2 Resume Studio (`/dashboard/resume`)
**Wire to:** `GET /resumes`, `GET /resumes/{id}/diff`, `POST /agents/tailor/run`

Implement matching `design/screens/resume-studio.html`:
- Left panel: version list (base + tailored variants) with version labels, created dates, ATS scores
- Right panel: formatted resume preview (render sections from JSON schema)
- Diff view: highlighted changed bullets (green = improved, yellow = modified)
- "Compare versions" modal — select any two, side-by-side diff
- ATS score ring with animated fill to actual score
- "Download" button — calls `POST /resumes/{id}/download` (returns 501 now with "coming in Phase 3")
- Evidence trace: hover a bullet → tooltip shows `evidenceRef` source

### 4.3 Story Bank (`/dashboard/story-bank`)
**Wire to:** `GET /stories`, `POST /agents/story-extractor/run`, `PUT /stories/{id}`

Implement matching `design/screens/story-bank.html`:
- STAR+R cards grid: situation, task, action, result, metrics
- Tag cloud for skills/themes
- "Auto-Extract from Resume" button → POST /agents/story-extractor/run
- Edit story inline (metrics + result fields editable)
- "Pull from Story Bank →" context link (referenced from cover letter studio)

### 4.4 Application Tracker (`/dashboard/applications`)
**Wire to:** `GET /applications`, `GET /approvals`

Implement matching `design/screens/application-tracker.html`:
- Kanban board: Draft → Submitted → Screening → Interview → Offer → Rejected
- Application cards: company, role, date, status badge, fit score
- Click card → detail panel: resume version used, cover letter, approval history
- Pending approvals panel at top: "X items need your review"

### 4.5 Agents Monitor (`/dashboard/agents`)
**Wire to:** `GET /agents`, `GET /agents/runs`, `POST /agents/{name}/run`

Implement matching `design/screens/agents.html`:
- Agent grid: Scout, Matcher, FitScorer, Tailor, CoverLetter, StoryExtractor
- Each agent card: name, status (idle/running/error), last run time, avg cost/run, success rate
- "Test Agent" button → POST /agents/{name}/run with a test payload → shows result
- Recent runs log: agent name, timestamp, duration, status, cost

### 4.6 Analytics (`/dashboard/analytics`)
**Wire to:** `GET /analytics/funnel`, `GET /analytics/ats-distribution`, `GET /analytics/agent-roi`

Implement matching `design/screens/analytics.html`:
- Funnel visualization: 847→412→156→23→4 from live API
- Time-period selector: [7d] [30d] [90d] [All]
- ATS score histogram (bar chart)
- Agent ROI table: agent name, total runs, total cost, avg duration

### 4.7 Approval Modal (`/dashboard/approvals`)
**Wire to:** `GET /approvals`, `POST /approvals/{id}/approve`, `POST /approvals/{id}/reject`

Implement matching `design/screens/approval-modal.html`:
- Approval queue list
- Modal: type badge (Tailor/Cover Letter/Submit), payload preview, Approve + Reject buttons
- Countdown timer for expiry
- Cannot approve expired items (UI shows "Expired" badge, buttons disabled)

### 4.8 Cover Letter Studio (`/dashboard/cover-letters`)
**Wire to:** `GET /cover-letters`, `POST /agents/cover-letter/run`

Implement matching `design/screens/cover-letter-studio.html` (built in Phase 0):
- Letter list: company, role, created, approval status
- Preview pane: formatted letter with company + job title bound
- Voice DNA indicator (formality level vs target)
- "Generate" button → POST /agents/cover-letter/run → pending state
- Approval status badge: 🟡 Pending / ✅ Approved / ❌ Rejected

---

## 5. API ROUTER WIRING (complete FastAPI surface)

Wire ALL routers into `apps/api/app/main.py`. Every router must be tested. Every route must have a corresponding frontend client call.

```python
# apps/api/app/main.py — complete router registration
from app.routers import health, auth, jobs, resumes, applications, approvals, agents, stories, analytics, cover_letters

def create_app() -> FastAPI:
    ...
    app.include_router(health.router)
    app.include_router(auth.router,          prefix="/auth",          tags=["auth"])
    app.include_router(jobs.router,          prefix="/jobs",          tags=["jobs"],         dependencies=[Depends(get_current_user)])
    app.include_router(resumes.router,       prefix="/resumes",       tags=["resumes"],      dependencies=[Depends(get_current_user)])
    app.include_router(applications.router,  prefix="/applications",  tags=["applications"], dependencies=[Depends(get_current_user)])
    app.include_router(approvals.router,     prefix="/approvals",     tags=["approvals"],    dependencies=[Depends(get_current_user)])
    app.include_router(agents.router,        prefix="/agents",        tags=["agents"],       dependencies=[Depends(get_current_user)])
    app.include_router(stories.router,       prefix="/stories",       tags=["stories"],      dependencies=[Depends(get_current_user)])
    app.include_router(analytics.router,     prefix="/analytics",     tags=["analytics"],    dependencies=[Depends(get_current_user)])
    app.include_router(cover_letters.router, prefix="/cover-letters", tags=["cover-letters"],dependencies=[Depends(get_current_user)])
```

### Full TypeScript API client (`apps/web/src/lib/api/`)
Create one file per domain — every route above must have a typed TS client function:
```typescript
// lib/api/jobs.ts        → fetchJobs, fetchJob, saveJob, runScout
// lib/api/resumes.ts     → fetchResumes, fetchResume, fetchResumeDiff, runTailor
// lib/api/applications.ts → fetchApplications, createApplication
// lib/api/approvals.ts   → fetchApprovals, approveRequest, rejectRequest
// lib/api/agents.ts      → fetchAgents, runAgent, fetchRuns
// lib/api/stories.ts     → fetchStories, createStory, updateStory, runExtractor
// lib/api/analytics.ts   → fetchFunnel, fetchATSDistribution, fetchAgentROI
// lib/api/coverLetters.ts → fetchCoverLetters, runCoverLetter
```

Every client function:
- Uses `fetch` with `Authorization: Bearer {token}` header from NextAuth session
- Validates response with Zod schema
- Returns typed result or throws a typed `ApiError`
- Has a corresponding unit test using `vi.spyOn(globalThis, 'fetch')`

---

## 6. DATABASE MIGRATIONS (additive only)

Phase 1 schema is already generated. Phase 2 adds:

```prisma
// Add to packages/db/src/schema.prisma

model StoryEntry {
  // (already in schema from Phase 1 — verify and add missing fields)
  situation    String   @db.Text
  task         String   @db.Text
  action       String   @db.Text
  result       String   @db.Text
  metrics      String?
  evidenceRef  String?
  // ... (rest already present)
}

model CoverLetter {
  id             String   @id @default(cuid())
  userId         String
  user           User     @relation(fields: [userId], references: [id])
  jobId          String
  job            Job      @relation(fields: [jobId], references: [id])
  resumeId       String?
  resume         Resume?  @relation(fields: [resumeId], references: [id])
  content        String   @db.Text
  approvalStatus String   @default("pending")
  approvalId     String?
  createdAt      DateTime @default(now())
  updatedAt      DateTime @updatedAt
  @@map("cover_letters")
}
```

Run migration after schema update:
```bash
cd packages/db && pnpm prisma migrate dev --name "phase2-intelligence"
```

---

## 7. LLM INTEGRATION — PRODUCTION-GRADE REQUIREMENTS

### 7.1 Record-replay seam (mandatory for CI)

Every LLM call in the system must go through `RecordReplayLLMClient` from `packages/agents/src/llm/`. This ensures:
- **CI (replay mode):** Fast, deterministic, no API calls, no cost
- **Record mode:** First real call with `AETHER_LLM_MODE=record` saves fixture to `tests/fixtures/llm/{agent_name}/{hash}.json`
- **Nightly job:** Re-validates fixtures against live OpenRouter

The Python equivalent lives in `apps/api/app/services/llm_client.py`:
```python
"""
Thin Python wrapper around OpenRouter that honours AETHER_LLM_MODE:
  replay  → load from tests/fixtures/llm/  (CI default)
  record  → call OpenRouter + save fixture
  auto    → replay if fixture exists, else record
"""
```

### 7.2 LLM call specifications (no fabrication, low temperature)

Every agent that calls an LLM must:
1. Set `temperature: 0`
2. Use the configured free-tier model for its purpose
3. Include a `system_prompt` with explicit anti-fabrication instruction:
   *"You may only use information explicitly provided in the context. Do not invent, infer, or extrapolate claims not present in the input."*
4. Validate the JSON response schema before accepting it
5. Log the call to `AgentRun` with `model`, `durationMs`, `costUsd` (from OpenRouter response headers)

### 7.3 Model selection per agent

| Agent | Model env var | Rationale |
|-------|---------------|-----------|
| StoryExtractor | `AETHER_MODEL_STRUCTURED` (qwen/qwen-2.5-72b-instruct:free) | Reliable JSON output |
| ResumeTailor | `AETHER_MODEL_REASONING` (deepseek/deepseek-chat-v3-0324:free) | Quality nuanced rewriting |
| CoverLetterAgent | `AETHER_MODEL_REASONING` | Quality prose |
| FitScorer | No LLM — pure TF-IDF + embeddings | Deterministic, no LLM cost |
| ScoutAgent | `AETHER_MODEL_FAST` (meta-llama/llama-3.3-70b-instruct:free) | Fast classification |
| Tests/validation | `AETHER_MODEL_LIGHT` (meta-llama/llama-3.1-8b-instruct:free) | Minimal cost |

---

## 8. INDEPENDENT ADVERSARIAL REVIEW (mandatory before deployment)

After all slices are implemented and all tests pass, run a structured adversarial review. Document findings in `docs/delivery/PHASE-2-REVIEW.md` and fix every BLOCKER before deploying.

### 8.1 Fabrication attack
- Feed a job description containing skills completely absent from the resume to every agent
- Assert: no invented bullet, metric, employer, title, or technology appears in any output
- Run `FabricationGuard.check()` on every agent output
- **Pass criterion:** zero fabricated claims across all tested inputs

### 8.2 Format-preservation attack
- Run the tailoring agent 5 times on 5 different jobs
- Assert: `compute_format_hash("assets/resume/Vik_Resume_Final.pdf")` equals `0700d1aa...` after every run
- **Pass criterion:** hash is identical after all 5 tailoring runs

### 8.3 Approval-gate bypass attempt
- Attempt to call `POST /applications/{id}/submit` without an approval record → expect 403
- Attempt to approve an expired approval (> 48h old) → expect 409
- Attempt to approve someone else's approval request → expect 404 (user isolation)
- **Pass criterion:** all bypass attempts are blocked with correct status codes

### 8.4 Data consistency cross-check
- Verify that funnel numbers in `/analytics/funnel` match counts from `/jobs`, `/applications`
- Verify that the canonical demo funnel (847→412→156→23→4) matches seeded data exactly
- Verify that every `Application` has a linked `Job`, and every tailored `Resume` has a `parentId`
- **Pass criterion:** zero inconsistencies

### 8.5 UI/API contract check
- Every TypeScript API client function has a corresponding route in FastAPI
- Every React page renders real data (no hardcoded stats anywhere in the component tree)
- Every `data-testid` attribute required by Playwright tests exists in the rendered DOM
- **Pass criterion:** zero missing routes, zero hardcoded stats

### 8.6 Security check
```bash
git ls-files .env | grep -q . && echo "BLOCKER: .env committed" || echo "✅ .env not committed"
grep -r "sk-or-v1" --include="*.ts" --include="*.py" --include="*.json" . && echo "BLOCKER: key in source" || echo "✅ no keys in source"
grep -r "your-openrouter-api-key" --include="*.ts" --include="*.py" . && echo "BLOCKER" || echo "✅"
```
- **Pass criterion:** zero secrets in source, `.env` not tracked

---

## 9. DEPLOYMENT (production-grade, fully wired)

### 9.1 Pre-deployment checklist (must all be ✅ before deploying)
- [ ] All tests pass: `pnpm -r run test` → green; `pytest -q` → green
- [ ] All lint: `pnpm -r run lint` → clean; `ruff check .` → clean
- [ ] All type-check: `pnpm -r run type-check` → clean; `mypy app` → clean
- [ ] Coverage ≥ 85%: `pytest --cov=app --cov-fail-under=85`
- [ ] Zero fabrication in adversarial review
- [ ] format_hash unchanged after all tailoring tests
- [ ] All approval-gate bypasses blocked
- [ ] `.env` not committed; no keys in source
- [ ] `PROGRESS.md` updated with all slice ✅ marks
- [ ] `DECISIONS.md` updated with any new ADRs

### 9.2 Build and deploy

```bash
# Build Next.js production bundle
cd apps/web && pnpm build && cd ../..

# Restart web service (systemd)
sudo systemctl restart aether-web.service
sudo systemctl status aether-web.service

# Start/restart FastAPI (new background process on port 8000)
pkill -f "uvicorn app.main:app" 2>/dev/null || true
cd apps/api && nohup uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 2 > /tmp/aether-api.log 2>&1 &

# Run Prisma migration on production DB
cd packages/db && DATABASE_URL=$DATABASE_URL pnpm prisma migrate deploy

# Seed demo data (canonical funnel + sample jobs + sample resume parse)
cd apps/api && python scripts/seed_demo.py

# Verify deployment
curl -so /dev/null -w "%{http_code}" https://5cb5f0620.abacusai.cloud/dashboard
# expect: 200
curl -s http://localhost:8000/health
# expect: {"status":"ok","version":"0.2.0"}
curl -s http://localhost:8000/openapi.json | python3 -c "import sys,json; paths=json.load(sys.stdin)['paths']; print(len(paths), 'routes')"
# expect: 30+ routes
```

### 9.3 Nginx update (CORS + API proxy)
Update the nginx vhost to also proxy `/api/` to FastAPI:
```nginx
# /etc/nginx/conf.d/5cb5f0620.conf
server {
    listen 80;
    server_name 5cb5f0620.vm.internal;

    # Next.js web app
    location / {
        proxy_pass http://127.0.0.1:3000;
        proxy_set_header Host $http_x_original_host;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }

    # FastAPI backend (proxied through /api/)
    location /api/ {
        rewrite ^/api/(.*) /$1 break;
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $http_x_original_host;
        proxy_http_version 1.1;
        add_header Access-Control-Allow-Origin "https://5cb5f0620.abacusai.cloud" always;
    }
}
```

Update `NEXT_PUBLIC_API_BASE_URL=https://5cb5f0620.abacusai.cloud/api` in `.env` for the production web app.

---

## 10. PRODUCTION VALIDATION (manual walkthrough — every feature)

After deployment, perform this walkthrough and screenshot/record each step in `docs/delivery/PHASE-2-REVIEW.md`:

### Walkthrough script
1. **Register + Login:** Navigate to `/` → see login page → register new user → log in → redirected to dashboard with live stats (not hardcoded 37/24%/3/91%)
2. **Run Job Discovery:** Click "Jobs" in sidebar → click "Run Discovery" → watch loading state → see real job cards appear with fit scores
3. **View Job Detail:** Click a job card → see full description, requirements, ATS score breakdown
4. **Save a Job:** Click bookmark icon → badge changes to ⭐ Saved
5. **Tailor Resume:** Click "Tailor Résumé →" on a job → loading → see new tailored resume in Resume Studio with diff highlighting
6. **Verify No Fabrication:** In Resume Studio, check tailored bullets → hover evidence tooltip → confirm all bullets cite source
7. **Generate Cover Letter:** Click "Generate Cover Letter" → loading → see letter in Cover Letter Studio with approval status "Pending"
8. **Approve Cover Letter:** Click "Approvals" → see pending approval → expand preview → click "Approve"
9. **Story Bank:** Navigate to Story Bank → click "Auto-Extract from Resume" → see STAR entries generated
10. **Analytics:** Navigate to Analytics → select "30d" → verify funnel shows live numbers with time filter working
11. **Agents Monitor:** Navigate to Agents → see all 6 agents with status, last run, cost
12. **Test an Agent:** Click "Test Agent" on Scout → see run result in ≤ 10s
13. **Application Tracker:** Navigate to Applications → see Kanban board with application cards
14. **Approval Gate Bypass Test:** Try to submit an application without approval → should be blocked
15. **Resume Version Compare:** In Resume Studio, select base + tailored version → click Compare → see side-by-side diff

Document each step: ✅ pass / ❌ fail with screenshot.

---

## 11. COMMIT AND PUSH PROTOCOL

### Commit convention
Each slice gets its own commit (or small group of tightly related commits):
```bash
test(auth): failing tests for register/login [P2-S01]
feat(auth): user repository + bcrypt + JWT login [P2-S01]
test(discovery): failing adapter + persistence tests [P2-S02]
feat(discovery): seek/linkedin/indeed adapters + job repository [P2-S02]
test(ats): failing scoring monotonicity + boundary tests [P2-S03]
feat(ats): ATS engine (TF-IDF + sentence-transformers, 0-100) [P2-S03]
feat(agents): LangGraph orchestration graph [P2-S08]
feat(web): jobs page wired to API [P2-S-frontend]
feat(web): resume studio with diff view [P2-S-frontend]
...
docs(delivery): Phase 2 PROGRESS.md + DECISIONS.md update
```

### Push cadence
Push to `origin/phase-2/intelligence` after every slice. Never accumulate more than 2 uncommitted slices.

### End-of-session
```bash
# Before ending the session:
pnpm -r run test && cd apps/api && pytest -q  # must be green
git add -A
git commit -m "docs(delivery): end-of-session state update [Phase 2]"
git push origin phase-2/intelligence
# Update PROGRESS.md with exact status of each slice
# Update DECISIONS.md with any new ADRs
# Leave WIP: note if a slice is mid-flight: exact next RED test to write
```

---

## 12. PROGRESS.MD UPDATE TEMPLATE (add after each slice)

Append to `docs/delivery/PROGRESS.md` under the Phase 2 slice ledger:

```markdown
## Phase 2 — Intelligence (branch: phase-2/intelligence)

| ID       | Title                                  | Status | Tests     | Commit  | Notes |
|----------|----------------------------------------|--------|-----------|---------|-------|
| P2-S01   | User repo + real auth (bcrypt + JWT)   | ✅     | N/N       | `sha`   |       |
| P2-S02   | Job discovery adapters + persistence   | ✅     | N/N       | `sha`   |       |
| P2-S03   | ATS scoring engine (TF-IDF + embeddings)| ✅    | N/N       | `sha`   |       |
| P2-S04   | FitScorer agent                        | ✅     | N/N       | `sha`   |       |
| P2-S05   | Resume tailoring agent (LLM + guard)   | ✅     | N/N       | `sha`   |       |
| P2-S06   | Cover letter agent + FabricationGuard  | ✅     | N/N       | `sha`   |       |
| P2-S07   | Approval gateway (state machine)       | ✅     | N/N       | `sha`   |       |
| P2-S08   | LangGraph multi-agent orchestration    | ✅     | N/N       | `sha`   |       |
| P2-S09   | Story Bank + STAR extractor            | ✅     | N/N       | `sha`   |       |
| P2-S10   | Analytics aggregates + live dashboard  | ✅     | N/N       | `sha`   |       |
| P2-FE-01 | Jobs page (wired, real data)           | ✅     | N/N       | `sha`   |       |
| P2-FE-02 | Resume Studio (diff view)              | ✅     | N/N       | `sha`   |       |
| P2-FE-03 | Story Bank page                        | ✅     | N/N       | `sha`   |       |
| P2-FE-04 | Application Tracker (Kanban)           | ✅     | N/N       | `sha`   |       |
| P2-FE-05 | Agents Monitor                         | ✅     | N/N       | `sha`   |       |
| P2-FE-06 | Analytics page (time-period selector)  | ✅     | N/N       | `sha`   |       |
| P2-FE-07 | Approval modal (wired)                 | ✅     | N/N       | `sha`   |       |
| P2-FE-08 | Cover Letter Studio (wired)            | ✅     | N/N       | `sha`   |       |
| —        | Adversarial review + verification      | ✅     | 0 fails   | `sha`   | docs/delivery/PHASE-2-REVIEW.md |
| —        | Production deployment + walkthrough    | ✅     | —         | `sha`   | https://5cb5f0620.abacusai.cloud |
```

---

## 13. DECISIONS.MD ENTRIES TO ADD

Add these ADR entries as they are decided:

```markdown
## D-0010 — ATS engine: TF-IDF + sentence-transformers, no LLM
Date: Phase 2 · Decision: Use scikit-learn TF-IDF + all-MiniLM-L6-v2 for ATS scoring.
No LLM calls. Reasons: deterministic (testable monotonicity), fast, zero cost, no API key needed in CI.
Alternative: GPT-based scoring. Rejected: non-deterministic, expensive, slower.

## D-0011 — FabricationGuard: spaCy NER + token-set intersection
Date: Phase 2 · Decision: Use spaCy en_core_web_sm NER + noun-chunk extraction to check
every LLM output against the evidence corpus. Rejected: exact string matching (too brittle),
GPT-based fact-checking (non-deterministic). Reversible: yes.

## D-0012 — LLM record-replay in Python (mirror of TS implementation)
Date: Phase 2 · Decision: Implement a Python llm_client.py that honours AETHER_LLM_MODE
(replay/record/auto), mirroring the TS RecordReplayLLMClient. CI always runs in replay mode.
Alternative: always mock LLM in Python tests. Rejected: masks real prompt/response failures.

## D-0013 — Prisma schema is the single DB source of truth
Date: Phase 2 · Decision: Python services use raw psycopg2/asyncpg (or SQLAlchemy with
reflect=True) against the Prisma-managed schema. No separate SQLAlchemy models.
This avoids schema drift between TS and Python layers.
```

---

## 14. ENVIRONMENT VARIABLES (add all new vars to .env.example)

```bash
# Phase 2 additions — add to .env.example with placeholder values
AETHER_MODEL_REASONING=deepseek/deepseek-chat-v3-0324:free
AETHER_MODEL_FAST=meta-llama/llama-3.3-70b-instruct:free
AETHER_MODEL_STRUCTURED=qwen/qwen-2.5-72b-instruct:free
AETHER_MODEL_LIGHT=meta-llama/llama-3.1-8b-instruct:free
AETHER_LLM_MODE=auto          # replay | record | auto
DATABASE_URL_TEST=postgresql://aether:aether@localhost:5432/aether_test

# Job board adapters (no API keys needed — HTML scrapers)
SEEK_BASE_URL=https://www.seek.com.au
LINKEDIN_BASE_URL=https://www.linkedin.com/jobs
INDEED_BASE_URL=https://au.indeed.com

# Sentence-transformers model cache
SENTENCE_TRANSFORMERS_HOME=/tmp/aether_models

# spaCy model path (downloaded once)
SPACY_MODEL=en_core_web_sm
```

---

## 15. WHAT SUCCESS LOOKS LIKE (definition of done for Phase 2)

Phase 2 is done when ALL of the following are true — verified, not assumed:

- [ ] `pnpm -r run test` → **≥ 150 tests passing**, 0 failures
- [ ] `cd apps/api && pytest -q` → **≥ 80 tests passing**, 0 failures
- [ ] `playwright test` → **≥ 15 e2e tests passing** across all major pages
- [ ] `pytest --cov=app --cov-fail-under=85` → **coverage ≥ 85%** on all route handlers + services
- [ ] `pnpm -r run lint && pnpm -r run type-check` → exit 0
- [ ] `ruff check . && mypy app` → exit 0
- [ ] `git ls-files .env` → empty (not tracked)
- [ ] Adversarial review document at `docs/delivery/PHASE-2-REVIEW.md` with **0 open BLOCKERS**
- [ ] Live deployment at `https://5cb5f0620.abacusai.cloud` returns 200 on all 12 nav routes
- [ ] Manual walkthrough (§10) completed with all 15 steps ✅
- [ ] `PROGRESS.md` shows all P2 slices as ✅
- [ ] `DECISIONS.md` has D-0010 through D-0013 (minimum)
- [ ] PR opened on `phase-2/intelligence` against `main` — do NOT self-merge

---

*Remember: RED → GREEN → REFACTOR. One failing test at a time. Never fabricate. Preserve format. Ship truth.*
