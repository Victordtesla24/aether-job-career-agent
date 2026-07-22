<div align="center">

# 🔮 AETHER

### Autonomous AI Career Agent Platform

[![Production](https://img.shields.io/badge/Production-Live-10B981?style=for-the-badge&logo=vercel&logoColor=white)](https://5cb5f0620.abacusai.cloud)
[![Design](https://img.shields.io/badge/Design_System-17_Screens-4F46E5?style=for-the-badge&logo=figma&logoColor=white)](design/DESIGN.md)
[![Billing](https://img.shields.io/badge/Billing-Stripe_(4_tiers,_AUD)-635BFF?style=for-the-badge&logo=stripe&logoColor=white)](docs/subscription/billing-architecture.md)
[![License](https://img.shields.io/badge/License-Private-EF4444?style=for-the-badge&logo=lock&logoColor=white)]()

<br/>

*An AI career agent that discovers jobs, scores fit, tailors résumés and cover letters from your own evidence, and routes everything through a human approval gate — running as a subscription web app.*

<br/>

[Production Status](#-production-status) · [Features](#-what-aether-does) · [Architecture](#️-architecture-as-deployed) · [AI Agents](#-ai-agents-runtime) · [Local Dev](#-local-development) · [Delivery History](#-delivery-history)

---

</div>

## 🎯 Vision

Aether is an **AI career assistant** that automates the repetitive, high-friction parts of a job search while keeping a human in control of anything that leaves the building:

- 🔍 **Discovers** jobs from ToS-compliant sources (licensed aggregator + official ATS APIs)
- 📊 **Evaluates** opportunities with a multi-dimensional fit-scoring engine
- 📝 **Tailors** résumés with content-only edits and an anti-fabrication entailment guard
- ✉️ **Generates** evidence-grounded cover letters in business-letter format
- ✅ **Gates** every outbound action (applications, emails) behind explicit human approval
- 🛡️ **Never fabricates** — every claim must trace to the user's résumé / story bank; if the LLM can't complete, the app returns an honest error, never canned content

## 🚦 Production Status

Aether is **live in production** at **https://5cb5f0620.abacusai.cloud** (`{"status":"ok","version":"0.2.0"}`), delivered through Phases 1–7, a per-wireframe MANUAL-VERIFICATION pass, and a subsequent **MODELS-LIVE** pass (per-agent live model choice + an in-app "Connect with Anthropic (subscription)" OAuth flow) — with gate-verified, evidence-backed QA throughout. All MODELS-LIVE code fixes are live in production as of commit `51f1ec8`; the run's own QA gates (`docs/delivery/MODELS-LIVE-GAPS.json`, `docs/delivery/MODELS-LIVE-GOVERNANCE-AUDIT.md`) track a small number of remaining LOW-severity, non-blocking documentation/UI-polish items (e.g. this SCREEN-MATRIX/runbook correction). The authoritative pre-MODELS-LIVE delivery record is [`docs/delivery/MANUAL-VERIFICATION-FINAL-REPORT.md`](docs/delivery/MANUAL-VERIFICATION-FINAL-REPORT.md) (2026-07-20); Phase-7 detail remains in [`EXECUTION-REPORT.md`](docs/delivery/EXECUTION-REPORT.md) §10 and the machine ledger [`phase7-gap-analysis.json`](docs/delivery/phase7-gap-analysis.json); Phase-6 detail remains in [`PHASE6-EXECUTION-SUMMARY.md`](docs/delivery/PHASE6-EXECUTION-SUMMARY.md).

**Latest verification (2026-07-20, MANUAL-VERIFICATION run, commit `54c28e5`):** full regression suite green — backend **967 passed / 0 failed** (serialized, `-p no:xdist`) and frontend **477 passed / 0 failed** (vitest). Production DB holds exactly the **2 legitimate accounts** (`admin@aether.local`, demoted, `isAdmin:false`; and the owner/demo account) — both were restored via the app's own seed path after a since-remediated test-suite incident wiped production data (`docs/delivery/INCIDENT-PROD-DB-WIPE-2026-07-18.md`). `aether-discovery.timer` fires every 30 minutes with honest ISO-timestamped logging (scout succeeds; fit-scorer honestly refuses with HTTP 422 until the demo account has a résumé — never a fabricated result). Full record, including a closed cross-account PII-leak class and a "UI facade" defect sweep across all 29 screens: [`docs/delivery/MANUAL-VERIFICATION-FINAL-REPORT.md`](docs/delivery/MANUAL-VERIFICATION-FINAL-REPORT.md) — 168 findings filed, 129 VERIFIED-CLOSED on production, 28 accepted-deviations, 8 blocked on operator action, 0 open.

**Shipped and verified on production:**

| Capability | State | Evidence |
|---|---|---|
| **Subscription billing** — 4 tiers (Free/Starter/Pro/Power), GST-inclusive AUD pricing, Stripe Checkout + transaction-safe idempotent webhook + customer portal, `/pricing` page | Built + unit-tested (mocked Stripe); live payment round-trip **pending operator Stripe keys** | `docs/subscription/billing-architecture.md`, `uat/reports/evidence/phase6/review-billing.json` |
| **Admin panel (Tier 1)** — users + USD spend, per-user spend-cap, suspend/unsuspend, signup toggle, append-only audit log, health | Built + production-flow-verified (spend-cap-before-LLM proven live via a temporary admin, then removed); **formal closure pending operator admin credential** | `docs/subscription/admin-guide.md`, `uat/reports/evidence/phase6/qa-prod-console-admin.json` |
| **Quota / spend-cap enforcement** — atomic reserve-before-run (sync) / reserve-at-enqueue (async), refund-on-failure, honest HTTP 429 | Live | `uat/reports/evidence/phase6/review-billing.json`, `uat/reports/evidence/phase7/journey-j3-quota-refund.json` |
| **ToS-compliant job sourcing** — Seek scraping removed; volume from Adzuna AU (licensed API) + Greenhouse/Lever/Ashby/Workable + Remotive/RemoteOK, per-source honest status, freshness + dedup | Live: 33 jobs / 5 sources (3 sources ≥5 each), 0% stale (>30d), 0 Seek, 0 duplicate `sourceUrl`s | `uat/reports/evidence/phase7/journey-j5-sourcing.json`, `step10-cluster2-gates.json` |
| **Evidence-grounded tailoring + cover letters** — entailment verification, zero fabrication survivors, content-only edits; business-format cover letters with approval gate | Live-verified, zero fabrication survivors across all sampled completions. A genuine ATS-score lift (30.81→32.97) was captured once live; **honest note:** the conservative entailment guard rejects most proposed rewrites when they lack evidence, so ≈14/19 recently sampled live tailoring runs show +0.0% lift and 2/19 show the +0.2% lift — the lift figure is a real, non-fabricated, one-time proof of the mechanism working, not the typical outcome of every run | `uat/reports/evidence/phase6/qa-prod-craft5.json`, `uat/reports/evidence/phase7/probe-p7-07a-ats-metrics.json` |
| **Multi-Gmail inbox** — per-account tokens, `prompt=select_account`, unified + filtered views | Built + code-verified; full 2-account round-trip **pending a 2nd Gmail consent** | `uat/reports/evidence/phase6/qa-E-verification.json` |
| **Dual-mode Anthropic credential** — Console API key or a pasted Claude Code OAuth token (`claude setup-token` output) as the platform's/a user's own Anthropic credential | Live-verified: real `sk-ant-oat01-` token round-tripped through a genuine Anthropic API call; billing audit records `authMode=oauth_token` on a live run | `docs/subscription/billing-architecture.md`, `uat/reports/evidence/phase7/step10-cluster1-gates.json` |
| **Connect with Anthropic (subscription)** — in-app OAuth: click a button, Anthropic's own authorize page opens in a new tab, paste back the one-time code, the server exchanges it (PKCE) and stores the access + refresh token encrypted; auto-refreshes before expiry; an honest `needs_reauth` state + "Renew now" / "Connect with Anthropic" affordance on refresh failure (never a stale token, never a silent fallback). A manual API-key / OAuth-token paste remains as a fallback. | Live: real authorize URL + code/state exchange/refresh cycle verified against production | `apps/api/app/services/anthropic_oauth.py`, `docs/delivery/MODELS-LIVE-GOVERNANCE-AUDIT.md` (ADR-ML-1/2/2a/5), `uat/reports/evidence/models-live/catalog/ML-agents-cred-002-live-mechanics.md` |
| **Per-agent live model catalog** — every LLM-backed agent card on `/dashboard/agents` has its own searchable, budget-tier-grouped picker over OpenRouter's live catalog (hundreds of models, count varies with upstream churn); the picked model persists per-agent and is honoured at run time for the REASONING-tier agents (`resumeTailoring`/`tailor`, `coverLetter`, `emailAgent`); the STRUCTURED-tier `storyExtraction` agent and all deterministic agents (scout/fitScorer/matcher/supervisor) show an honest "fixed model — not user-selectable" lock instead of a picker that would silently no-op | Live: fresh pull returned 357 models (2026-07-22T23:06:57Z, this task); prior sweeps recorded 337/335 — the count moves with OpenRouter's own catalog, by design | `uat/reports/evidence/models-live/models/CATALOG-SWEEP.md`, `STAGE3-CATALOG-RESAMPLE.md`, `RUN-SWEEP.md`, `NO-SUBSTITUTION-PROOF.md`, `docs/subscription/model-catalog.md` |
| **Async background generation** — `tailor`/`coverLetter`/pipeline runs enqueue (202) and poll (`GET /api/agents/jobs/{job_id}`) via an ARQ/Redis worker instead of blocking the HTTP request | Live: `AETHER_ASYNC_GENERATION=true` in production; 20/20-run soak, 0 HTTP 503s | `uat/reports/evidence/phase7/journey-j3-soak-20.json` |

**Pending operator action** (human-gated — code is built and tested, but the live round-trip requires secrets/consents an agent must not fake). Full checklist: [`docs/delivery/PHASE7-BLOCKED-ON-HUMAN.md`](docs/delivery/PHASE7-BLOCKED-ON-HUMAN.md) (supersedes the Phase-6 checklist):

1. **Stripe** test-mode keys (`STRIPE_SECRET_KEY`, webhook signing secret, 6 Price IDs) + ABN/Stripe Tax → live checkout → webhook → entitlement.
2. **Admin credential** (`AETHER_ADMIN_EMAIL` + bcrypt `AETHER_ADMIN_PASSWORD_HASH`) → formally closes the admin gate. The demo `admin/admin123` account already carries **zero** admin privilege in production.
3. **Second Gmail OAuth consent** → exercises multi-inbox end-to-end.
4. **Adzuna AU API credentials** (`ADZUNA_APP_ID`/`ADZUNA_APP_KEY`) — optional; the sourcing floor is already met without them.

The operator's own Claude Code OAuth token (`sk-ant-oat01-…`) is **already configured and live** — no action needed for that item.

**Known non-blocking residual (Phase 6) — RESOLVED in Phase 7:** LLM generation used to be synchronous under a ~100s HTTP edge, surfacing an honest HTTP 503 in roughly 20% of attempts (`BACKLOG-P6-02`). Async background generation (above) eliminates this: generation now runs on a separate `aether-worker` process and the HTTP request only enqueues + polls.

## ✨ What Aether Does

| Area | Live behaviour |
|---|---|
| **Job discovery** | Profile-driven sourcing across licensed/ATS APIs; per-source sync status; freshness ≤30d; fingerprint de-duplication; honest "why zero" surfacing |
| **Fit scoring** | Deterministic multi-dimensional scoring per job (non-LLM, zero-token by design) |
| **Résumé tailoring** | Content-only edits to the top-relevance bullets; JD-keyword integration only where the user's own evidence supports it; an entailment pass reverts any unsupported claim; before/after ATS scores shown with a methodology tooltip |
| **Cover letters** | Business-letter format (sender/date/recipient/salutation/3 paragraphs/CTA/sign-off); evidence-grounded; clean PDF export; approval-gated before send |
| **Applications & email** | Application tracker; Gmail-connected email triage with draft-and-approve; every outbound action passes an explicit approval item in `/dashboard/approvals` |
| **Billing & quota** | Monthly agent-run quota per tier; atomic reserve-before-run; USD spend cap; honest 429 + upgrade CTA at exhaustion |
| **Admin** | User/spend visibility (USD), spend caps, suspend, signup toggle, append-only audit log |

## 🏗️ Architecture (as deployed)

Aether runs as a **pnpm + Turborepo monorepo** on a single VM behind nginx — not the Kubernetes/multi-cloud topology in the original enterprise design PDFs (those remain in `docs/architecture/` as design-time reference, not a description of the live system).

```
Browser ──▶ nginx (per-host vhost)
              ├─ /            ──▶ aether-web    (Next.js 14 App Router, systemd, :3000)
              └─ /api/*       ──▶ aether-api    (FastAPI + Uvicorn, systemd, :8000)
                                    ├─ PostgreSQL (hosted, schema "aether")
                                    ├─ LLM via OpenRouter (OpenAI-compatible; deepseek / qwen)
                                    │  or a dual-mode Anthropic credential (Console API key / Claude Code OAuth token)
                                    ├─ aether-worker  (ARQ worker, systemd; async tailor/coverLetter/pipeline)
                                    ├─ Redis          (loopback-only, requirepass, logical DB 3 — ARQ queue backend)
                                    └─ aether-discovery.timer (scheduled sourcing, every 30 min; paywall-exempt via X-Aether-System-Run)
```

- **Web:** `apps/web` — Next.js 14 (App Router, RSC), TypeScript, Tailwind. Routes: `/login`, `/signup`, `/pricing`, `/privacy-policy`, `/terms`, `/admin/*`, and `/dashboard/*` (jobs, applications, resume, cover-letters, email, interviews, networking, offers, analytics, agents, stories, approvals, settings).
- **API:** `apps/api` — FastAPI (Python 3.11+). Raw-psycopg2 data layer; additive **lazy idempotent DDL** (`_ensure_*_tables` + advisory locks) — no destructive migrations; `.sql` files under `apps/api/migrations/` are documentation mirrors.
- **Worker:** `apps/api/app/workers/` — an ARQ task runner (`aether-worker.service`, `Requires=redis-server.service`) that executes `tailor`/`coverLetter`/pipeline generation off the HTTP request path when `AETHER_ASYNC_GENERATION=true` (production default since Phase 7). Jobs live in the additive `BackgroundJob` table; quota is reserved atomically at enqueue and refunded on enqueue failure, worker failure, or a stale-job watchdog trip. See `docs/subscription/billing-architecture.md` §4.4.
- **LLM:** OpenAI-compatible transport to OpenRouter (`AETHER_LLM_MODE=auto`) is the default production routing for plan-tier billing. On top of that, every LLM-backed agent (`tailor`, `coverLetter`, `emailAgent`) has a **per-agent live model picker** (§ AI Agents below) drawing on OpenRouter's full catalog. Separately, the Anthropic provider-credential endpoints accept a **dual-mode manual credential**: a Claude Console API key (`sk-ant-api…`) or a pasted Claude Code OAuth token (`sk-ant-oat01-…`, the output of running `claude setup-token`; `ADR-P7-01`). **In addition**, an in-app **"Connect with Anthropic (subscription)" OAuth flow** is now built and live (`ML-agents-cred-002`, `ADR-ML-1/2/2a/5` in `docs/delivery/MODELS-LIVE-GOVERNANCE-AUDIT.md`) — a compliant re-authoring, distinct from the interactive-consent flow Phase 6 found ToS-prohibited (`ADR-P6-OAUTH`) and removed: clicking "Connect with Anthropic" opens **Anthropic's own** authorize page in a new tab; the operator approves and pastes back a one-time `code#state`; the server exchanges it (PKCE, `platform.claude.com/v1/oauth/token`) and stores the access + refresh token encrypted; the access token auto-refreshes ~5 minutes before expiry; a failed refresh marks the credential `needs_reauth` and the UI shows an honest "Renew now" / reconnect affordance rather than silently reusing a stale token. The manual API-key/OAuth-token paste stays available as a fallback. On any LLM call failure the client raises an honest error and refunds quota — it never serves a fixture as real output, and a user-chosen model that fails is never silently substituted with a different one (`ADR-ML-3`).
- **Secrets:** all via environment variables; OAuth/credential material encrypted at rest (Fernet); a saved `oauth_token`-mode Anthropic credential is additionally synced (atomic, 0600, never logged) to the repo-root `.env` as `CLAUDE_CODE_OAUTH_TOKEN` so the worker process can read it too.

## 🤖 AI Agents (runtime)

**8 agents actually execute in production** (confirmed via `GET /api/agents`; `uat/reports/evidence/phase6/probe-16-agent-keys.json`):

| Agent | Kind | Role |
|---|---|---|
| `supervisor` | orchestration | Plans and sequences a pipeline run |
| `scout` | deterministic | Multi-source job discovery (no LLM tokens by design) |
| `matcher` | deterministic | Job↔profile matching |
| `fitScorer` | deterministic | Multi-dimensional fit scoring |
| `tailor` | LLM | Content-only résumé tailoring + entailment anti-fabrication |
| `coverLetter` | LLM | Business-format, evidence-grounded cover letters |
| `storyExtractor` | LLM | STAR+R story/achievement extraction |
| `emailAgent` | LLM | Gmail triage + draft-and-approve |

The `AgentConfig` table holds **22 configured agent keys** — a superset of the 8 runtime agents plus disabled/catalog entries reserved for future enablement without a schema change. Only the 8 above are wired to orchestration and run today. (LLM agents record real token counts and USD cost; deterministic agents are correctly zero-cost.)

### Model choice (per-agent, live OpenRouter catalog)

Every LLM-backed agent card on `/dashboard/agents` (`resumeTailoring`→`tailor`, `coverLetter`, `emailAgent`) carries its own searchable, budget-tier-grouped model picker (`AgentModelPicker.tsx`) over `GET /api/agents/providers/openrouter/models`. The choice is saved per-agent (`PUT /api/agents/config/{agentKey}`), not as one global default, and is what the agent actually runs on the next time it executes.

- **Overridable vs. fixed:** the picker is only rendered as a functional search+select for agents on the `REASONING` LLM tier (`tailor`, `coverLetter`, `emailAgent`) — the only tier the run-time model resolver (`_model_overridable` / `_USER_OVERRIDABLE_TIERS`) honours a per-agent override for. `storyExtraction` runs on the `STRUCTURED` tier and deterministic agents (`scout`/`fitScorer`/`matcher`/`supervisor`) make no LLM call at all — both show an honest **"Fixed model — not user-selectable"** lock instead of a picker that would silently no-op.
- **Freshness + refresh:** the OpenRouter catalog is fetched live and cached for up to 1 hour (`_MODEL_CATALOG_TTL`); every catalog response carries `lastRefreshedAt` (ISO-8601) and `stale` (true only once the cache has aged past the TTL and a background refresh attempt has failed). `POST /api/agents/providers/{provider}/models/refresh` forces an immediate upstream re-fetch; on an upstream failure it still serves the last-good cached list (flagged `stale: true`) rather than blocking the UI or fabricating a catalog.
- **Curation (proven-broken denylist):** 5 exact model ids proven — via a live 82-model run sweep, `uat/reports/evidence/models-live/models/RUN-SWEEP.md` — to be permanently unable to serve a chat completion for this deployment's key (2× no-endpoint 404, 3× structurally non-chat apply/diff/deep-research endpoints) are filtered out of the picker by exact-id match (`_OPENROUTER_PROVEN_BROKEN_IDS`, `ADR-ML-4`). This is a maintained denylist seeded from evidence, not a heuristic filter — OpenRouter's `/models` payload carries no availability signal, and a heuristic (e.g. "no `temperature` param") would also hide 50+ working Anthropic-via-OpenRouter models. Transient failures (rate-limits, timeouts) are deliberately **not** denylisted.
- **Validation:** `PUT /api/agents/config/{agentKey}` rejects a model id that isn't in the live OpenRouter catalog with an honest `HTTP 422` (`model '<id>' is not in the live openrouter catalog — choose one from the catalog.`); a cold/unwarmed cache accepts the id rather than blocking on a slow upstream call (it then fails honestly at run time if wrong — never a silent substitution).
- **Provider / billing routing:** a model id containing a `/` (e.g. `deepseek/deepseek-v4-flash`, or OpenRouter's own `anthropic/claude-3-haiku`) is OpenRouter-namespaced and **always bills through OpenRouter** — including the `anthropic/*` ids OpenRouter itself serves, which do **not** route to the direct Anthropic API. A bare id starting with `claude-` or `anthropic` (no slash) routes to the **direct Anthropic API** instead (`resolve_provider`, `apps/api/app/services/llm_client.py`). The picker states this routing implication in-UI next to every agent's model list.
- **No silent substitution:** when a user-chosen model fails at run time, the run fails honestly (quota refunded) — it is never silently replaced with a different model and reported as success (`ADR-ML-3`, proven live in `uat/reports/evidence/models-live/models/NO-SUBSTITUTION-PROOF.md`).

Full behavioural reference: [`docs/subscription/model-catalog.md`](docs/subscription/model-catalog.md).

## 🛠️ Technology Stack (deployed)

| Layer | Technology |
|---|---|
| **Frontend** | Next.js 14 (App Router, RSC), TypeScript, Tailwind CSS |
| **Backend** | FastAPI (Python 3.11+), Uvicorn |
| **Monorepo** | pnpm workspaces + Turborepo (`tasks` config, Turborepo 2.x) |
| **Database** | PostgreSQL (hosted), schema `aether`; pgvector-style embeddings stored in-table |
| **LLM** | OpenRouter (OpenAI-compatible), `auto` mode with model fallback + honest failure; per-agent live model catalog picker (hundreds of curated OpenRouter models, 1h cache + manual refresh); Anthropic via a manual dual-mode credential (Console API key or Claude Code OAuth token) **or** the in-app "Connect with Anthropic (subscription)" OAuth flow — both available via the agent-provider settings |
| **Async jobs** | ARQ (task runner) + Redis (loopback-only, `requirepass`, logical DB 3) — background `tailor`/`coverLetter`/pipeline generation |
| **Billing** | Stripe (Checkout, webhooks, customer portal), Stripe Tax optional |
| **Auth / crypto** | Session JWT, bcrypt password hashing, Fernet-encrypted credentials, per-endpoint rate limiting |
| **Sourcing** | Adzuna AU API + Greenhouse/Lever/Ashby/Workable board APIs + Remotive/RemoteOK |
| **Serving** | nginx reverse proxy, systemd units (`aether-api`, `aether-web`, `aether-worker`, `aether-discovery.timer`) on a single VM |
| **PDF** | Server-side résumé/cover-letter PDF generation |

> The original enterprise design (LangGraph, Pinecone/Weaviate, Redis/BullMQ, AWS EKS, Terraform, Langfuse/Grafana) lives in the architecture PDFs as reference; it is **not** the deployed stack.

## 🎨 Design System — 17 Screens

**17 high-fidelity screens** (dark mode, glassmorphism, coral accent `#FF6B35`), all built and live under `/dashboard/*`, `/admin`, and `/pricing`. The source wireframes are in [`design/screens/`](design/screens/) (open any `.html` in a browser); the design language spec is [`design/DESIGN.md`](design/DESIGN.md).

Dashboard, Job Discovery, Résumé Studio, Story Bank, Application Tracker, Interview Center, Networking & CRM, Email Center, Manage Agents, Agent Monitor, Analytics, Offer Comparison, Settings, Approval Modal, Cover Letter Studio, Mobile Dashboard, Mobile Approval.

## 🧑‍💻 Local Development

```bash
# Install dependencies (Node 20+, pnpm)
pnpm install

# Copy and fill in environment variables (see .env for the full name list —
# DATABASE_URL, OPENROUTER_API_KEY, AETHER_LLM_MODE, AETHER_CREDENTIAL_KEY, Stripe keys, etc.)
cp .env.example .env   # if present; otherwise seed from the DEPLOYMENT-RUNBOOK reference

# Run API (FastAPI), web (Next.js), and the async worker — production-style:
./start-api.sh    # loads .env, uvicorn on 127.0.0.1:8000
./start-web.sh    # loads .env, Next.js production build for apps/web
./start-worker.sh # loads .env, arq app.workers.settings.WorkerSettings (needs Redis running)

# Iterative development across the monorepo:
pnpm dev · pnpm test · pnpm lint · pnpm type-check   # (turbo)
```

Billing and admin degrade **honestly** without secrets — an unconfigured `STRIPE_SECRET_KEY` returns a clean HTTP 503 on checkout (never a fabricated payment URL); with no admin credential set, the panel simply has no admin. Full env reference and the exact production deploy/rollback procedure: [`docs/delivery/DEPLOYMENT-RUNBOOK.md`](docs/delivery/DEPLOYMENT-RUNBOOK.md).

**Phase-7 environment variables** (in addition to the Phase-6 set — DB/LLM/Stripe/admin/Gmail — documented in the runbook):

| Var | Purpose | Default |
|---|---|---|
| `CLAUDE_CODE_OAUTH_TOKEN` | Anthropic `oauth_token`-mode credential (`sk-ant-oat01-…`), auto-synced when saved via the agent-provider settings — do not hand-edit | (none) |
| `AETHER_ALLOWED_INTERNAL_EMAIL_DOMAINS` | Comma-separated exact-domain allowlist for the settings-email validator (subdomains are still rejected) | `aether.local` |
| `AETHER_REDIS_URL` | ARQ/Redis connection string for the async worker queue | `redis://127.0.0.1:6379/3` |
| `AETHER_REDIS_PASSWORD` | Redis `requirepass` value (loopback-only bind) | (none) |
| `AETHER_ASYNC_GENERATION` | Enables 202-enqueue + poll for `tailor`/`coverLetter`/pipeline instead of synchronous 200 | `false` (`true` in production) |
| `AETHER_LLM_WORKER_BUDGET_SECONDS` / `AETHER_LLM_WORKER_COVER_BUDGET_SECONDS` / `AETHER_LLM_WORKER_PIPELINE_BUDGET_SECONDS` | Per-call LLM time budgets inside the worker (no HTTP-edge timeout to respect there) | `300` |
| `AETHER_SYSTEM_RUN_SECRET` | Shared secret for the `X-Aether-System-Run` header that lets `aether-discovery.timer` bypass the paywall for `scout`/`fitScorer` only | (none — disabled when unset) |
| `AETHER_JOB_STALE_SECONDS` | Staleness window before a polled, non-terminal `BackgroundJob` is watchdog-failed + refunded | `900` |

## 📂 Repository Structure

```
aether-job-career-agent/
├── apps/
│   ├── api/        # FastAPI backend (routers, agents, services, repositories, middleware, migrations/)
│   │   └── app/workers/  # ARQ async task runner (tasks.py, queue.py, settings.py) — aether-worker.service
│   └── web/        # Next.js 14 frontend (app/, components/, lib/)
├── packages/       # shared workspace packages (agents, db, queue, shared)
├── design/         # DESIGN.md + 17 screen wireframes (design/screens/)
├── docs/
│   ├── delivery/       # gate-verified delivery record (PHASE*-*, gap ledgers, runbook, governance audit)
│   ├── subscription/   # billing-architecture, admin-guide, model-catalog, privacy-policy, terms-of-service
│   ├── architecture/   # original enterprise design PDFs (reference, not the deployed topology)
│   └── research/        # market/competitive research (historical)
├── assets/resume/  # canonical résumé PDF (read-only)
├── ci/             # CI configuration
├── scripts/        # operational scripts
├── uat/            # UAT runner + reports/evidence
├── start-api.sh · start-web.sh · start-worker.sh   # systemd entrypoints
├── turbo.json · pnpm-workspace.yaml
└── docs/delivery/EXECUTION-REPORT.md   # (root EXECUTION-REPORT.md is a pointer stub)
```

## 📜 Delivery History

The full, gate-verified delivery history lives in [`docs/delivery/`](docs/delivery/):
- **MODELS-LIVE** (`MODELS-LIVE-GAPS.json`, `MODELS-LIVE-GOVERNANCE-AUDIT.md`) — latest run (2026-07-22, all code fixes live @ commit `51f1ec8`): per-agent live OpenRouter model catalog picker (searchable, budget-tier grouped, freshness + manual refresh, proven-broken denylist, 422 validation, no-silent-substitution); the in-app "Connect with Anthropic (subscription)" OAuth flow (`ML-agents-cred-002`); billing/provider-routing correctness (`resolve_provider`); 46 findings tracked (36 VERIFIED-CLOSED, 4 OPEN — all LOW severity: 3 documentation-accuracy items addressed by this refresh — `ML-runbook-001`, `ML-admindetail-002`, `ML-forgotpw-001` — plus 1 known-environmental shared-test-DB flakiness note, `ML-env-001`, not a code defect). Evidence root: `uat/reports/evidence/models-live/`.
- **[`MANUAL-VERIFICATION-FINAL-REPORT.md`](docs/delivery/MANUAL-VERIFICATION-FINAL-REPORT.md)** — prior run (2026-07-20): per-wireframe human-grade manual testing across all 29 screens → fix → adversarial re-verify. 168 findings (129 VERIFIED-CLOSED / 28 accepted-deviation / 8 blocked-on-human / 3 other, 0 open); closed a cross-account PII-leak class (9 agent paths grounded on the caller's own résumé, not a fixed operator résumé); survived and remediated a production-DB-wipe incident (`INCIDENT-PROD-DB-WIPE-2026-07-18.md`) including seed-account + discovery-cron restoration; eliminated dead buttons/client-only fakes/false-success notices across the UI. Governance: `MANUAL-VERIFICATION-GOVERNANCE-AUDIT.md` (14 entries, 0 self-approvals). Claim ledger: `MANUAL-VERIFICATION-CLAIM-LEDGER.md`.
- **[`EXECUTION-REPORT.md`](docs/delivery/EXECUTION-REPORT.md) §10** — prior run (Phase 7): dual-mode Anthropic credential, settings-email allowlist + persistence fix, async background generation, discovery paywall bypass.
- **[`PHASE7-GAP-ANALYSIS.md`](docs/delivery/PHASE7-GAP-ANALYSIS.md)** + `phase7-gap-analysis.json` — per-gap records with production evidence.
- **[`PHASE7-CLAIM-LEDGER.md`](docs/delivery/PHASE7-CLAIM-LEDGER.md)** — independent adversarial audit of every Phase-6 closure claim against fresh Phase-7 evidence.
- **[`PHASE7-BLOCKED-ON-HUMAN.md`](docs/delivery/PHASE7-BLOCKED-ON-HUMAN.md)** — current operator steps to go fully live (supersedes the Phase-6 checklist).
- **[`PHASE6-EXECUTION-SUMMARY.md`](docs/delivery/PHASE6-EXECUTION-SUMMARY.md)** — prior run: subscription/billing, admin panel, ToS-compliant sourcing, evidence-grounded quality; 34-gate adjudication.
- **[`DECISIONS.md`](docs/delivery/DECISIONS.md)** — architecture decision records (ADRs) through Phase 6 (e.g. `ADR-P6-OAUTH`, `ADR-P6-PRICING`); Phase-7 rulings (`ADR-P7-01` dual-mode Anthropic credential override, `ADR-P7-05` discovery paywall bypass) are recorded in the **Rulings** table of [`PHASE7-GAP-ANALYSIS.md`](docs/delivery/PHASE7-GAP-ANALYSIS.md), not yet folded into `DECISIONS.md`.
- Per-phase reports for Phases 0–6 are retained as dated historical records.

<div align="center">

---

**Aether** — an AI career agent with a human approval gate and an anti-fabrication guarantee.

Built by [Vikram Deshpande](https://forgotten-mistory.web.app/)

</div>
