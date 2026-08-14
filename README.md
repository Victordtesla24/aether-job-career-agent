<div align="center">

# 🔮 AETHER

### The career agent that never lies on your behalf

[![Production](https://img.shields.io/badge/Production-Live_v0.2.0-10B981?style=for-the-badge&logo=vercel&logoColor=white)](https://5cb5f0620.abacusai.cloud)
[![Agents](https://img.shields.io/badge/Agents-22_on_3_maps-4F46E5?style=for-the-badge&logo=probot&logoColor=white)](#-the-22-agent-orchestration-map)
[![Honesty](https://img.shields.io/badge/Fabrication_guard-Measured,_not_claimed-FF6B35?style=for-the-badge&logo=shieldsdotio&logoColor=white)](#-why-honesty-is-the-product)
[![Billing](https://img.shields.io/badge/Billing-Stripe_(4_tiers,_AUD)-635BFF?style=for-the-badge&logo=stripe&logoColor=white)](docs/subscription/billing-architecture.md)
[![License](https://img.shields.io/badge/License-Private-EF4444?style=for-the-badge&logo=lock&logoColor=white)]()

<br/>

*Aether discovers jobs, scores fit, tailors résumés and cover letters from your own evidence, and routes every outbound action through your approval — as a subscription web app. What makes it different is not that it writes: it's that it refuses to write anything your history doesn't support, and it can show you what it refused.*

<br/>

[Why honesty](#-why-honesty-is-the-product) · [Agent map](#-the-22-agent-orchestration-map) · [Production](#-production-status) · [Architecture](#️-architecture-as-deployed) · [Model choice](#-model-choice-per-agent-live-catalog) · [Roadmap](#️-roadmap--in-progress) · [Local dev](#-local-development)

---

</div>

## 🎯 Why honesty is the product

Every AI career tool promises to make you look better. Aether's premise is the opposite one: **the only durable advantage is that nothing it sends on your behalf can be contradicted.** An embellished bullet is not a small win — it is a landmine you carry into an interview you were not prepared to defend.

So the guarantee is not a policy paragraph. It is four mechanisms you can watch working:

**1. A fabrication guard that visibly refuses.** Résumé tailoring is content-only, and every proposed rewrite must be entailed by your own résumé and story bank. Anything unsupported is reverted rather than shipped, and the guard's verdicts are a reported metric — the compliance agent answers for a "zero unverifiable claims shipped" threshold on the orchestration map. On a real production run the guard **rejected 7 of 11 proposed rewrites**: the mechanism firing on live user data, not in a test fixture. A guard that strict means many runs show only a small ATS lift, or none. That is the honest shape of the tradeoff, and Aether states it in-product rather than burying it in an average.

**2. Résumé fidelity measured from the artifact, never asserted.** After a tailored résumé is rendered, Aether re-extracts the produced file and verifies each intended change actually survived into it. Every résumé carries a `formatFidelity` report — method, confidence, and the changes it can prove landed. A change the renderer dropped is named as dropped. The approval screen reasons from that measured report; when the report is still in flight or unavailable, it says so instead of claiming "layout preserved". *(Completeness hardening is in progress — see [Roadmap](#️-roadmap--in-progress).)*

**3. Market data cross-checked against its own source.** The Analytics "Market vs. You" rows quote live Adzuna Australia figures and cite exactly what was measured. An independent audit re-queried Adzuna directly, outside the app: the app showed **3,901 postings** (as-of 01:27:10Z) against **3,907** on a fresh independent pull ~57 minutes later — 0.15% drift, explained by a moving market inside the cache TTL — and a mean advertised salary of **A$119,711** against **A$119,668** live. The one row with no honest source stays permanently disconnected: no external interview-conversion benchmark provider exists for any market, so that row says so rather than inventing a comparison. A failed refetch is cached as *nothing*, never as the old numbers behind a fresh timestamp.

**4. A policy loop that escalates rigor when your results lag — and shows the escalation.** Aether reads your real conversion rate and fit-dimension scores and resolves a rigor tier. `heightened` is not a mood: it is **+2 tailoring iterations, +3 points of ATS target, +1 cover-letter corrective retry**, with the truthfulness guards unchanged — more effort never means looser evidence rules. The Agents console shows the current tier, the triggers that forced it, the tiers your past runs actually obeyed (read from each run's own record, not recomputed), and the interview conversion of each tier's cohort. If heightened rigor works, its cohort converts better; if it does not, that is visible too. With too few submissions to measure anything, the tier reads `insufficient_data` and runs at full standard rigor — never less.

**No outcome promises anywhere.** Aether does not predict interviews or offers, and its progress score says so in its own methodology text: it measures your submitted volume, your interview conversion and your average fit score — and a signal with no data reads "not measured" rather than counting as a zero.

## 🤖 The 22-agent orchestration map

The fleet is the product's signature, and it is deliberately **not** a black box. `/dashboard/agents` opens on an Orchestration view that draws all **22 catalog agents across three maps** — because one dense graph would misrepresent what they are:

| Map | Stages | Agents |
|---|---|---|
| **Application Pipeline** | Discovery → Fit Scoring → Tailoring → Cover Letter → Quality Gates → Submission → Tracking | 12 — the linear path one job posting travels |
| **Learning Loop** | Orchestration → Signal Capture → Learning | 4 — a *cycle* over the pipeline's outcomes; drawing it as a stage would misrepresent feedback as a step |
| **Context & Enrichment** | Market Intelligence · Employer Research · Outreach · Interview Readiness | 6 — context providers that advance no application on their own |

Each node carries its real state: last run time, a live pulse while running, the policy tier it obeyed, an honest `Last run failed` badge, and an explicit **"Planned — roadmap"** marker for catalog agents not yet wired to orchestration. The maps ship with an honesty legend naming that distinction, so a planned agent can never be mistaken for a running one.

The map renders as a semantic DOM/SVG graph **first**; a lazily-loaded three.js layer sits on top as pure enhancement (accessibility is the base, not the fallback, and the WebGL bundle is on none of the app's other routes until you open this one). Beside the maps: a live run monitor, per-agent performance panels, provider connections, and the per-agent model picker below.

## 🚦 Production Status

Live at **https://5cb5f0620.abacusai.cloud** — `{"status":"ok","version":"0.2.0"}`, verified this session. `main` is at `fab6d75` with CI green.

Since 2026-08-13 the project has run a continuous launch program: a monitoring loop over dev + production logs with every finding fixed through a thin-slice delivery pipeline, plus a day-one readiness audit whose six blockers are now closed. The ledger of record is [`uat/reports/evidence/market-perf/MONITORING-LEDGER.md`](uat/reports/evidence/market-perf/MONITORING-LEDGER.md) — every finding, its evidence, and who closed it.

**Shipped and live:**

| Capability | State | Evidence |
|---|---|---|
| **Agents console with 3 orchestration maps** — tabbed IA, live run monitor, policy panel, honesty legend, lazily-loaded WebGL layer over an always-present semantic map | Live @ `fab6d75` (deployed 2026-08-14 06:08Z); full frontend suite 1,125 tests green with zero existing test files modified | `uat/reports/evidence/market-perf/s-ui/slice1/` |
| **Rigor-policy loop** — tier resolution from real conversion + fit metrics, named triggers, tier history from each run's own record, per-tier cohort conversion | Live; the panel's `heightened` tier matched an independent SQL recompute exactly (0% conversion over 290 submissions) | `apps/api/app/services/quality_policy.py`, `uat/reports/evidence/market-perf/mon-batch-ax/` |
| **Real submission architecture (U5)** — parser-backed auto-submit for Ashby + Greenhouse; honest **assisted** click-to-send for Lever, SmartRecruiters and generic boards; terminal channels (email, Seek-manual, unknown) named as such; approval-gated throughout; approvals older than 7 days never auto-execute and require a one-click reconfirm; sweeps bounded to 10 oldest-first with an honest remaining count | Live; production DRY-RUN verified with **zero** real submissions | `apps/api/app/services/apply_channel_resolver.py`, `apps/api/app/workers/apply_sweep.py` |
| **Multi-user scheduled discovery** — every subscriber's board refreshes on the timer (not just one account), with a shared Adzuna cache, a daily API budget, and a Sync cooldown; honest degradation when the budget is spent | Live; `aether-discovery.timer` fires every 30 min | `uat/reports/evidence/market-perf/s-fix/A/` |
| **Automated DB backups with a proven restore** | Live; every 6h, first *autonomous* scheduled fire succeeded 2026-08-14 06:00:10Z. Restore drill into a scratch schema: 33/33 tables, `User` 6/6, `Application` 585/585, `Job` 9,500/9,500 — then dropped, production untouched | `uat/reports/evidence/market-perf/s-fix/C-final/RESTORE-DRILL-output.log` |
| **Pull-based auto-deploy pipeline** — polls every 5 min, health-gated with a retry deadline, refuses loudly on unexpected working-tree state, canary-verified | Live; a real timer-driven deploy passed the health gate on the exact race an earlier round exposed | `deploy/auto-deploy.sh`, `uat/reports/evidence/market-perf/u-cd/` |
| **Password reset with real email delivery** | Live; a real reset email was delivered through the configured provider (HTTP 200 from the send API), with anti-enumeration responses and rate limiting | `uat/reports/evidence/market-perf/s-fix/D/` |
| **Measured résumé fidelity** | Live — fidelity derived from the produced file and surfaced to every consumer, including the approval screen's reasoning | `apps/api/app/services/resume_format.py`, `apps/api/app/services/format_verification.py` |
| **Live market data in Analytics** — Adzuna AU postings + mean advertised salary, per-row provenance, 6h never-stale cache, fail-closed per row | Live; independently cross-checked (above) | `uat/reports/evidence/market-perf/i4/audit-d/` |
| **Async generation, quota + spend caps** — `tailor`/`coverLetter`/pipeline enqueue (202) and poll via an ARQ worker; atomic reserve-before-run, refund on failure, honest 429; mid-job cap-crossing stops honestly | Live; bounded DB pool held under a 40-request burst with zero 5xx | `docs/subscription/billing-architecture.md`, `uat/reports/evidence/market-perf/s-fix/` |
| **Per-agent live model catalog** — searchable, budget-tier-grouped picker over OpenRouter's live catalog, honest locks where an override would no-op | Live — see [Model choice](#-model-choice-per-agent-live-catalog) | `docs/subscription/model-catalog.md` |
| **Subscription billing** — 4 tiers (Free/Starter/Pro/Power) in AUD, Stripe Checkout + customer portal, transaction-safe idempotent webhook | Live and audited: Managed Payments with automatic tax, an active AU registration, all 6 prices exact to the cent across Stripe ↔ database ↔ pricing page, and an exact 8-event match between the webhook endpoint and its handler | `uat/reports/evidence/market-perf/s-pay/` |

**Test suites.** Frontend: **1,125 passed / 154 files** at the current `main` tip (2026-08-14). Backend: the closing-gate full run recorded **2,784 passed / 1 skipped** with 2 failures, which were resolved by a reviewed test-only reconciliation and a 35-test targeted proof; the gate was certified green by composition rather than by re-running an unchanged production tree. Both figures carry their date because they move every day.

**What still needs a human.** These are deliberately not automated — an agent must not fake a payment, a consent, or a legal registration:

1. **A real end-to-end purchase.** The Stripe integration is audited and coherent, but the live account has recorded **zero completed Checkouts** to date — the subscribe path (Checkout → webhook → entitlement → invoice) is unproven with real money. A dress rehearsal with the operator's card is a hard gate before wide onboarding.
2. **Stripe Dashboard branding** — logo/icon upload and brand colours; the API forbids writing an account's own branding, so this is a two-minute manual step (assets are prepared in-repo).
3. **GST/ABN representation** — the ABN is configured; the final tax-display adjudication is deferred to the real invoice produced by that first live purchase.
4. **A second Gmail consent** — exercises the multi-inbox path end-to-end.

## ✨ What Aether does

| Area | Live behaviour |
|---|---|
| **Job discovery** | Profile-driven sourcing across licensed and official ATS APIs (Adzuna AU, Greenhouse/Lever/Ashby/Workable/SmartRecruiters, Remotive/RemoteOK); per-source honest status; freshness windows; fingerprint de-duplication; an explicit "why zero" when a source returns nothing |
| **Fit scoring** | Deterministic multi-dimensional scoring per job — no LLM tokens, zero cost by design |
| **Résumé tailoring** | Content-only edits to the top-relevance bullets; JD keywords integrated only where your own evidence supports them; an entailment pass reverts anything unsupported; before/after ATS scores with a methodology tooltip; fidelity verified against the rendered file |
| **Cover letters** | Business-letter format, evidence-grounded, PDF export, approval-gated before send |
| **Applications & submission** | Parser-backed auto-submit where a real parser exists; honest assisted mode elsewhere; stale approvals expire into a reconfirm rather than firing late; every outbound action passes an explicit gate in `/dashboard/approvals` |
| **Email** | Gmail-connected triage with draft-and-approve; approving an email-channel application really sends it, and a failed send is retryable |
| **Analytics** | Melbourne-timezone bucketing on an AU-branded page; every delta declares what kind of comparison it is; live market rows with per-row provenance; unmeasured signals read "—", never 0 |
| **Billing & quota** | Monthly run quota per tier, atomic reserve-before-run, USD spend cap, honest 429 with an upgrade path |
| **Admin** | User and spend visibility, per-user spend caps, suspend, signup toggle, append-only audit log |

## 🏗️ Architecture (as deployed)

A **pnpm + Turborepo monorepo** on a single VM behind nginx — not the Kubernetes/multi-cloud topology in the original design PDFs, which remain in `docs/architecture/` as design-time reference only.

```
Browser ──▶ nginx (per-host vhost)
              ├─ /            ──▶ aether-web    (Next.js 14 App Router, systemd, :3000)
              └─ /api/*       ──▶ aether-api    (FastAPI + Uvicorn, systemd, :8000)
                                    ├─ PostgreSQL (hosted, schema "aether")
                                    ├─ aether-worker (ARQ worker, systemd — async tailor/coverLetter/pipeline/apply-sweep)
                                    ├─ Redis        (loopback-only, requirepass, logical DB 3 — ARQ queue)
                                    └─ LLM: OpenRouter (OpenAI-compatible) or a direct Anthropic credential

systemd timers
  ├─ aether-discovery.timer   every 30 min  — multi-user sourcing + fit scoring (paywall-exempt via X-Aether-System-Run)
  ├─ aether-backup.timer      every 6 h     — pg_dump → local + S3, restore-drilled
  └─ aether-autodeploy.timer  every 5 min   — pull, gate on CI + health, deploy or refuse loudly
```

- **Web:** `apps/web` — Next.js 14 (App Router, RSC), TypeScript, Tailwind. 34 routes under `/login`, `/signup`, `/pricing`, `/privacy-policy`, `/terms`, `/admin/*` and `/dashboard/*`.
- **API:** `apps/api` — FastAPI (Python 3.11+). Raw-psycopg2 data layer with a bounded pool; additive **lazy idempotent DDL** (`_ensure_*_tables` + advisory locks) — no destructive migrations. The `.sql` files under `apps/api/migrations/` are documentation mirrors.
- **Worker:** `apps/api/app/workers/` — ARQ task runner (`aether-worker.service`, `Requires=redis-server.service`) executing generation and the bounded apply sweep off the HTTP path. Quota is reserved atomically at enqueue and refunded on enqueue failure, worker failure, or a stale-job watchdog trip.
- **LLM:** OpenAI-compatible transport to OpenRouter is the default production routing; a direct Anthropic credential (Console API key, a pasted Claude Code OAuth token, or the in-app "Connect with Anthropic" PKCE OAuth flow with encrypted storage and pre-expiry refresh) is supported alongside it. Six providers can hold credentials (`anthropic`, `openrouter`, `openai`, `gemini`, `bedrock`, `groq`); a provider is reported connected only when its credential is genuinely present. **On any LLM failure the client raises an honest error and refunds quota — it never serves a fixture as real output, and a user-chosen model that fails is never silently swapped for another.**
- **Secrets:** environment variables only; credential material encrypted at rest (Fernet); nothing sensitive in process argv or logs.
- **Deploy:** unit files, the backup and auto-deploy scripts, and the nginx vhost live in-repo under `deploy/`; the newer units (`aether-backup`, `aether-autodeploy`) and the vhost are symlinked from `/etc` so their runtime setup is version-controlled, while the original `aether-api` / `aether-web` / `aether-worker` / `aether-discovery` units remain copies installed under `/etc/systemd/system`. Procedure and rollback: [`docs/delivery/DEPLOYMENT-RUNBOOK.md`](docs/delivery/DEPLOYMENT-RUNBOOK.md).

## 🧠 Model choice (per-agent, live catalog)

Every LLM-backed agent card on `/dashboard/agents` carries its own searchable, budget-tier-grouped model picker over OpenRouter's live catalog. The choice is saved **per agent**, not as one global default, and is what that agent actually runs on next time.

- **Overridable vs. fixed.** The picker renders as a functional search-and-select only for agents whose runtime resolver honours a per-agent override. Agents that make no LLM call, or run on a fixed structured tier, show an honest **"Fixed model — not user-selectable"** lock instead of a control that would silently no-op.
- **Freshness + refresh.** The catalog is fetched live and cached; every response carries `lastRefreshedAt` and a `stale` flag (true only once the cache has aged past its TTL *and* a background refresh has failed). A manual refresh endpoint forces an immediate upstream re-fetch; on upstream failure it serves the last-good list flagged `stale` rather than blocking the UI or inventing a catalog.
- **Curation.** A small, evidence-seeded denylist filters model ids proven — by a live run sweep — permanently unable to serve a chat completion for this deployment. It is a maintained list, not a heuristic: transient failures are deliberately never denylisted.
- **Validation.** Saving a model id that isn't in the live catalog returns an honest `HTTP 422` naming the problem; a cold cache accepts the id rather than blocking on a slow upstream call, and then fails honestly at run time if it was wrong.
- **Provider / billing routing.** A model id containing `/` is OpenRouter-namespaced and **always bills through OpenRouter** — including the `anthropic/*` ids OpenRouter itself serves, which do **not** reach the direct Anthropic account. A bare `claude-…` id (no slash) routes to the direct Anthropic API. The picker states this in-UI next to every model list.
- **Served-model observation.** When an upstream provider routes a request to a different model than requested, that is recorded on the run and costed against the model actually served — surfaced, never hidden.

Full behavioural reference: [`docs/subscription/model-catalog.md`](docs/subscription/model-catalog.md).

## 🛠️ Technology stack (deployed)

| Layer | Technology |
|---|---|
| **Frontend** | Next.js 14 (App Router, RSC), TypeScript, Tailwind CSS, three.js (lazily loaded, Agents console only) |
| **Backend** | FastAPI (Python 3.11+), Uvicorn |
| **Monorepo** | pnpm workspaces + Turborepo 2.x |
| **Database** | PostgreSQL (hosted), schema `aether`; embeddings stored in-table |
| **LLM** | OpenRouter (OpenAI-compatible) with a per-agent live catalog picker; direct Anthropic via API key, pasted OAuth token, or in-app PKCE OAuth |
| **Async jobs** | ARQ + Redis (loopback-only, `requirepass`, logical DB 3) |
| **Billing** | Stripe — Checkout, webhooks, customer portal, Managed Payments with automatic tax |
| **Auth / crypto** | Session JWT, bcrypt password hashing, Fernet-encrypted credentials, per-endpoint rate limiting, tokenless reset flow with anti-enumeration |
| **Sourcing** | Adzuna AU + Greenhouse/Lever/Ashby/Workable/SmartRecruiters board APIs + Remotive/RemoteOK |
| **Ops** | nginx, systemd services (`aether-api`, `aether-web`, `aether-worker`) and timers (`aether-discovery`, `aether-backup`, `aether-autodeploy`), S3 backup storage |

> The original enterprise design (LangGraph, Pinecone/Weaviate, BullMQ, EKS, Terraform, Langfuse/Grafana) lives in the architecture PDFs as reference. It is **not** the deployed stack.

## 🗺️ Roadmap — in progress

Named honestly: these are **not shipped**, and nothing above depends on them.

- **Full-app UI recreation.** The Agents console (above) was slice 1 and is live. In flight: the application shell (pinned rail, ⌘K command bar over the existing search index, system-status popover) and a Dashboard + Analytics recreation built on a hand-written SVG chart kit whose honesty laws are enforced in code — a chart that cannot distinguish a measured zero from missing data throws in development rather than rendering an ambiguous mark. Design specs and reference captures: `uat/reports/evidence/market-perf/s-ui/`.
- **Agentic runtime.** Today's agents are scripted: exactly half (10 of 20 distinct backends) make no LLM call at all, and the other half make a single fully-scripted call. The design direction on record is **one thin shared kernel** (reasoning loop, tool registry, and all guardrail enforcement — spend caps, approval gates, anti-fabrication, honesty traces) with **per-agent declarative charters** (goal, allowed tools, constraints, autonomy tier) as *data*, not code — each phase deleting the scripted path it supersedes. A blueprint exists (`uat/reports/evidence/market-perf/u-agi/`) and is explicitly design-only: no implementation has been approved or written.
- **Résumé completeness hardening.** Fidelity is measured today, but a live verification on a real baseline caught the reflow renderer dropping whole sections while the fidelity checks tracked only edits. The fix — renderer completeness plus whole-document verification — is in flight and gates closure of the résumé path.
- **Monitoring residuals.** Open, low-severity items stay listed in the ledger with their severity rather than being quietly dropped.

## 🎨 Design system

17 high-fidelity wireframes (dark, glassmorphism, coral accent `#FF6B35`) in [`design/screens/`](design/screens/) — open any `.html` in a browser — with the language spec in [`design/DESIGN.md`](design/DESIGN.md). That count is **wireframes**, deliberately smaller than the 34 live app routes: several routes (every `/admin/*` sub-page, `/login`, `/signup`) were built without a dedicated wireframe. The in-flight UI recreation above supersedes parts of this system; where they disagree, the live app is the truth.

## 🧑‍💻 Local development

```bash
# Node 20+, pnpm 11
pnpm install

# Environment: DATABASE_URL, OPENROUTER_API_KEY, AETHER_CREDENTIAL_KEY, Stripe keys, etc.
# .env.example documents most of these names; a few operational ones (e.g.
# AETHER_CREDENTIAL_KEY, AETHER_APPROVAL_MAX_AGE_DAYS) are set via the runbook instead.
cp .env.example .env

# Run the three processes production-style (each loads .env):
./start-api.sh      # uvicorn on 127.0.0.1:8000
./start-web.sh      # Next.js production build for apps/web
./start-worker.sh   # arq app.workers.settings.WorkerSettings (needs Redis)

# Monorepo tasks (turbo):
pnpm dev · pnpm build · pnpm test · pnpm lint · pnpm type-check
pnpm validate:openrouter   # sanity-check the live model catalog wiring
```

Everything degrades **honestly** without secrets: an unconfigured `STRIPE_SECRET_KEY` returns a clean 503 on checkout rather than a fabricated payment URL; with no admin credential, the panel simply has no admin; with no email provider key, password reset reports itself degraded instead of pretending to send. Reference: [`docs/delivery/DEPLOYMENT-RUNBOOK.md`](docs/delivery/DEPLOYMENT-RUNBOOK.md) and [`docs/delivery/EMAIL-SETUP.md`](docs/delivery/EMAIL-SETUP.md).

Selected environment variables beyond the core DB/LLM/Stripe/admin/Gmail set:

| Var | Purpose |
|---|---|
| `AETHER_ASYNC_GENERATION` | 202-enqueue + poll for `tailor`/`coverLetter`/pipeline instead of a blocking 200 (`true` in production) |
| `AETHER_REDIS_URL` / `AETHER_REDIS_PASSWORD` | ARQ queue backend (loopback-only) |
| `AETHER_SYSTEM_RUN_SECRET` | Shared secret for the header that lets the discovery timer bypass the paywall for `scout`/`fitScorer` only |
| `AETHER_APPROVAL_MAX_AGE_DAYS` | Age past which an approved application will not auto-submit and must be reconfirmed (default 7) |
| `AETHER_EMAIL_API_KEY` | Outbound email provider key (password reset); absent ⇒ honest degraded state |
| `ADZUNA_APP_ID` / `ADZUNA_APP_KEY` | Live market benchmarks; absent ⇒ every market row reports `connected: false` |
| `AETHER_JOB_STALE_SECONDS` | Staleness window before a polled non-terminal background job is watchdog-failed and refunded |

## 📂 Repository structure

```
aether-job-career-agent/
├── apps/
│   ├── api/        # FastAPI backend (routers, agents, services, repositories, middleware, migrations/)
│   │   └── app/workers/    # ARQ task runner + bounded apply sweep — aether-worker.service
│   └── web/        # Next.js 14 frontend (app/, components/, lib/)
├── packages/db/    # schema of record (src/schema.prisma)
├── design/         # DESIGN.md + 17 screen wireframes
├── deploy/         # systemd units, timers, nginx vhost, backup + auto-deploy scripts (symlinked into /etc)
├── docs/
│   ├── delivery/       # gate-verified delivery record, ADRs, runbook, email setup
│   ├── subscription/   # billing architecture, admin guide, model catalog, privacy policy, terms
│   ├── architecture/   # original enterprise design PDFs (reference, not the deployed topology)
│   └── growth/         # external growth-engine notes
├── assets/         # canonical résumé PDF (read-only)
├── ci/             # CI configuration
├── scripts/        # operational scripts
├── uat/            # UAT runner + reports/evidence (the evidence trees cited throughout this README)
├── start-api.sh · start-web.sh · start-worker.sh
└── turbo.json · pnpm-workspace.yaml
```

## 📜 Delivery history

Full, gate-verified history in [`docs/delivery/`](docs/delivery/) and the evidence trees under `uat/reports/evidence/`:

- **Launch program (2026-08-13 → 2026-08-14)** — continuous dev + production monitoring with every finding fixed through a thin-slice pipeline; a day-one readiness audit and the closure of all six blockers (multi-user discovery, Adzuna budget guards, DB pool, spend-cap enforcement, backups, password reset); live market data in Analytics; the real-submission architecture; the auto-deploy pipeline; the rebuilt Agents console. The record of record is the ledger: [`uat/reports/evidence/market-perf/MONITORING-LEDGER.md`](uat/reports/evidence/market-perf/MONITORING-LEDGER.md).
- **LAUNCH-READY** (2026-07-24) — [`LAUNCH-READY-FINAL-REPORT.md`](docs/delivery/LAUNCH-READY-FINAL-REPORT.md), [`LAUNCH-READY-GOVERNANCE-AUDIT.md`](docs/delivery/LAUNCH-READY-GOVERNANCE-AUDIT.md): six-workstream readiness pass, dedup, repo cleanup, quality sweep, adversarial review.
- **MODELS-LIVE** (2026-07-22) — [`MODELS-LIVE-GAPS.json`](docs/delivery/MODELS-LIVE-GAPS.json): the per-agent live model catalog, the in-app Anthropic OAuth flow, and the provider/billing-routing correctness work described above. Evidence: [`uat/reports/evidence/models-live/`](uat/reports/evidence/models-live/).
- **[`MANUAL-VERIFICATION-FINAL-REPORT.md`](docs/delivery/archive/MANUAL-VERIFICATION-FINAL-REPORT.md)** (2026-07-20) — per-wireframe human-grade testing across every screen, then adversarial re-verification: 168 findings, a closed cross-account PII-leak class, and the remediation of a production-DB-wipe incident ([`INCIDENT-PROD-DB-WIPE-2026-07-18.md`](docs/delivery/INCIDENT-PROD-DB-WIPE-2026-07-18.md) — the reason automated backups are now a shipped feature rather than a plan).
- **[`EXECUTION-REPORT.md`](docs/delivery/archive/EXECUTION-REPORT.md) §10**, **[`PHASE7-GAP-ANALYSIS.md`](docs/delivery/archive/PHASE7-GAP-ANALYSIS.md)**, **[`PHASE7-CLAIM-LEDGER.md`](docs/delivery/archive/PHASE7-CLAIM-LEDGER.md)**, **[`PHASE6-EXECUTION-SUMMARY.md`](docs/delivery/archive/PHASE6-EXECUTION-SUMMARY.md)** — prior phases, each with its own gap ledger and independent adversarial audit of the previous phase's closure claims.
- **[`DECISIONS.md`](docs/delivery/DECISIONS.md)** and the `ADR-*.md` files — architecture decision records, including the reasoning behind each honesty rule cited in this README.

<div align="center">

---

**Aether** — agents you can watch, a guard that refuses in public, and no claim it cannot show you the evidence for.

Built by [Vikram Deshpande](https://forgotten-mistory.web.app/)

</div>
