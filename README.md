<div align="center">

# 🔮 AETHER

### Autonomous AI Career Agent Platform

[![Production](https://img.shields.io/badge/Production-Live_(Phase_6)-10B981?style=for-the-badge&logo=vercel&logoColor=white)](https://5cb5f0620.abacusai.cloud)
[![Architecture](https://img.shields.io/badge/Architecture-Complete-FF6B35?style=for-the-badge&logo=blueprint&logoColor=white)](docs/architecture/architecture_document.pdf)
[![Design](https://img.shields.io/badge/Design_System-17_Screens-4F46E5?style=for-the-badge&logo=figma&logoColor=white)](design/DESIGN.md)
[![Billing](https://img.shields.io/badge/Billing-Stripe_(4_tiers,_AUD)-635BFF?style=for-the-badge&logo=stripe&logoColor=white)](docs/subscription/billing-architecture.md)
[![License](https://img.shields.io/badge/License-Private-EF4444?style=for-the-badge&logo=lock&logoColor=white)]()

<br/>

*An enterprise-grade autonomous AI career agent that discovers, evaluates, tailors, applies, and learns — functioning as an intelligent recruiting assistant operating continuously on your behalf.*

<br/>

[Architecture Docs](#-architecture) · [Design System](#-design-system) · [Implementation Guide](#-implementation-guide) · [Roadmap](#-implementation-roadmap) · [Next Steps](#-next-steps)

---

</div>

## 🎯 Vision

Aether is not a resume tool. Not an auto-apply bot. It is an **autonomous AI Executive Career Agent** — think Jarvis + Devin + OpenAI Operator + Claude Computer Use + Enterprise Workflow Engine — combined into a single platform that:

- 🔍 **Discovers** jobs continuously across 15+ job boards (AU & International)
- 📊 **Evaluates** opportunities using a 10-dimensional fit scoring engine
- 📝 **Tailors** resumes with pixel-perfect format preservation and ATS optimization
- ✉️ **Generates** evidence-backed cover letters and recruiter responses
- 🤖 **Applies** autonomously when confidence exceeds configurable thresholds
- 📈 **Learns** from every application outcome to improve over time
- 🛡️ **Never fabricates** — every claim traces to verified evidence from resume, portfolio, or GitHub

<br/>

## 🚦 Production Status (Phase 6 — 2026-07-16)

Aether is **live in production** at **https://5cb5f0620.abacusai.cloud** (`{"status":"ok","version":"0.2.0"}`).
Phases 1–6 have shipped; the sections below (Architecture, Design System, Roadmap, "Next Steps") are the
**original pre-implementation planning artifacts** and are kept as historical record — the real, gate-verified
delivery history lives in [`docs/delivery/`](docs/delivery/) (see `PHASE6-GAP-ANALYSIS.md`, the machine ledger
`phase6-gap-analysis.json`, and per-phase reports for Phases 0–5).

**Shipped and live:**

| Capability | State | Evidence |
|---|---|---|
| **Subscription billing** — 4 tiers (Free/Starter/Pro/Power), GST-inclusive AUD pricing, Stripe Checkout + webhooks + customer portal | Built, unit-tested (mocked Stripe), `/pricing` live (200) | `docs/subscription/billing-architecture.md`, `uat/reports/evidence/phase6/review-billing.json` |
| **Admin panel (Tier 1)** — users + spend, spend-cap control, suspend/unsuspend, settings, append-only audit log, health | Built, production-flow-verified live (spend-cap-before-LLM proven with a temporary admin account) | `docs/subscription/admin-guide.md`, `uat/reports/evidence/phase6/gate17-admin-verification-raw.json` |
| **Quota / spend-cap enforcement** — atomic reserve-before-run, refund-on-failure, honest 429 (never a silent payer switch) | Live in production | `uat/reports/evidence/phase6/review-billing.json`, `deploy-verify.json` |
| **ToS-compliant job sourcing** — Seek scraping removed from the live registry (disabled by default); volume from Adzuna AU (licensed API) + Greenhouse/Lever/Ashby/Workable + Remotive/RemoteOK | Live: 30 jobs / 5 sources, 100% fresh ≤30d, 0 Seek, 0 duplicates | `uat/reports/evidence/phase6/qa-prod-sourcing.json` |
| **Evidence-grounded resume tailoring + cover letters** — entailment verification, zero fabrication survivors, content-only edits, genuine ATS lift | Live-verified (2/8 completions showed strict ATS lift 30.81→32.97, independently reconfirmed) | `uat/reports/evidence/phase6/qa-prod-craft5.json` |

**Pending operator action (human-gated — code is built and tested, live round-trip cannot be completed by an agent):**

1. **Stripe test-mode keys** (`STRIPE_SECRET_KEY`, webhook signing secret, Price IDs) + ABN/Stripe Tax — unblocks the live checkout → webhook → entitlement round-trip.
2. **Admin credential rotation** (`AETHER_ADMIN_EMAIL` + bcrypt `AETHER_ADMIN_PASSWORD_HASH`) — formally closes the admin-panel gate (the demo `admin/admin123` account already carries **zero** admin privilege in production today).
3. **Second Gmail account OAuth consent** — exercises the multi-inbox flow end-to-end (schema, endpoints, and `select_account` are already built and tested).

Full checklist and instructions: [`docs/delivery/PHASE6-BLOCKED-ON-HUMAN.md`](docs/delivery/PHASE6-BLOCKED-ON-HUMAN.md).
**Known non-blocking residual:** tailoring/cover-letter generation is synchronous under a ~100s HTTP edge, so
slow LLM calls surface an honest HTTP 503 (never a fabricated fallback) in roughly 20% of attempts; the durable
fix is asynchronous generation, tracked as `BACKLOG-P6-02`.

<br/>

## 🏗️ Architecture

<table>
<tr>
<td width="50%">

### Enterprise Architecture Package
**84-page** comprehensive document covering:
- C4 Model (Context, Container, Component, Deployment)
- 20 specialized AI agents with full specifications
- Multi-agent orchestration with LangGraph
- Sequence diagrams for all critical workflows
- Data model (ERD) with 20+ entities
- Security architecture (Zero Trust, GDPR, AU Privacy Act)
- Knowledge graph design
- AI memory architecture (5-tier hierarchy)

📄 **[View Architecture Document →](docs/architecture/architecture_document.pdf)**

</td>
<td width="50%">

### Implementation Specification
**Agent-ready build guide** covering:
- Monorepo scaffolding (Next.js + FastAPI + LangGraph)
- Complete Prisma database schema
- 25+ API endpoint contracts with TypeScript interfaces
- System prompts for all 20 agents
- LangGraph orchestration graph definitions
- Kubernetes deployment manifests
- Terraform IaC modules (AWS EKS, RDS, S3)
- CI/CD pipeline (GitHub Actions)
- Monitoring stack (Langfuse + Grafana + Prometheus)

📄 **[View Implementation Guide →](docs/implementation/implementation_guide.pdf)**

</td>
</tr>
</table>

<br/>

## 🎨 Design System

<div align="center">

**17 high-fidelity interactive screens** · Dark mode · Glassmorphism · Coral/Orange accent (#FF6B35)

*Design quality exceeds Linear, Notion, Stripe, Vercel, and Cursor*

</div>

### Screen Inventory

| # | Screen | Type | Description |
|---|--------|------|-------------|
| 1 | **Dashboard** | Desktop | Command center with stats, agent activity feed, market intelligence, application funnel, weekly summary |
| 2 | **Job Discovery** | Desktop | AU/International tabs, 15+ job board integration, 10-dimensional fit scoring, risk signals, source management |
| 3 | **Resume Studio** | Desktop | Split-pane PDF preview, ATS scoring, diff highlighting, evidence tracing, voice DNA controls |
| 4 | **Story Bank** | Desktop | STAR+R achievement memory, interview question mapping, gap analysis, evidence sources |
| 5 | **Application Tracker** | Desktop | 8-column Kanban + Sankey flow visualization, auto follow-up indicators, safety gates |
| 6 | **Interview Center** | Desktop | Prep / Live Assist / Debrief tabs, company intelligence, predicted questions, real-time coaching |
| 7 | **Networking & CRM** | Desktop | Recruiter pipeline, relationship scoring, automated outreach, referral network map |
| 8 | **Email Center** | Desktop | Dual Gmail integration, AI-scored inbox, auto-drafted replies, follow-up engine, voice DNA checks |
| 9 | **Manage Agents** | Desktop | AI provider OAuth/API connections, 22 agent cards with autonomy sliders, cost tracking, tooltips |
| 10 | **Agent Monitor** | Desktop | Live orchestration node graph, task queue, performance metrics, error log, manual overrides |
| 11 | **Analytics** | Desktop | Funnel, conversion trends, ATS distribution, agent ROI, burnout monitor, market pulse |
| 12 | **Offer Comparison** | Desktop | Side-by-side offers, weighted decision matrix, total comp calculator, negotiation coach |
| 13 | **Settings** | Desktop | Profile, integrations, notification preferences, privacy & compliance |
| 14 | **Approval Modal** | Desktop | Confidence-gated approval with AI reasoning, content preview, trust delegation |
| 15 | **Mobile Dashboard** | Phone | Compact stats, approval alerts, activity feed |
| 16 | **Mobile Approval** | Phone | Swipe-to-approve interface for on-the-go decisions |
| 17 | **Cover Letter Studio** | Desktop | Dedicated cover-letter management, versioning, evidence trace, voice DNA, email hand-off (added post-launch; live at `/dashboard/cover-letters`) |

> 📂 **All screens:** [`design/screens/`](design/screens/) — Open any `.html` file in a browser to preview

<br/>

## 🤖 AI Agent Architecture

The original design specified 22 specialized agents. **In production today, 8 runtime agents actually
execute** — `supervisor`, `scout`, `matcher`, `fitScorer`, `tailor`, `coverLetter`, `storyExtractor`,
`emailAgent` (confirmed via `GET /api/agents` on production, `uat/reports/evidence/phase6/probe-16-agent-keys.json`).
The `AgentConfig` table carries **22 configured agent keys** (a superset — the 8 runtime agents plus
disabled/future catalog entries such as `atsOptimization`, `companyResearch`, `interviewPrep`, etc.) so that
future agents can be enabled without a schema change; only the 8 above are wired to LangGraph orchestration
and actually run:

<table>
<tr><td>

**Discovery & Evaluation**
| Agent | Model | Purpose |
|-------|-------|---------|
| Job Discovery | GPT-4o-mini | High-volume job board crawling |
| ATS Optimization | text-embedding-3-large | Semantic matching & scoring |
| Recruiter Intelligence | GPT-4o | Company & recruiter profiling |

**Document Generation**
| Agent | Model | Purpose |
|-------|-------|---------|
| Resume Tailoring | Claude Sonnet | Format-preserving content rewriting |
| Cover Letter | Claude Sonnet | Evidence-backed letter generation |
| Portfolio | GPT-4o | Portfolio evidence extraction |
| Voice DNA | Claude Sonnet | AI-pattern removal, authenticity |

</td><td>

**Automation & Communication**
| Agent | Model | Purpose |
|-------|-------|---------|
| Application | Playwright + GPT-4o | Browser-based form submission |
| Email | GPT-4o | Inbox classification & drafting |
| Calendar | GPT-4o-mini | Interview scheduling |
| Networking | GPT-4o | Outreach & follow-up automation |

**Intelligence & Safety**
| Agent | Model | Purpose |
|-------|-------|---------|
| Supervisor | Claude Sonnet | Orchestration & planning |
| Compliance | Claude Sonnet | Truthfulness verification |
| Learning | GPT-4o | Outcome analysis & strategy |
| Reflection | Claude Sonnet | Performance improvement |
| Error Recovery | GPT-4o-mini | Failure handling & retries |

</td></tr>
</table>

<br/>

## 🛠️ Technology Stack

| Layer | Technology | Rationale |
|-------|-----------|-----------|
| **Frontend** | Next.js 14, TypeScript, Tailwind CSS, shadcn/ui | App Router, RSC, streaming |
| **Backend** | FastAPI (Python), Node.js (TypeScript) | Agent orchestration + API layer |
| **Agent Framework** | LangGraph, LangChain | Stateful multi-agent workflows |
| **Database** | PostgreSQL + pgvector | Relational + vector embeddings |
| **Vector DB** | Pinecone / Weaviate | Semantic search at scale |
| **Queue** | Redis + BullMQ | Async job processing |
| **Auth** | NextAuth.js, OAuth 2.0, JWT | Multi-provider SSO |
| **AI Models** | GPT-4o, Claude Sonnet, Gemini Pro | Multi-provider with fallback |
| **Embeddings** | text-embedding-3-large | 3072-dim semantic matching |
| **Browser Automation** | Playwright | Job board scraping & form filling |
| **Monitoring** | Langfuse, Grafana, Prometheus | Agent tracing + system metrics |
| **Cloud** | AWS (EKS, RDS, S3, SQS, ElastiCache) | Production infrastructure |
| **IaC** | Terraform + Pulumi | Reproducible deployments |
| **CI/CD** | GitHub Actions | Automated testing & deployment |

> Some rows above describe the original design intent rather than what is deployed today — production
> runs Next.js + FastAPI on a single VM behind nginx (not Kubernetes/EKS), PostgreSQL without a separate
> vector DB (no Pinecone/Weaviate in the live path), and OpenRouter as the runtime LLM provider (model
> names in agent config are semantic; Anthropic models route through OpenRouter, not a direct Anthropic
> API/OAuth connection — see `ADR-P6-OAUTH` in `docs/delivery/DECISIONS.md`).

<br/>

## 🧑‍💻 Local Development

```bash
# Install dependencies (Node 20+, pnpm 11.9.0)
pnpm install

# Copy and fill in environment variables (see .env.example for the full list —
# DATABASE_URL, OPENROUTER_API_KEY, AETHER_LLM_MODE, AETHER_CREDENTIAL_KEY, etc.)
cp .env.example .env

# Run the API (FastAPI, Python 3.11+) and the web app (Next.js) separately
./start-api.sh   # loads .env, runs uvicorn on 127.0.0.1:8000
./start-web.sh   # loads .env, runs `pnpm start` (production build) for apps/web

# Or, for iterative frontend/backend development:
pnpm dev         # turbo dev across the monorepo workspaces
pnpm test        # turbo test
pnpm lint        # turbo lint
pnpm type-check  # turbo type-check
```

Billing (Stripe) and the admin panel work locally with mocked/absent Stripe keys — endpoints degrade
honestly (e.g. an unconfigured `STRIPE_SECRET_KEY` returns a clean HTTP 503 on checkout, never a fabricated
payment URL). See `docs/subscription/billing-architecture.md` and `docs/delivery/DEPLOYMENT-RUNBOOK.md`
for the full environment-variable reference and production deployment procedure.

<br/>

## 📋 Implementation Roadmap

> **Historical planning document** (pre-implementation). Phases 1–6 have since shipped to production —
> see [Production Status](#-production-status-phase-6--2026-07-16) above and `docs/delivery/` for the
> real, gate-verified delivery history.

```
Phase 1 ─ Foundation (Weeks 1-4)         Phase 2 ─ Intelligence (Weeks 5-8)
├── Core infrastructure & auth            ├── Full agent architecture (LangGraph)
├── Database schema & migrations          ├── ATS optimization engine
├── Resume parsing & basic tailoring      ├── Cover letter generation
├── Portfolio scraper MVP                 ├── Job discovery automation
└── Dashboard shell                       └── Multi-agent orchestration

Phase 3 ─ Automation (Weeks 9-12)         Phase 4 ─ Learning & Scale (Weeks 13-16)
├── Application submission (Playwright)   ├── Learning agent & feedback loops
├── Email monitoring & auto-response      ├── Analytics dashboard
├── Interview scheduling                  ├── Knowledge graph
├── Human approval workflows              ├── Performance optimization
└── Recruiter CRM                         └── Production hardening
```

<br/>

## 🚀 Next Steps — Pre-Implementation Wireframe Completion

> **Historical planning document.** This checklist predates implementation; the wireframe refinements
> below were addressed during Phases 0–2 (see `docs/delivery/PROGRESS.md`, `docs/delivery/PHASE-0-REVIEW.md`).
> It is kept for historical continuity, not as a current backlog.

Before implementation begins, the following wireframe refinements ensure robust session-to-session integrity:

### Priority 1 — Critical (Must Complete Before Implementation)

| # | Task | Screen(s) | Status |
|---|------|-----------|--------|
| 1 | **Email Center send-confirmation gate** — Add two-step confirmation to "Send Reply" button | Email Center | ⬜ Pending |
| 2 | **Job Discovery two-step apply flow** — Split "Tailor & Apply" into "Tailor Resume →" then "Review & Apply →" | Job Discovery | ⬜ Pending |
| 3 | **Settings integration-status sync** — Match job board statuses with Job Discovery source bar | Settings | ⬜ Pending |
| 4 | **Empty states for Networking, Offers** — Add no-data designs with onboarding CTAs | Networking, Offer Comparison | ⬜ Pending |
| 5 | **Analytics time-period selector** — Add "7d / 30d / 90d / All" toggle and align funnel numbers | Analytics | ⬜ Pending |
| 6 | **Cross-screen linking** — Add "View in CRM →", "View Email Thread →", "Pull from Story Bank →" contextual links | Email, Tracker, Interview | ⬜ Pending |

### Priority 2 — Enhancement (Improve Before or During Phase 1)

| # | Task | Screen(s) | Status |
|---|------|-----------|--------|
| 7 | **Resume Studio version comparison** — Dropdown to compare any two tailored versions | Resume Studio | ⬜ Pending |
| 8 | **Interview Center Live Assist disclaimer** — Add compliance banner | Interview Center | ⬜ Pending |
| 9 | **Agent test buttons** — "Test Agent" + estimated cost per task on each agent card | Manage Agents | ⬜ Pending |
| 10 | **Job Discovery saved jobs tab** — "⭐ Saved" tab with bookmark action on cards | Job Discovery | ⬜ Pending |
| 11 | **Mobile notification badges** — Badge counts on bottom tab bar items | Mobile Dashboard | ⬜ Pending |
| 12 | **Mobile swipe gestures** — Swipe-to-approve/reject hints | Mobile Approval | ⬜ Pending |

### Priority 3 — New Screens (Consider Adding)

| # | Task | Description | Status |
|---|------|-------------|--------|
| 13 | **Onboarding Wizard** | 5-step guided setup: profile → resume upload → portfolio sync → job preferences → agent config | ⬜ Planned |
| 14 | **Cover Letter Studio** | Dedicated screen for cover letter management, versioning, and templates | ⬜ Planned |
| 15 | **Notification Center** | Full notification history with filtering by type and priority | ⬜ Planned |

### Session Continuity Protocol

To ensure robust integrity across implementation sessions:

1. **This repository is the single source of truth** — All architecture, design, and research artifacts are version-controlled here
2. **Design System** — [`design/DESIGN.md`](design/DESIGN.md) contains the complete design language specification (colors, typography, spacing, components)
3. **Review Report** — [`design/review_report.md`](design/review_report.md) contains the adversarial audit with all findings and their resolution status
4. **Architecture Document** — [`docs/architecture/architecture_document.pdf`](docs/architecture/architecture_document.pdf) is the canonical architecture reference
5. **Implementation Guide** — [`docs/implementation/implementation_guide.pdf`](docs/implementation/implementation_guide.pdf) is the agent-ready build specification
6. **Research Foundation** — [`docs/research/`](docs/research/) contains all competitive analysis and market research

> **For any new implementation session:** Start by reading this README, then the Implementation Guide, then the Architecture Document, then the Design System. This sequence provides complete context without loss.

<br/>

## 📂 Repository Structure

```
aether-job-career-agent/
├── README.md                              # This file — project overview & roadmap
├── docs/
│   ├── architecture/
│   │   ├── architecture_document.pdf      # 84-page enterprise architecture (C4, agents, ERD, security)
│   │   └── architecture_document.html     # Source HTML
│   ├── implementation/
│   │   ├── implementation_guide.pdf       # Agent-ready build specification
│   │   └── implementation_guide.html      # Source HTML
│   └── research/
│       ├── portfolio_analysis.md          # Portfolio website deep analysis
│       ├── resume_analysis.md             # Resume structured extraction
│       ├── github_repo_analysis.md        # Existing repo capabilities assessment
│       ├── recruitment_and_apis.md        # Job board APIs & hiring trends
│       ├── competitive_features.md        # 25 competitive features ranked by impact
│       ├── jobpilot_analysis.md           # Job Pilot repo analysis
│       ├── careerops_analysis.md          # Career-Ops platform analysis
│       └── github_trackers_analysis.md    # Top 20 job tracker repos synthesis
├── design/
│   ├── DESIGN.md                          # Complete design system specification
│   ├── canvas.json                        # Screen registry & layout metadata
│   ├── review_report.md                   # Adversarial audit findings & status
│   └── screens/                           # 16 high-fidelity HTML wireframes
│       ├── dashboard.html
│       ├── job-discovery.html
│       ├── resume-studio.html
│       ├── story-bank.html
│       ├── application-tracker.html
│       ├── interview-center.html
│       ├── networking.html
│       ├── email-center.html
│       ├── agents.html
│       ├── agent-monitor.html
│       ├── analytics.html
│       ├── offer-comparison.html
│       ├── settings.html
│       ├── approval-modal.html
│       ├── mobile-dashboard.html
│       └── mobile-approval.html
└── assets/
    └── resume/
        └── Vik_Resume_Final.pdf           # Canonical resume (format must be preserved)
```

<br/>

<div align="center">

---

**Aether** — *Your autonomous AI career agent, operating 24/7 on your behalf.*

Built with 🔥 by [Vikram Deshpande](https://forgotten-mistory.web.app/)

</div>
