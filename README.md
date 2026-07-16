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

Aether is **live in production** at **https://5cb5f0620.abacusai.cloud** (`{"status":"ok","version":"0.2.0"}`), delivered through Phases 1–6 with gate-verified, evidence-backed QA. The authoritative delivery record is in [`docs/delivery/`](docs/delivery/) — start with [`PHASE6-EXECUTION-SUMMARY.md`](docs/delivery/PHASE6-EXECUTION-SUMMARY.md) and the machine ledger [`phase6-gap-analysis.json`](docs/delivery/phase6-gap-analysis.json).

**Shipped and verified on production:**

| Capability | State | Evidence |
|---|---|---|
| **Subscription billing** — 4 tiers (Free/Starter/Pro/Power), GST-inclusive AUD pricing, Stripe Checkout + transaction-safe idempotent webhook + customer portal, `/pricing` page | Built + unit-tested (mocked Stripe); live payment round-trip **pending operator Stripe keys** | `docs/subscription/billing-architecture.md`, `uat/reports/evidence/phase6/review-billing.json` |
| **Admin panel (Tier 1)** — users + USD spend, per-user spend-cap, suspend/unsuspend, signup toggle, append-only audit log, health | Built + production-flow-verified (spend-cap-before-LLM proven live via a temporary admin, then removed); **formal closure pending operator admin credential** | `docs/subscription/admin-guide.md`, `uat/reports/evidence/phase6/qa-prod-console-admin.json` |
| **Quota / spend-cap enforcement** — atomic reserve-before-run, refund-on-failure, honest HTTP 429 | Live | `uat/reports/evidence/phase6/review-billing.json` |
| **ToS-compliant job sourcing** — Seek scraping removed; volume from Adzuna AU (licensed API) + Greenhouse/Lever/Ashby/Workable + Remotive/RemoteOK, per-source honest status, freshness + dedup | Live: 30 jobs / 3 sources ≥5, 100% fresh ≤30d, 0 Seek, 0 duplicates | `uat/reports/evidence/phase6/qa-prod-sourcing.json` |
| **Evidence-grounded tailoring + cover letters** — entailment verification, zero fabrication survivors, content-only edits, genuine ATS lift; business-format cover letters with approval gate | Live-verified (strict ATS lift 30.81→32.97; cover craft 78/100, zero fabrication) | `uat/reports/evidence/phase6/qa-prod-craft5.json`, `qa-cov2-ui1-verify.json` |
| **Multi-Gmail inbox** — per-account tokens, `prompt=select_account`, unified + filtered views | Built + code-verified; full 2-account round-trip **pending a 2nd Gmail consent** | `uat/reports/evidence/phase6/qa-E-verification.json` |

**Pending operator action** (human-gated — code is built and tested, but the live round-trip requires secrets/consents an agent must not fake). Full checklist: [`docs/delivery/PHASE6-BLOCKED-ON-HUMAN.md`](docs/delivery/PHASE6-BLOCKED-ON-HUMAN.md):

1. **Stripe** test-mode keys (`STRIPE_SECRET_KEY`, webhook signing secret, 6 Price IDs) + ABN/Stripe Tax → live checkout → webhook → entitlement.
2. **Admin credential** (`AETHER_ADMIN_EMAIL` + bcrypt `AETHER_ADMIN_PASSWORD_HASH`) → formally closes the admin gate. The demo `admin/admin123` account already carries **zero** admin privilege in production.
3. **Second Gmail OAuth consent** → exercises multi-inbox end-to-end.

