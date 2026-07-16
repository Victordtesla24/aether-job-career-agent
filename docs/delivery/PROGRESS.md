# Aether Delivery Progress
Last updated: 2026-07-16 by doc-updater sub-agent (Phase 6 documentation refresh, GAP-P6-DOCS-001/GATE-19)
Current phase: Phase 6 — Subscription/billing/admin/sourcing-compliance/quality (production, `main`, https://5cb5f0620.abacusai.cloud)
Branch: `main`  |  CI: workflow active at `.github/workflows/ci.yml` (mirror kept at `ci/github-actions-ci.yml`)

## Phases 3–5 — tracked in dedicated per-phase documents, not this file

This file (`PROGRESS.md`) was the single delivery log through Phase 2. Starting with Phase 3, each phase's
gap ledger, execution summary, and decisions were recorded in their own dedicated document instead of being
appended here — this section restores the pointer trail so a reader starting from `PROGRESS.md` can still
find every phase:

- **Phase 3** — `docs/delivery/PHASE3-GAP-LEDGER.md`
- **Phase 4** — `docs/delivery/PHASE4-GAP-ANALYSIS.md`
- **Provider-config run** (Anthropic-subscription-vs-API-key provider configuration, Gmail PKCE fix) — `docs/delivery/PROVIDER-CONFIG-RUN.md`
- **Phase 5** ("prud-remediation" + separately, "prod-remediation" runs) — `docs/delivery/PHASE5-GAP-ANALYSIS.md`, `docs/delivery/PHASE5-EXECUTION-SUMMARY.md`, and the repo-root `EXECUTION-REPORT.md` (2026-07-15 remediation run; superseded in part by Phase 6 — see the correction note at the top of that file)
- **Requirements traceability** (production, cumulative) — `docs/delivery/REQUIREMENTS-TRACEABILITY-PRODUCTION.md`

## Phase 6 — Subscription, billing, admin, sourcing-compliance, quality (2026-07-16)

**Prompt:** `aether-subscription-prompt.md` · **Orchestrator:** `claude-fable-5 (xhigh)`, decision points only.
**Machine ledger:** `docs/delivery/phase6-gap-analysis.json` (27 gaps) · **Narrative ledger:**
`docs/delivery/PHASE6-GAP-ANALYSIS.md` · **Human-gated checklist:** `docs/delivery/PHASE6-BLOCKED-ON-HUMAN.md` ·
**Model governance:** `docs/delivery/PHASE6-GOVERNANCE-AUDIT.md` · **Evidence:** `uat/reports/evidence/phase6/`.

**Binding ADRs (recorded in `docs/delivery/DECISIONS.md`):** `ADR-P6-SEEK` (Seek scraping is ToS-prohibited;
sourcing volume via Adzuna AU + ATS APIs instead), `ADR-P6-OAUTH` (Anthropic third-party subscription OAuth
is prohibited by Anthropic's own Consumer ToS; API-key-only enforced, OAuth stays flag-disabled),
`ADR-P6-STRIPE-MOCK` (billing built now against a mocked Stripe SDK; live round-trip gates human-gated),
`ADR-P6-PRICING` (ratified subscription tiers, overriding the billing-architecture design doc's proposed
quotas/annual pricing), plus the tailoring entailment-verification and top-K batch-cap decisions.

**Gap ledger final status (27 gaps):**

| Status | Count |
|---|---|
| VERIFIED-CLOSED | 17 |
| FIX-READY-MERGED (billing — code+tests complete, live Stripe round-trip blocked-on-human) | 3 |
| PROD-FLOW-VERIFIED / GATE-17-human-gated (admin panel) | 2 |
| CODE-VERIFIED-CLOSED / LIVE-BLOCKED-ON-HUMAN (multi-Gmail) | 1 |
| TRIAGED (Cluster H — repo/branch cleanup, directory reorg, this doc refresh, EXECUTION-REPORT re-verify) | 4 |

**Shipped:**
- **Subscription billing** — Free/Starter/Pro/Power tiers (A$0/19/39/69 monthly, A$179/359/649 annual,
  GST-inclusive, `gst=round(total/11,2)` per `ADR-P6-PRICING`), Stripe Checkout/webhook/portal, atomic
  quota reserve-before-run + refund-on-failure, `/pricing` page live. Built + unit-tested against mocked
  Stripe (`ADR-P6-STRIPE-MOCK`); live verification (checkout, webhook, GST-on-invoice, Stripe Tax) is
  BLOCKED-ON-HUMAN pending operator Stripe test credentials. Evidence: `review-billing.json`,
  `docs/subscription/billing-architecture.md`.
- **Admin panel (Tier 1)** — users/spend, spend-cap, suspend/unsuspend, settings, append-only audit log,
  health; all routes gated server-side on `isAdmin`. Spend-cap-before-LLM proven live (429 fired before any
  `AgentRun` row was created). `admin/admin123` demoted to `isAdmin=false` unconditionally on every boot
  (GATE-31 verified live). Full GATE-17 closure needs operator-rotated `AETHER_ADMIN_EMAIL`/`AETHER_ADMIN_PASSWORD_HASH`.
  Evidence: `review-admin.json`, `gate17-admin-verification-raw.json`.
- **Sourcing ToS compliance** — Seek scraping (confirmed ToS-prohibited: `seek-tos-check.md`, `robots.txt`
  names `anthropic-ai`) excluded from the live adapter registry by default. Volume restored via Adzuna AU
  (licensed API, optional creds) + Greenhouse/Lever/Ashby/Workable + Remotive/RemoteOK: live re-probe shows
  30 active-feed jobs / 5 sources, 100% fresh ≤30d, 0 duplicates, 0 Seek. Evidence: `qa-prod-sourcing.json`.
- **Tailoring & cover-letter quality** — removed a fixture-fallback defect (auto mode no longer silently
  serves canned fixtures on live-LLM failure; honest 503 + quota refund instead); added entailment
  verification so an unsupported claim is reverted rather than shipped; a top-8 batch cap + scaled
  entailment budget resolved the resulting reliability regression. Live QA (`qa-prod-craft5.json`): 8/10
  honest completions, 2 with a genuine, independently-reconfirmed ATS lift (30.81→32.97), **zero**
  fabrication survivors across all 8. **Honest residual:** ~20% of attempts return a clean HTTP 503 (never
  a fixture) — synchronous generation under the ~100s HTTP edge; durable fix is async generation
  (`BACKLOG-P6-02`, out of Phase 6 scope).

**Human-gated (pending operator action, not fixable by an agent):** Stripe test-mode keys + webhook secret
+ Price IDs + ABN/Tax (unblocks GATE-13/14/15/16/33); `AETHER_ADMIN_EMAIL`/`AETHER_ADMIN_PASSWORD_HASH`
(closes GATE-17); a second real Gmail account's OAuth consent (closes GATE-05). Full instructions:
`docs/delivery/PHASE6-BLOCKED-ON-HUMAN.md`.

**Honest residuals (tracked backlog, non-blocking):** `BACKLOG-P6-01` (per-run Cost column not surfaced in
the `/dashboard/agents` Recent Runs table — an aggregate avg-cost stat is shown instead); `BACKLOG-P6-02`
(the ~20% honest tailoring/cover-letter 503 rate above); the sourcing volume margin is real but thin
(remoteok/remotive contribute 1 job each, lever sits exactly at the 5-job floor, Adzuna contributes 0
without operator credentials — not required for today's GATE-07 pass).

**Cluster H (this update):** documentation refresh (`README.md`, `EXECUTION-REPORT.md`, `PROGRESS.md`,
`DECISIONS.md`, `TRACEABILITY-MATRIX.md`, new `docs/subscription/`) targets GATE-19/20/28. Gate closure
itself is the reviewer/QA sub-agent's sole authority (no self-approval) — this entry documents what was
written and re-verified, not a claimed gate closure.

## Phase-2 adversarial audit + fix loop (2026-07-09)

Full wireframe↔backend wiring audit against production (17 wireframes, 37 API routes, journeys
J1–J7). Deliverables: `docs/delivery/TRACEABILITY-MATRIX.md` (per-wireframe verdicts with live
proof) and `docs/delivery/DEFECTS-PHASE-2-AUDIT.md` (defects D1–D9 with before/after evidence).

- **Fixed & verified on production:** D1 524-timeout on cover-letter/pipeline (hard wall-clock LLM
  cap + shared pipeline budget + provider override, ADR D-0017 — now 200 in ≈60–62 s); D2
  approve/reject now moves the linked application draft→submitted/rejected (ADR D-0016); D3
  contaminated cover-letter retry fixture neutralised; D4 per-job "Tailor Resume" deep link; D5
  resume Download with graceful 501 note; D6 Story Bank create/edit STAR form; D7 application
  detail panel + pending-approvals banner; D8 approval expiry badge + disabled actions; D9
  stage-conversion rates rendered on analytics.
- **New env vars** (`.env.example`): `AETHER_MODEL_FALLBACK`, `AETHER_LLM_BASE_URL`,
  `AETHER_LLM_API_KEY` (any OpenAI-compatible provider, e.g. Anthropic Claude).
- **Gates:** pytest 104 passed / coverage 89%; ruff+mypy clean; vitest 47 passed; lint,
  type-check, build clean; Playwright e2e 24 passed.

## Section C — BA resume built, registered & tailored (2026-07-10)

- **PDF:** `assets/resume/Vik_Resume_BA_Final.pdf` (3 pages) — Senior Business Analyst / Product
  Owner variant, rebuilt programmatically (`scripts/generate_ba_resume.py`, reportlab) in the
  **identical visual format** of `assets/resume/Vik_Resume_Final.pdf` (two-column, left rail,
  peach title panel, coral accents; format spec measured from the original with PyMuPDF). Every
  claim traces to `Vik_Resume_BA.pdf` / `Vik_Resume_Final.pdf` only — no fabrication.
  `Vik_Resume_Final.pdf` untouched (md5 `16b856c0f3f4ec0d801fdde6d084452c` verified before/after).
- **Registered via the app's own API:** new `POST /resumes` ingestion endpoint +
  `scripts/ingest_ba_resume.py` → production root resume id `c57a44d136100943494554143`
  (version 15). `GET /api/resumes` now returns **15 resumes / 2 roots** (BA + demo seed); visible
  in Resume Studio (screenshot `reverify-C-resume-studio.png` in the evidence archive).
- **Tailoring against it:** `POST /agents/tailor/run` with new optional `resume_id` →
  **20 accepted changes**, child resume `c39cbf4a6e6d1b3b2fe37787d` parented to the BA root with
  the same `formatHash` (`2df88344d04efe30`). ADR **D-0018**.
- **Gates after changes:** pytest **108 passed** / coverage **89%**; ruff + mypy clean.

## Production defect fixes (2026-07-10)

Live-environment defects found on https://5cb5f0620.abacusai.cloud, all fixed and verified live:

1. **Cover-letter agent hang (>120 s, then 502).** Root cause: `_call_live` used urllib with a
   120 s per-call timeout and the corrective drafting loop (≤3 drafts × 2-model fallback chain)
   had **no overall budget** — worst case 6 live OpenRouter calls ≈ 720 s while the free tier
   stalls. Fix (`llm_client.py`): httpx with strict per-call timeouts (connect 10 s / read 30 s)
   plus a client-wide wall-clock budget (`AETHER_LLM_BUDGET_SECONDS`, default 60 s) spanning the
   whole fallback chain; once exhausted, requests degrade to fixture replay or a typed 503 —
   never a hang. Two extra graceful-degradation paths: malformed/truncated live JSON falls back
   to the fixture (was an unhandled 500), and a missing per-attempt fixture key (`retry`/`retry2`)
   degrades to the `default` fixture (was a spurious 503). Live verification: cover-letter run for
   the previously-hanging job returned **HTTP 200 in ~94 s** (bounded; was infinite) with a real
   draft + pending approval.
2. **Tailoring guard rejected every rewrite (`changes: 0`).** Raw-verbatim token matching flagged
   unicode punctuation, inflections and number formats as fabrication. Fixed with a normalized
   evidence index (unicode folding + stemming + number-value equivalence + stopword exemption) —
   see **ADR D-0015**. Live verification: tailor run returned `changes: 22` with 3 genuinely
   novel bullets rejected; `/resumes/{id}/diff` shows evidence-linked before/after entries.
3. **`/login` 404.** Real login page added (`apps/web/src/app/login/page.tsx`): demo credentials
   prefilled, POSTs `/api/auth/login`, stores the JWT under the `aether_token` localStorage key,
   redirects to `/dashboard`; wrong credentials show an inline alert. Covered by 3 Playwright specs.
4. **nginx proxy timeout.** `/api/` location on the live vhost now has
   `proxy_connect_timeout 10s; proxy_send_timeout 30s; proxy_read_timeout 180s` (server-side
   config only — not a repo file).
5. **Wireframe sweep (design/screens/*.html as contract).** Two rendered-but-unwired controls with
   real backend support were wired: Jobs page **source filter** (Seek/LinkedIn/Indeed →
   `GET /jobs?source=`) and Cover-letter studio **Regenerate** button (re-runs the cover-letter
   agent for that letter's job). Controls without backend support (kanban drag, topbar search,
   approval edit-and-approve, analytics export) were intentionally left as-is.
6. **Test determinism.** `tests/conftest.py` now forces `AETHER_LLM_MODE=replay` (matching CI) so
   a developer `.env` with `auto` can never make the suite hit the rate-limited live backend.

Verification (2026-07-10): **99 pytest**, **85 vitest**, **24 Playwright** — all green; ruff +
mypy + eslint + tsc clean; `pnpm build` clean; all dashboard routes + `/login` return 200 live.

## Phase 2 — Intelligence (session started 2026-07-02)
`phase-1/foundation` was merged into `main` (merge commit `969643e`) and `phase-2/intelligence` was
branched from the merged `main`. Session-setup checklist:

- **Environment**: `.env` extended with Phase 2 model tiers (`AETHER_MODEL_REASONING`,
  `AETHER_MODEL_FAST`, `AETHER_MODEL_STRUCTURED`, `AETHER_MODEL_LIGHT`), `AETHER_LLM_MODE=auto`,
  `DATABASE_URL` / `DATABASE_URL_TEST` (hosted PostgreSQL), `REDIS_URL`, job-board base URLs
  (`SEEK_BASE_URL`, `LINKEDIN_BASE_URL`, `INDEED_BASE_URL`), and NLP settings
  (`SENTENCE_TRANSFORMERS_HOME`, `SPACY_MODEL`). `.env.example` updated with matching placeholders.
- **Database**: Abacus.AI hosted PostgreSQL (single database granted; no `CREATEDB` privilege), so
  dev/test isolation uses dedicated schemas `aether` and `aether_test` via Prisma's `?schema=`
  URL parameter. `prisma db push` applied the full Phase 1 schema to both (10 tables each).
  The hosted server does not ship pgvector, so `JobEmbedding.vector` was changed from
  `Unsupported("vector(1536)")` to a portable `Float[]` (see schema comment; cosine similarity is
  computed application-side, Pinecone remains the optional external vector store).
- **Redis**: `redis-server` installed and running locally (`redis://localhost:6379`, PONG verified).
- **OpenRouter**: `scripts/validate-openrouter.mjs` passed — key authenticated; free models
  transiently rate-limited (HTTP 429), treated as reachable.
- **Baseline**: all Phase 1 tests re-run green on `phase-2/intelligence` (see verification below).

### Phase 2 Slice Ledger

| Slice  | Title                                        | Status | Tests | Notes |
|--------|----------------------------------------------|--------|-------|-------|
| P2-S01 | User repository + real auth (bcrypt + JWT)   | ✅     | 10 py | `POST /auth/register` (201, policy: ≥8 chars + digit, 409 on dup email, hash never exposed), `POST /auth/login` (JWT HS256, 24h exp, userId/email/iat/exp claims), `get_current_user` bearer dependency guards `/jobs`. `UserRepository` = raw psycopg2 over the Prisma `User` table (new nullable `passwordHash` column, `prisma db push` applied to `aether` + `aether_test`). |
| P2-S02 | Job discovery: adapters + persistence        | ✅     | 7 py + 6 ts | `BaseAdapter` (fixture mode primary; live HTTP intentionally `NotImplementedError` — never fake live data) + Seek/LinkedIn/Indeed adapters + registry. `JobRepository` upserts on new unique `(userId, sourceUrl)` (idempotent re-scouting). `ScoutAgent` fans out over all sources. Routes: `GET /jobs` (status/source/saved/sort filters), `GET /jobs/{id}`, `POST /jobs/{id}/save`, `DELETE /jobs/{id}` (soft archive), `POST /agents/scout/run` → 202. Web: `src/lib/api/jobs.ts` typed client with zod validation (zod added to apps/web). Fixtures: `apps/api/tests/fixtures/http/{seek,linkedin,indeed}/jobs.json` (2 realistic AU tech jobs each). |
| P2-S03 | ATS scoring engine (0–100, deterministic)    | ✅     | 7 py | `ATSEngine.score(resume, jd) -> ATSScore` — 0.4·keyword_match (TF-IDF-ranked JD keywords → resume coverage) + 0.4·semantic_similarity (sentence-transformers all-MiniLM-L6-v2 iff installed AND cached in `SENTENCE_TRANSFORMERS_HOME=/tmp/aether_models`; deterministic token-overlap fallback otherwise — never downloads at scoring time) + 0.2·experience score (regex years parsing, pro-rated gap). `requires_review=True` below 60. scikit-learn in requirements.txt; sentence-transformers optional in `requirements-ml.txt` (heavy torch dep kept out of CI). |

| P2-S04 | LLM fit scoring (record-replay client)       | ✅     | 2 py | `LLMClient` with record/replay modes (`AETHER_LLM_MODE`, default **replay** — CI/tests never hit the network; fixtures at `apps/api/tests/fixtures/llm/<prompt>/<key>.json`), model tiers resolved from `AETHER_MODEL_<TIER>` env. `FitScorerAgent` scores unscored jobs against the real base resume (`assets/resume/Vik_Resume_Final.pdf`, override `AETHER_RESUME_PDF`) and persists `fitScore`; `POST /agents/fit-scorer/run`; `GET /jobs?sort=fit_score` alias. |
| P2-S05 | Resume tailoring w/ evidence-linked diffs    | ✅     | 5 py | `ResumeTailorService.tailor()` — every rewritten bullet must be a token-subset of the evidence bullet + carry an `evidenceRef`; violations are dropped, never invented. `ResumeRepository` (immutable versions, `parentId` chain, base v1 auto-ingested from the PDF). Routes: `GET /resumes`, `GET /resumes/{id}`, `GET /resumes/{id}/diff` (before/after/evidenceRef), `POST /agents/tailor/run` (creates new version, never mutates base). |
| P2-S06 | Approval gate state machine                  | ✅     | 7 py | `ApprovalRepository` + `ApprovalService`: pending → approved/rejected, terminal states return 409, 48h expiry (expired approve → 409), `assert_action_allowed` blocks execution of unapproved actions with 403. Routes: `GET /approvals?status=`, `GET /approvals/{id}`, `POST /approvals/{id}/{approve,reject,execute}`. Nothing leaves the system without an explicit human decision. |
| P2-S07 | Cover letters + fabrication guard            | ✅     | 6 py | `FabricationGuard` — capitalized entities & numeric claims in generated text must appear in resume evidence (punctuation-normalized tokens, exempt-word list); flagged drafts raise `FabricationError` and are **not** persisted. `CoverLetterAgent`: deterministic header (job title + company) + replayed LLM body; each draft stored on the `Application` row and queued as a pending `application_submit` approval (payload `kind=cover_letter`). Routes: `GET /cover-letters`, `GET /cover-letters/{id}`. |
| P2-S08 | Agent console + audited runs + story bank    | ✅     | 3 py | Every agent invocation recorded as an `AgentRun` (status/input/output/error/cost/duration). `GET /agents` (7-agent roster w/ `approval_gated` flags), `GET /agents/runs`, dedicated run routes (scout 202, fit-scorer, tailor, cover-letter, story-extractor) + `POST /agents/pipeline/run` (scout → fitScorer → tailor → coverLetter on the top job; stops at the approval gate). `StoryExtractorAgent` mines STAR stories from the resume — stories with metrics not evidenced in the resume are dropped; `GET/POST/PUT/DELETE /stories`. |
| P2-S09 | Analytics + applications API + demo seed     | ✅     | 5 py | `GET /analytics/funnel?period=7d|30d|90d|all` (invalid → 422), `/analytics/ats-distribution` (10 buckets), `/analytics/agent-roi`, `/analytics/conversion`; `GET /applications` joined with Job. `scripts/seed_demo.py` — idempotent demo user (`demo@aether.dev`) + canonical funnel (847 jobs / 412 applications) via batched inserts (hosted-PG friendly). API version bumped to **0.2.0**. |
| P2-S10 | LangGraph orchestration graph (TS)           | ✅     | 6 ts | `AetherGraph` (`packages/agents/src/graph/aether-graph.ts`): supervisor → scout → matcher → tailor → coverLetter node chain built on `@langchain/langgraph` `StateGraph`/`Annotation`; `runNode()` records `GraphRunRecord`s; approval-gated nodes (`tailor`, `coverLetter`) halt with `pending_approval` instead of acting. |
| P2-FE  | Dashboard frontend (8 pages, live wiring)    | ✅     | 3 ts + build | `apps/web/src/lib/api/client.ts` (demo auto-login, 401 retry, `/api` proxy base) + 7 typed zod clients. Pages: jobs (filters/save/Run Discovery), resume (versions/tailor/diff), stories (STAR cards/extractor), applications (6-column kanban), agents (roster/runs/pipeline), analytics (funnel + period selector, ATS bars, ROI), approvals (approve/reject queue), cover-letters (job select/draft viewer). Dashboard home stats now live from `GET /analytics/funnel` (`DashboardStats`; hardcoded Phase 1 STATS removed, guarded by `src/__tests__/dashboard/live-stats.test.ts`). e2e placeholder spec repointed at a still-unbuilt route (`/dashboard/interviews`). |

**Test infrastructure (P2-S01):** `apps/api/tests/conftest.py` — points the app at
`DATABASE_URL_TEST` (schema `aether_test`) before import, `client` (TestClient, truncates
`Job`/`User` per test), `db_session` (raw psycopg2), `auth_headers` (register+login fixture user).
`app/db.py` translates Prisma-style `?schema=` URLs into psycopg2 `search_path` options;
connections are short-lived (hosted PG caps at 25 concurrent).

**Verification after P2-S03:** API 46/46 pytest green (22 Phase 1 + 24 new), ruff + mypy clean;
Node 76/76 green across workspaces (shared 4, web 35, agents 18, db 12, queue 7); web lint +
type-check clean.

**Verification after P2-S10 + frontend (2026-07-02):** API **74/74** pytest green; ruff + mypy
clean (48 files). Node **85/85** green across workspaces (shared 4, web 38, agents 24, db 12,
queue 7); web lint + type-check + `next build` clean (13 routes). **Deployed:**
`aether-api.service` (uvicorn :8000, systemd) + `aether-web.service` (Next :3000) behind nginx —
`https://5cb5f0620.abacusai.cloud/dashboard` → 200, `/api/health` → `{"status":"ok","version":"0.2.0"}`;
demo data seeded and the live funnel verified end-to-end with the demo login. `.env` `NEXTAUTH_SECRET` rotated from the `change-me` placeholder to a random
64-hex secret (JWT signing uses `JWT_SECRET` || `NEXTAUTH_SECRET`).

**Post-review hardening (2026-07-09):** an independent review found 3 genuine defects — all fixed:
1. **TS type-check failure** in `packages/agents/src/graph/aether-graph.ts` (7 errors): the
   LangGraph `StateGraph` was built with un-chained `addNode` calls, so `addEdge` only knew
   `__start__`/`__end__`. Fixed with the chained builder pattern (each `.addNode()` widens the
   node-name union) — no `as any`. `pnpm -r run type-check` → exit 0.
2. **Live 500s on LLM agent endpoints**: 3 of 4 configured OpenRouter free-tier model ids had been
   retired upstream (404). Model ids refreshed in `.env`/`.env.example`; `LLMClient` `auto` mode now
   has a resilience chain (primary model → one retry with `openai/gpt-oss-20b:free` → recorded
   fixture → typed `LLMUnavailableError` mapped to HTTP **503**, never a 500). See ADR **D-0014**.
   Live-verified: `POST /agents/tailor/run`, `/agents/cover-letter/run`, `/agents/story-extractor/run`
   all return 200 through real OpenRouter calls. Also hardened: `FabricationGuard` no longer
   false-positives on sentence-initial title-case words; cover-letter agent gained a corrective
   drafting loop (≤3 attempts feeding flagged terms back to the model).
3. **Playwright e2e gap** (3 tests → **21 passing**): new specs for jobs, resume, analytics,
   agents, approvals, stories, applications and cover-letters run against the production build with
   the live API (`next.config.mjs` now mirrors the nginx `/api` → :8000 rewrite for standalone
   `next start`).

**Verification after post-review hardening (2026-07-09):** API **81/81** pytest green (74 + 7 new
`test_llm_resilience.py`); ruff + mypy clean (48 files). Node **85/85** vitest green;
`pnpm -r run type-check` + lint clean; `next build` clean (13 routes). Playwright **21/21** e2e
green. Redeployed and live-verified: dashboard → 200, `/api/health` → 0.2.0, canonical funnel
847/412/156/23/4, all three LLM agent runs → 200.

## Phase 1 — Foundation (complete — merged to main 2026-07-02)
Strict TDD (RED → GREEN → REFACTOR), small vertical slices, one conventional commit per slice on
`phase-1/foundation`. `main` is untouched this phase (branch pushed only). No secrets committed; the
résumé PDF (`assets/resume/Vik_Resume_Final.pdf`) is read-only and never modified.

### Phase 1 Slice Ledger
| ID      | Title                                            | Status | Tests | Commit    |
|---------|--------------------------------------------------|--------|-------|-----------|
| P1-env  | OpenRouter connectivity validation script        | ✅     | green | `f0b7f8a` |
| P1-S01  | Monorepo scaffolding: shared/agents/queue + turbo | ✅     | green | `67b82fb` |
| P1-S02  | Prisma schema (pgvector + all models) + repos     | ✅     | green | `fff6c15` |
| P1-S03  | NextAuth.js + JWT + requireAuth middleware        | ✅     | green | `d00ae4a` |
| P1-S04  | Resume parser (pdfplumber, format-preserving hash)| ✅     | green | `28f991b` |
| P1-S05  | Portfolio/GitHub scraper MVP (fixture-backed)     | ✅     | green | `be54f16` |
| P1-S06  | Dashboard shell (12-item Schema-A sidebar)        | ✅     | green | `95c34a2` |
| P1-S09  | FastAPI skeleton + `/health`                      | ✅     | green | `3a04703` |
| P1-S10  | CI activation (`.github/workflows/ci.yml`)        | ✅     | green | `f109757` |
| P1-S11  | LLM fixture record-replay infra                   | ✅     | green | `4029787` |
| P1-S12  | Graceful placeholder + active-nav (unbuilt routes)| ✅     | green | `610614b` |

**P1-S01 detail:** `packages/shared` (VERSION, Result utils, secret-redacting logger, zod validation,
domain types), `packages/agents` (BaseAgent, ToolRegistry, LangGraph-compatible `AetherAgentState`),
`packages/queue` (BullMQ client + typed discovery/tailoring/application jobs), `turbo.json` (tasks:
build/test/lint/type-check/dev) and root scripts. Tests: shared 4 + agents 7 + queue 7, all green;
build/type-check/lint pass across the workspace. Note: Turbo 2.x uses `tasks` (not the deprecated
`pipeline` key); nav label standardized as "Resume Studio" per DECISIONS D-0002 (spec's "Résumé
Studio" reconciled to the repo's canonical no-accent label).

**P1-S02 detail:** `packages/db` (`@aether/db`) — full Prisma schema (`src/schema.prisma`) with the
`vector` PostgreSQL extension (pgvector) for `JobEmbedding.embedding` (`vector(1536)`), all domain
models (User, Job, JobEmbedding, Resume with `formatHash` + self-referential version lineage,
Application, ApprovalRequest, Contact, EmailThread, StoryEntry, AgentRun) and enums. Typed
repositories (Job/Resume/Application/User) built on `import type` from `@prisma/client` so unit tests
run without a generated client or live DB. Tests: 13 green (5 schema-structure + 8 repository). A
package-scoped `turbo.json` wires `prisma:generate` ahead of build/type-check via `extends: ["//"]`.
`prisma generate` runs offline; `migrate dev` is deferred until `DATABASE_URL` is provisioned.

**P1-S03 detail:** `apps/web/src/lib/auth` — framework-agnostic auth core: `jwt.ts` (sign/verify
session tokens via `jose`, the library NextAuth uses internally), `session.ts` (session model +
token→session resolution), `require-auth.ts` (`requireAuth` guard reading Bearer header or session
cookie, returning a discriminated result), `credentials.ts` (`authorizeCredentials` provider
callback with injected user-lookup + password-verify; never leaks the hash), `options.ts`
(`authConfig`, a NextAuth-shaped Credentials + stateless-JWT config), plus `test-helpers.ts`. Tests:
18 green (5 JWT + 6 guard + 7 credentials/config). NextAuth route-handler wiring is deferred to
P1-S06 when Next.js lands — see DECISIONS D-0006. Secret comes from `NEXTAUTH_SECRET` (already in
`.env.example`); it is never logged.

**P1-S04 detail:** `apps/api/app/services` — `resume_parser.py` (`compute_format_hash` = SHA-256 of
the raw PDF bytes → the immutable format identity; `parse_resume_pdf` extracts page count, raw text,
contact fields (email/phone/linkedin/github via regex) and detects known section headings using
`pdfplumber`) and `resume_tailor.py` (`tailor_bullets`, a lossless passthrough stub — the seam for
LLM tailoring in Phase 2). Tests: 10 green, asserting against the *real* content of the read-only
`assets/resume/Vik_Resume_Final.pdf` (no fabrication) and pinning the format hash
`0700d1aa…0768a25`. Runtime dep `pdfplumber` added to `pyproject.toml` + `requirements.txt`;
`requirements-dev.txt` now `-r requirements.txt` so CI installs runtime deps too. The resume asset is
byte-for-byte unchanged. Uses the repo's existing `app/` package (not the spec's `api/`).

**P1-S05 detail:** `apps/api/app/services/portfolio_scraper.py` — `scrape_github_profile(username,
fixture=None)` normalises a GitHub profile into the portfolio-card shape (identity, follower/repo
counts, `total_stars`, `top_languages` ranked by frequency, `top_repos` sorted by stars). Fixture
mode (`fixture=`) runs fully offline for tests; live mode fetches the public GitHub REST API via the
stdlib `urllib` (no new dependency ahead of the FastAPI/httpx slice). Deterministic, clearly-synthetic
fixtures live in `tests/fixtures/github_fixture.py`. Tests: 5 green (normalisation, star-sort,
language aggregation, empty-profile, blank-username guard).

**P1-S06 detail:** `apps/web` becomes a real Next.js 14 App Router app. The 12-item Schema-A sidebar
renders from a single pure-data contract, `src/lib/navigation.ts` (no React/Next imports), asserted
by `__tests__/navigation.test.ts` (5 tests: count = 12, canonical order/labels, "Resume Studio" with
no accent per D-0002, unique hrefs + non-empty icons, Dashboard → `/dashboard`). Shell: root
`layout.tsx` (fonts/Font Awesome via `<link>` — offline-safe, not `next/font`), `page.tsx`
(`/`→`/dashboard`), `dashboard/{layout,page}.tsx`, and `components/{sidebar,topbar}.tsx`, styled with
Tailwind + the glassmorphism tokens from `design/screens/dashboard.html`. NextAuth is wired
(fulfilling D-0006): `src/lib/auth/next-auth-options.ts` (real `NextAuthOptions` delegating to the
P1-S03 `authorizeCredentials`; user store seeded in Phase 2) + `src/app/api/auth/[...nextauth]/route.ts`.
Tooling: `next build`, `tsc --noEmit`, and `next lint` all pass; Vitest = 25 web tests; Playwright
smoke (`e2e/dashboard.spec.ts`, 2 tests) verifies the 12 nav items render and the root redirect. See
DECISIONS D-0007. Orphaned `tsconfig.build.json`/`.eslintrc.cjs` removed; `unrs-resolver` added to the
pnpm allowed-build list.

**P1-S09 detail:** `apps/api` becomes a real FastAPI app. A `create_app()` factory (`app/main.py`)
mounts routers and CORS (dev origins `localhost:3000`/`127.0.0.1:3000`); module-level `app` is what
`uvicorn app.main:app` serves. `app/config.py` holds pydantic-settings `Settings` (env-driven,
`extra="ignore"` so the shared root `.env` is reusable; `OPENROUTER_API_KEY` declared but optional and
never logged) plus `API_VERSION = "0.1.0"`. `app/deps.py` exposes a typed `SettingsDep` for injection.
`app/routers/health.py` serves the canonical `GET /health` → `{"status":"ok","version":"0.1.0"}`.
Tests: `tests/test_main.py` (5, via `fastapi.testclient.TestClient`) assert the payload, version
alignment with config, OpenAPI metadata/route exposure, and a 404 for unknown paths. Full API suite =
22 pytest green; ruff + mypy clean. Runtime deps (`fastapi`, `uvicorn[standard]`, `pydantic`,
`pydantic-settings`, `httpx`) added to `pyproject.toml` + `requirements.txt`.

**P1-S11 detail:** `packages/agents/src/llm` — a deterministic, offline-first LLM seam so agent tests
and CI never touch the network or need an API key. `types.ts` defines a provider-neutral contract
(`LLMMessage`/`LLMRequest`/`LLMResponse`/`LLMClient`). `fixture-store.ts` derives a stable
`fixtureKey` = SHA-256 of the *canonicalised* request (model + messages + `temperature` + `maxTokens`);
`FixtureStore` reads/writes one `<key>.json` per request and throws a helpful `No LLM fixture…` error
when a recording is missing. `record-replay-client.ts` (`RecordReplayLLMClient`) has three modes —
`replay` (default, offline, serves only committed fixtures), `record` (calls the injected live client
and persists the response), and `auto` (replay-if-present-else-record); the mode is overridable via
`AETHER_LLM_MODE`, and `record`/`auto` require an injected live client (constructor throws otherwise).
`openrouter-client.ts` (`OpenRouterClient`) is the live transport with an injectable `fetch`; the API
key is never logged, echoed, or serialised. A committed sample fixture plus
`tests/fixtures/llm/README.md` document the record→commit→replay workflow, and `AETHER_LLM_MODE` is
mirrored into `.env.example` (default `replay`). Tests: 11 new (key stability + model/message
sensitivity + 64-hex shape, store `has`/`load`, replay serves fixture with zero live calls, missing
fixture throws, record persists + becomes replayable, auto records-then-replays, record without a live
client throws). Full agents suite = 18 green; workspace = 63 unit tests green; type-check + lint clean.

**P1-S10 detail:** CI is now live at `.github/workflows/ci.yml`, promoted from the Phase-0 inert
template; `ci/github-actions-ci.yml` is kept as a byte-identical mirror so the exact pipeline stays
tracked even if a `workflows`-scoped push is rejected. On push (`main`/`phase-*/**`) and PRs to `main`
four jobs run: **security** (fails if `.env` is tracked, or a real-looking `sk-or-v1-<32+ alnum>` key
appears in source — the long-tail regex ignores synthetic test/doc placeholders), **node** (Node 20:
install → `@aether/db` `prisma:generate` → recursive lint → type-check → unit tests → build, with
`AETHER_LLM_MODE=replay` so agent tests replay committed fixtures offline), **api** (Python 3.11:
ruff → mypy → pytest), and **e2e** (Playwright chromium smoke, `needs: node`). A schedule/dispatch-only
**live-openrouter** job is non-blocking (`continue-on-error`) and skips when `OPENROUTER_API_KEY` is
unset. Prisma generate precedes type-check/build because the web app + repositories type-check against
`@prisma/client`. Every gate was verified locally before commit. Coverage-threshold enforcement
(directive target ≥85%) is a tracked follow-up — `@vitest/coverage-v8` is not yet wired, and adding an
unconfigured gate would break the green pipeline. See DECISIONS D-0008. **Push structure (workflows
permission):** the Abacus GitHub App installation lacks the `workflows` permission, so a push that
touches `.github/workflows/**` is rejected by GitHub. The slice is therefore split so everything
lands on the remote except the one blocked file: `f109757` carries the full pipeline as the tracked
mirror `ci/github-actions-ci.yml` (outside `.github/workflows/`, always pushable) plus `ci/README.md`;
this docs commit records it; and a final commit drops the byte-identical file into
`.github/workflows/ci.yml` to activate it. That final commit is the only thing pending — apply it by
granting the app the `workflows` permission and pushing, or by copying the mirror into
`.github/workflows/ci.yml` via the GitHub UI (a UI commit is made as the user, bypassing the app
restriction). See `ci/README.md`.

**P1-S12 detail:** Deployment-hardening for the shell, added while deploying + verifying Phase 1. Every
sidebar route except `/dashboard` previously fell through to a bare Next.js 404 (the feature pages are
later phases). `src/lib/navigation.ts` gains a pure `findNavItemByHref(href)` resolver (prefix-based,
most-specific-wins, `undefined` for unknown routes); the `Sidebar` becomes a client component using
`usePathname()` so the correct item highlights on *any* route (removing the hard-coded `activeHref` in
the dashboard layout — closes the "active item resolved in a later slice" TODO from P1-S06); and a
catch-all `app/dashboard/[...slug]/page.tsx` renders the section title inside the existing shell with an
honest "planned for a later phase" panel (unknown routes get a generic placeholder, still 200 not 404).
Tests: +4 resolver unit tests (web 25 → 29) and +1 Playwright smoke (clicking a nav section shows the
placeholder with correct `aria-current`, not a 404). Verified on the live deployment — all 12 nav routes
return 200. See DECISIONS D-0009.

### Deployment & end-to-end verification (2026-07-02)

Phase 1 was deployed and verified end-to-end on the Abacus supercomputer:
- **Live URL:** `https://5cb5f0620.abacusai.cloud` (Next.js production `next start` behind nginx via a
  per-host vhost + `aether-web.service` systemd unit; root `/` → 307 → `/dashboard`).
- **Web tests:** 71 Node unit tests green (shared 4, web 29, db 13, agents 18, queue 7); Playwright smoke
  3/3 green; recursive lint + type-check + `next build` all exit 0.
- **API:** FastAPI runs (`GET /health` → `{"status":"ok","version":"0.1.0"}`, OpenAPI at `/docs`); 22
  pytest green; ruff + mypy clean (11 files).
- **CI security gates (run locally):** `.env` untracked ✅; no real `sk-or-v1-<32+>` key in source ✅.
- **Wireframe fidelity:** the deployed dashboard matches `design/screens/dashboard.html` (dark
  glassmorphism, coral `#FF6B35`, 12-item Schema-A sidebar, topbar, stat cards). Full requirement→
  implementation matrix and adversarial review in `docs/delivery/PHASE-1-VERIFICATION.md`.

### Phase 1 — Adversarial self-review (pre-independent-review)

Applied three lenses — guardrail compliance, "what would a reviewer attack", and spec fidelity —
before handing Phase 1 to independent + adversarial review. Findings are recorded honestly; none are
release-blocking for a *foundation* phase, and each has an owner/next step.

**Guardrail compliance (all ✅).** Strict TDD held for every slice (a failing RED test preceded each
implementation — e.g. `record-replay.test.ts` failed on the missing `../index.js` before the LLM
module existed). No secret was ever committed: the CI `security` job now enforces this in perpetuity
(`.env` untracked + `sk-or-v1-<32+>` scan), and every commit was secret-scanned. The résumé
`assets/resume/Vik_Resume_Final.pdf` is byte-for-byte unchanged (format hash `0700d1aa…0768a25`
still pinned by the parser tests). `main` was never touched — all work is on `phase-1/foundation`,
pushed (not merged). Conventional commits with one `feat`/`ci` + one `docs(progress)` per slice.

**Adversarial findings (ranked).**
1. *Coverage is not yet enforced.* The directive targets ≥85% line coverage on
   `agents`/`db`/`shared` + API handlers; `@vitest/coverage-v8` is not wired and no threshold gate
   exists. Mitigation: behaviour is well-tested (67 Node + 22 API tests), and the gap is documented
   in D-0008. **Next:** a dedicated slice to add coverage tooling + thresholds to CI.
2. *LLM live path is unit-tested only via an injected fake.* `OpenRouterClient` uses an injectable
   `fetch`, but no unit test exercises it directly, and no test performs a real call (by design —
   CI is offline/replay). Mitigation: the non-blocking nightly `live-openrouter` job validates real
   connectivity. **Next:** add a unit test for `OpenRouterClient` with a stub `fetch` asserting
   headers/body shape and that the key is never logged.
3. *DB integration tests are skipped without a live database.* Repository tests run against types
   only; no migration/`pgvector` round-trip is exercised. Mitigation: `prisma generate` runs in CI;
   integration is gated on `DATABASE_URL`. **Next:** provision a Postgres service in CI for the
   repository/integration layer (Phase 2).
4. *Auth user store is a placeholder.* `authorizeCredentials` is wired, but `lookupUser`→`null` and
   `verifyPassword`→`false` until a user store exists (D-0006). Expected for a foundation phase;
   completed in Phase 2 against `UserRepository` + real hashing.
5. *`.github/workflows/ci.yml` is not yet on the remote* (app lacks `workflows` permission). The
   identical mirror `ci/github-actions-ci.yml` is pushed; activation is one user action away (grant
   permission or copy via UI). Fully documented (D-0008, `ci/README.md`).

**Spec-fidelity deviations (intentional, logged).** API uses the repo's existing `app/` package
rather than the spec's `api/`; the sidebar label is "Resume Studio" (no accent) per D-0002; fonts load
via `<link>` not `next/font` for hermetic offline builds per D-0007. Each is an ADR, each reversible.

**Verdict.** Foundation is coherent, green (Node 67 + API 22 tests; recursive lint/type-check/build
clean; Playwright smoke green), and honestly documented. Recommended for independent + adversarial
review, then merge to `main`. The coverage gate and the CI-workflow activation are the two explicit
follow-ups to close before/at merge.

---

## Phase 0 — Wireframes (complete, merged to `main`)

## Workflow (per user directive)
One branch per phase. Work stays on that single branch until the phase is complete, then:
**independent review + verification + adversarial review → incorporate feedback → merge to `main`** — only then is the next phase's branch opened. CI-CD is kept deliberately simple: through Phase 0 the GitHub Actions workflow was parked at `ci/github-actions-ci.yml` (outside `.github/workflows/`) so merges needed no special GitHub App `workflows` permission. In Phase 1 (slice P1-S10) CI was activated at `.github/workflows/ci.yml`, with `ci/github-actions-ci.yml` retained as a byte-identical mirror; if the app lacks the `workflows` permission the workflow push is applied via the GitHub UI instead (see `ci/README.md` and DECISIONS D-0008).

## Summary
All **Priority 1 (mandatory)** slices are complete, plus **Priority 2** (S07–S10) and one **Priority 3** new screen (Cover Letter Studio). Every slice is a single conventional commit on `phase-0/wireframes`. `main` was untouched during the phase, no secrets were committed, and the résumé PDF (`assets/resume/Vik_Resume_Final.pdf`) was not modified. Phase 0 passed an independent review, an automated verification harness (`scripts/verify_phase0.py`, 0 hard fails), and an adversarial sweep — full report in `docs/delivery/PHASE-0-REVIEW.md`. **Verdict: approved for merge to `main`.**

## Slice Ledger
| ID     | Title                              | Status | Tests    | Commit    | Notes |
|--------|------------------------------------|--------|----------|-----------|-------|
| P1-S00 | Test harness + CI skeleton         | ✅     | green    | `ac5b968` | pnpm/vitest + pytest; workflow stored at `ci/github-actions-ci.yml` (inert template); esbuild build-gate resolved via pnpm-workspace allowBuilds |
| P0-S01 | Email Center confirm gate          | ✅     | struct ✓ | `9fba8f3` | Send requires confirmation modal |
| P0-S02 | Job Discovery tailor/apply split   | ✅     | struct ✓ | `5718163` | Two-step Tailor → Review & Apply + submit gate |
| P0-S03 | Settings integration status sync   | ✅     | struct ✓ | `4f473a1` | Per-board status indicators mirror Job Discovery |
| P0-S04 | Empty states: Networking & Offers  | ✅     | struct ✓ | `4a3eead` | First-run empty states + CTAs |
| P0-S05 | Analytics time-period selector     | ✅     | struct ✓ | `a0f3e35` | Time-range pills + canonical funnel (847→412→156→23→4) across Analytics/Dashboard/Tracker |
| P0-S06 | Cross-screen contextual links      | ✅     | struct ✓ | `b0ef748` | Story Bank / CRM / Email Thread links between related screens |
| P0-S07 | Resume Studio version comparison   | ✅     | struct ✓ | `44c3507` | Compare modal (pick 2 versions, change list, restore/keep) |
| P0-S08 | Interview Center compliance banner | ✅     | struct ✓ | `1a956c7` | Recording-consent banner + Live Assist Mute Mode |
| P0-S09 | Manage Agents test button + cost   | ✅     | struct ✓ | `b2b08ef` | Test Run modal (per-agent est. + actual cost) + avg-cost/run stat |
| P0-S10 | Job Discovery Saved tab            | ✅     | struct ✓ | `04ec681` | Saved tab w/ count badge, saved view + empty state |
| P0-S14 | Cover Letter Studio (new screen)   | ✅     | struct ✓ | `ee78a7d` | New screen; resolves phantom "Cover Letters" nav item; Schema A sidebar, Evidence Trace, Voice DNA, Email hand-off |
| —      | canvas.json + review_report log    | ✅     | valid    | `022d584` | Registered new screen; Phase 0 resolution log added |
| —      | Phase 0 review + verification harness | ✅  | 0 fails  | (this session) | `docs/delivery/PHASE-0-REVIEW.md` + `scripts/verify_phase0.py`; independent + adversarial review, approved |
| P0-S11 | Mobile Dashboard badge counts      | ⬜ deferred | -   | -         | Mobile parity — later phase |
| P0-S12 | Mobile Approval swipe gestures     | ⬜ deferred | -   | -         | Mobile parity — later phase |
| P0-S13 | Onboarding Wizard (new screen)     | ⬜ deferred | -   | -         | Net-new flow — later phase |
| P0-S15 | Notification Center (new screen)   | ⬜ deferred | -   | -         | Net-new flow — later phase |

> Commit SHAs above reflect the branch after the CI-CD relocation (workflow moved out of `.github/workflows/`). They are stable and match `git log main..phase-0/wireframes`.

## Deferred to later phases (tracked in design/review_report.md + PHASE-0-REVIEW.md)
- **Cosmetic (from Phase 0 review):** standardize the optional sidebar *footer widget* below the 12-item nav (some screens show a status card, some none) and the top-bar profile chip (name+plan vs avatar-only). Pre-existing base design, non-blocking.
- Single data-model / source-of-truth reconciliation (role names, profile data, currency prefixes, source-vs-connected).
- Onboarding / first-run flow; resume → Story Bank auto-extraction.
- Interview scheduling flow; offer-acceptance wind-down; error-recovery flows.
- Mobile parity (dashboard badges, approval swipe/cover-letter preview); dashboard/offer countdowns; "Rejected/Withdrawn" tracking.

## Environment State
- `.env.example` present; `.env` holds `OPENROUTER_API_KEY` locally and is git-ignored (never committed).
- **OpenRouter (validated P1-env):** REACHABLE & AUTHENTICATED — key is valid. Free models are
  currently rate-limited (HTTP 429), so `scripts/validate-openrouter.mjs` treats a 429 from any
  candidate free model as a PASS (proves connectivity + auth); 401/403 would be a hard fail. The API
  key value is never logged, printed, or committed. Default light model:
  `meta-llama/llama-3.2-3b-instruct:free` (`AETHER_MODEL_LIGHT`); heavy model configurable via
  `AETHER_MODEL_HEAVY`.
- Toolchain: Node v22 / pnpm 11.9.0 / Python 3.12 locally (CI pins Node 20 + Python 3.11).
- Postgres/Redis: not running locally. Prisma work uses `prisma generate` only (no `migrate dev`);
  DB-dependent integration tests are gated on `DATABASE_URL` / `DATABASE_URL_TEST` and skipped when absent.
- Services running locally: none.
- Known flaky tests / quarantines: none.

## Next session
1. Phase 0 merged to `main` (single reviewed merge). Confirm on origin; do not re-open the phase-0 branch.
2. Open the next phase's branch **only after** this merge is on `main`.
3. Candidate next phase: Phase 0 mobile parity (P0-S11/S12) or move data-model reconciliation into Phase 1 planning.
4. Activate CI when desired: grant the GitHub App `workflows` permission, then move `ci/github-actions-ci.yml` → `.github/workflows/ci.yml` (see `ci/README.md`).