**Known non-blocking residuals:** LLM generation is synchronous under a ~100s HTTP edge, so slow calls surface an honest HTTP 503 (never a fabricated fallback) in roughly 20% of attempts, and the "run everything" `/pipeline/run` endpoint can hit the edge — the durable fix is asynchronous generation (`BACKLOG-P6-02`). Individual tailor and cover-letter runs complete reliably.

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
              ├─ /            ──▶ aether-web   (Next.js 14 App Router, systemd, :3000)
              └─ /api/*       ──▶ aether-api   (FastAPI + Uvicorn, systemd, :8000)
                                    ├─ PostgreSQL (hosted, schema "aether")
                                    ├─ LLM via OpenRouter (OpenAI-compatible; deepseek / qwen)
                                    └─ aether-discovery.timer (scheduled sourcing, every 30 min)
```

- **Web:** `apps/web` — Next.js 14 (App Router, RSC), TypeScript, Tailwind. Routes: `/login`, `/signup`, `/pricing`, `/privacy-policy`, `/terms`, `/admin/*`, and `/dashboard/*` (jobs, applications, resume, cover-letters, email, interviews, networking, offers, analytics, agents, stories, approvals, settings).
- **API:** `apps/api` — FastAPI (Python 3.11+). Raw-psycopg2 data layer; additive **lazy idempotent DDL** (`_ensure_*_tables` + advisory locks) — no destructive migrations; `.sql` files under `apps/api/migrations/` are documentation mirrors.
- **LLM:** OpenAI-compatible transport to OpenRouter (`AETHER_LLM_MODE=auto`). Model names in agent config are semantic; there is **no direct Anthropic API/OAuth** connection (third-party Anthropic subscription OAuth is ToS-prohibited — see `ADR-P6-OAUTH` in `docs/delivery/DECISIONS.md`). On failure the client raises an honest error and refunds quota — it never serves a fixture as real output.
- **Secrets:** all via environment variables; OAuth/credential material encrypted at rest (Fernet).

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

## 🛠️ Technology Stack (deployed)

| Layer | Technology |
|---|---|
| **Frontend** | Next.js 14 (App Router, RSC), TypeScript, Tailwind CSS |
| **Backend** | FastAPI (Python 3.11+), Uvicorn |
| **Monorepo** | pnpm workspaces + Turborepo (`tasks` config, Turborepo 2.x) |
| **Database** | PostgreSQL (hosted), schema `aether`; pgvector-style embeddings stored in-table |
| **LLM** | OpenRouter (OpenAI-compatible), `auto` mode with model fallback + honest failure |
| **Billing** | Stripe (Checkout, webhooks, customer portal), Stripe Tax optional |
| **Auth / crypto** | Session JWT, bcrypt password hashing, Fernet-encrypted credentials, per-endpoint rate limiting |
| **Sourcing** | Adzuna AU API + Greenhouse/Lever/Ashby/Workable board APIs + Remotive/RemoteOK |
| **Serving** | nginx reverse proxy, systemd units (`aether-api`, `aether-web`, `aether-discovery.timer`) on a single VM |
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

# Run API (FastAPI) and web (Next.js) — production-style:
./start-api.sh   # loads .env, uvicorn on 127.0.0.1:8000
./start-web.sh   # loads .env, Next.js production build for apps/web

# Iterative development across the monorepo:
pnpm dev · pnpm test · pnpm lint · pnpm type-check   # (turbo)
```

Billing and admin degrade **honestly** without secrets — an unconfigured `STRIPE_SECRET_KEY` returns a clean HTTP 503 on checkout (never a fabricated payment URL); with no admin credential set, the panel simply has no admin. Full env reference and the exact production deploy/rollback procedure: [`docs/delivery/DEPLOYMENT-RUNBOOK.md`](docs/delivery/DEPLOYMENT-RUNBOOK.md).

## 📂 Repository Structure

```
aether-job-career-agent/
├── apps/
│   ├── api/        # FastAPI backend (routers, agents, services, repositories, middleware, migrations/)
│   └── web/        # Next.js 14 frontend (app/, components/, lib/)
├── packages/       # shared workspace packages (agents, db, queue, shared)
├── design/         # DESIGN.md + 17 screen wireframes (design/screens/)
├── docs/
│   ├── delivery/       # gate-verified delivery record (PHASE*-*, gap ledgers, runbook, governance audit)
│   ├── subscription/   # billing-architecture, admin-guide, privacy-policy, terms-of-service
│   ├── architecture/   # original enterprise design PDFs (reference, not the deployed topology)
│   └── research/        # market/competitive research (historical)
├── assets/resume/  # canonical résumé PDF (read-only)
├── ci/             # CI configuration
├── scripts/        # operational scripts
├── uat/            # UAT runner + reports/evidence
├── start-api.sh · start-web.sh   # systemd entrypoints
├── turbo.json · pnpm-workspace.yaml
└── docs/delivery/EXECUTION-REPORT.md   # (root EXECUTION-REPORT.md is a pointer stub)
```

## 📜 Delivery History

The full, gate-verified delivery history lives in [`docs/delivery/`](docs/delivery/):
- **[`PHASE6-EXECUTION-SUMMARY.md`](docs/delivery/PHASE6-EXECUTION-SUMMARY.md)** — latest run: subscription/billing, admin panel, ToS-compliant sourcing, evidence-grounded quality; 34-gate adjudication.
- **[`PHASE6-GAP-ANALYSIS.md`](docs/delivery/PHASE6-GAP-ANALYSIS.md)** + `phase6-gap-analysis.json` — per-gap records with production evidence.
- **[`PHASE6-BLOCKED-ON-HUMAN.md`](docs/delivery/PHASE6-BLOCKED-ON-HUMAN.md)** — operator steps to go fully live.
- **[`DECISIONS.md`](docs/delivery/DECISIONS.md)** — architecture decision records (ADRs).
- Per-phase reports for Phases 0–5 are retained as dated historical records.

<div align="center">

---

**Aether** — an AI career agent with a human approval gate and an anti-fabrication guarantee.

Built by [Vikram Deshpande](https://forgotten-mistory.web.app/)

</div>
