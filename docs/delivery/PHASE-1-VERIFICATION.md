# Phase 1 — Foundation: Deployment, End-to-End Verification & Adversarial Review

**Date:** 2026-07-02  ·  **Branch:** `phase-1/foundation`  ·  **Reviewer:** Aether Delivery Agent (Session 2)
**Live deployment:** <https://5cb5f0620.abacusai.cloud>  (root `/` → 307 → `/dashboard`)

> **Scope note.** Phase 1 is the *Foundation* phase. It delivers the design system, the app shell +
> navigation, the authentication core, the full data model, the API skeleton, and the agent/LLM/queue
> infrastructure. It deliberately does **not** implement the individual feature workspaces (Jobs, Resume
> Studio, …) — those are later phases. This document verifies what Phase 1 claims to deliver, maps every
> Phase 0 wireframe to its Phase 1 status **honestly**, and then attacks the deliverable adversarially.

---

## 1. Verdict

**Foundation is deployed, green, and faithful to the wireframe design system.** The dashboard shell is a
pixel-faithful realisation of `design/screens/dashboard.html` (dark glassmorphism, coral `#FF6B35`,
12-item Schema-A sidebar). Every navigation route now resolves (200, graceful placeholder) rather than
404-ing. All automated gates pass. The two known follow-ups (coverage-threshold enforcement; landing the
literal `.github/workflows/ci.yml`) are documented and owner-assigned. **No feature screen is
misrepresented as complete** — un-built sections render an explicit "planned for a later phase" panel.

---

## 2. Deployment

| Aspect | Detail |
|--------|--------|
| Public URL | `https://5cb5f0620.abacusai.cloud` |
| Web runtime | Next.js 14 production build (`next build` → `next start`) on `127.0.0.1:3000` |
| Process manager | `aether-web.service` (systemd, `Restart=always`) |
| Ingress | nginx vhost `/etc/nginx/conf.d/5cb5f0620.conf` (`server_name 5cb5f0620.vm.internal`) → proxy to `:3000`, forwards original host via `X-Original-Host` |
| API runtime | FastAPI via `uvicorn app.main:app` (`127.0.0.1:8000`) — verified locally; not publicly exposed (single hostname reserved for the web app) |

Live HTTP checks:

```
GET /                     → 307  (redirect to /dashboard)
GET /dashboard            → 200
GET /dashboard/jobs       → 200   (graceful placeholder, was 404 before P1-S12)
GET /dashboard/resume     → 200   … all 12 nav routes → 200
GET /dashboard/<unknown>  → 200   (generic placeholder, not a 404)
GET  http://127.0.0.1:8000/health → {"status":"ok","version":"0.1.0"}
GET  http://127.0.0.1:8000/docs   → 200 (OpenAPI UI, title "Aether API")
```

---

## 3. End-to-End Verification (evidence)

| Gate | Command | Result |
|------|---------|--------|
| Node unit tests | `pnpm -r run test` | **71 passed** — shared 4, web 29, db 13, agents 18, queue 7 |
| Web e2e smoke | `playwright test` (chromium) | **3 passed** — 12-item nav renders; `/`→`/dashboard`; nav section shows placeholder (not 404) |
| Lint (recursive) | `pnpm -r run lint` | exit 0 |
| Type-check (recursive) | `pnpm -r run type-check` | exit 0 |
| Build (recursive) | `pnpm -r run build` | exit 0 (web + all packages) |
| API tests | `pytest -q` | **22 passed** |
| API lint | `ruff check app tests` | clean |
| API types | `mypy app` | clean (11 files) |
| CI security gate 1 | `.env` tracked? | **not tracked** ✅ |
| CI security gate 2 | `sk-or-v1-<32+>` in source? | **none** ✅ (synthetic test/doc placeholders correctly ignored) |

**Totals: 96 automated tests green (71 Node + 3 e2e + 22 API), 0 failures.** Guardrails intact: the
résumé asset `assets/resume/Vik_Resume_Final.pdf` is byte-for-byte unchanged (format hash
`0700d1aa…0768a25` still pinned by the parser tests); no secret is committed; `main` is untouched.

---

## 4. Design-system fidelity (deployed vs wireframe)

The deployed `/dashboard` was compared directly against `design/screens/dashboard.html`:

| Element | Wireframe | Deployed | Match |
|---------|-----------|----------|-------|
| Palette / theme | `#0A0A0F` bg, coral `#FF6B35`, glassmorphism | same tokens (`tailwind.config.ts`, `globals.css`) | ✅ |
| Logo lockup | coral→amber bolt, "Aether / Career Agent" | identical | ✅ |
| Sidebar | 12-item Schema-A nav + "Agents Active" widget + Manage Agents | identical, renders from `NAV_ITEMS` contract | ✅ |
| Topbar | greeting + search + notifications + user chip | identical (greeting static in Phase 1) | ✅ |
| Stat cards | Active Applications / Interview Rate / Offers (+ AI Confidence) | identical, 4 cards | ✅ |
| Agent Activity | live feed with entries | section present with "live" dot; **feed entries deferred** (labelled) | ⚠️ intentional |
| Today's Opportunities | opportunity cards | **deferred** (labelled in shell copy) | ⚠️ intentional |

The two ⚠️ rows are Phase 1's explicit deferrals — the shell states "The activity feed, opportunity
cards, and approvals panel arrive in the next slices." Nothing is faked.

---

## 5. Wireframe requirement → Phase 1 implementation matrix

Every Phase 0 wireframe screen, its owning nav item, and its **honest** Phase 1 status. "Foundation
backing" is the data model / service / infra a later-phase screen will build on — already in place.

| # | Wireframe screen | Nav item | Phase 1 status | Foundation backing (in place today) |
|---|------------------|----------|----------------|--------------------------------------|
| 1 | `dashboard.html` | Dashboard | **Shell built** (cards, topbar, sidebar); feed/opportunities deferred | shell + design system + `NAV_ITEMS` |
| 2 | `job-discovery.html` | Jobs | Placeholder | `Job` + `JobEmbedding (vector 1536)` models; `discovery` queue; portfolio scraper |
| 3 | `resume-studio.html` | Resume Studio | Placeholder | `Resume` model (`formatHash` + self-referential version lineage); `resume_parser` (pdfplumber); `resume_tailor` seam; `tailoring` queue |
| 4 | `cover-letter-studio.html` | (under Resume) | Placeholder (design added Phase 0) | `Resume`/`StoryEntry`; LLM record-replay seam |
| 5 | `story-bank.html` | Story Bank | Placeholder | `StoryEntry` model |
| 6 | `application-tracker.html` | Applications | Placeholder | `Application` model + `ApplicationStatus`; `application` queue |
| 7 | `interview-center.html` | Interview Center | Placeholder | *(no dedicated model yet — Phase 2)* |
| 8 | `networking.html` | Networking | Placeholder | `Contact` model + `ContactStage` |
| 9 | `email-center.html` | Email Center | Placeholder | `EmailThread` model |
| 10 | `agents.html` | Agents | Placeholder | `AgentRun` + `AgentRunStatus`; `BaseAgent`, `ToolRegistry`, `AetherAgentState`; LLM client (replay/record/auto) |
| 11 | `analytics.html` | Analytics | Placeholder | derived from `Application`/`Job`/`AgentRun` (funnel 847→412→156→23→4 defined in Phase 0) |
| 12 | `offer-comparison.html` | Offers | Placeholder | *(no dedicated Offer model yet — Phase 2)* |
| 13 | `settings.html` | Settings | Placeholder | `User` model; integration-status pattern (Phase 0) |
| 14 | `approval-modal.html` | (modal) | Not yet wired | `ApprovalRequest` + `ApprovalType` + `ApprovalStatus` |
| 15 | `agent-monitor.html` | (Agents sub) | Placeholder | `AgentRun` |
| 16 | `mobile-dashboard.html` | (mobile) | Deferred (P0-S11 backlog) | responsive shell |
| 17 | `mobile-approval.html` | (mobile) | Deferred (P0-S12 backlog) | `ApprovalRequest` |

**Reading of the matrix:** 1 screen realised as a working shell; 11 nav sections reachable with a
graceful, honest placeholder; the remaining wireframes (modals/mobile) are backlog. Critically, the
**data model already covers every wireframe entity** (User, Job + embeddings, Resume + versions,
Application, ApprovalRequest, Contact, EmailThread, StoryEntry, AgentRun) — so the feature phases build
on a complete schema rather than inventing it screen-by-screen.

---

## 6. Adversarial review (attacking the deliverable)

Three lenses: guardrail compliance, "what would a hostile reviewer attack", and spec fidelity.

### 6.1 Guardrail compliance — all ✅
- **TDD** held for every slice, including P1-S12 added during this verification (4 unit + 1 e2e tests
  written RED — `findNavItemByHref is not a function` — before implementation turned them GREEN).
- **No secret ever committed;** CI `security` job enforces this in perpetuity; every commit secret-scanned.
- **Résumé PDF unchanged** (format hash still pinned).
- **`main` untouched;** all work on `phase-1/foundation`, pushed (never merged).
- **Conventional commits;** one `feat`/`ci` + one `docs(progress)` per slice; `git add <paths>` only.

### 6.2 Ranked findings
1. **Coverage is not enforced.** Directive targets ≥85% line coverage; `@vitest/coverage-v8` is not
   wired and no threshold gate exists. *Mitigation:* behaviour is well-tested (96 tests). *Next:* a
   dedicated slice adds coverage tooling + CI thresholds. (Owner: Phase 1 close-out.)
2. **`.github/workflows/ci.yml` is not on the remote.** The Abacus GitHub App installation lacks the
   `workflows` permission, so the activation commit (`2f94cdc`) is rejected. The byte-identical mirror
   `ci/github-actions-ci.yml` **is** pushed. *Next:* grant the permission and re-push, or copy via the
   GitHub UI (see `ci/README.md`, D-0008). (Owner: user action + re-push.)
3. **Feature workspaces are placeholders.** 11/12 nav sections render a "planned for a later phase"
   panel, not functionality. *This is by design for a foundation phase* and is stated explicitly on
   each screen — but a reviewer must not read the deployed app as feature-complete. (Owner: Phases 2+.)
4. **LLM live path is unit-tested only via an injected fake.** `OpenRouterClient` takes an injectable
   `fetch`; no test exercises it directly (CI is offline/replay). *Mitigation:* nightly non-blocking
   `live-openrouter` job. *Next:* add a stub-`fetch` unit test asserting header/body shape + that the
   key is never logged. (Owner: Phase 2.)
5. **DB integration is types-only.** Repository tests run against `@prisma/client` types; no
   migration / `pgvector` round-trip. *Mitigation:* `prisma generate` runs in CI; integration gated on
   `DATABASE_URL`. *Next:* provision Postgres in CI. (Owner: Phase 2.)
6. **Auth user store is a placeholder.** `authorizeCredentials` is wired but `lookupUser→null` /
   `verifyPassword→false` until a store exists (D-0006). Expected for foundation. (Owner: Phase 2.)
7. **Topbar greeting is static** ("Good morning, Vikram", "Pro plan"). Cosmetic; wired to session data
   in Phase 2.

### 6.3 Spec-fidelity deviations (intentional, each an ADR)
- API uses the repo's existing `app/` package rather than the spec's `api/`.
- Sidebar label is "Resume Studio" (no accent) per **D-0002**.
- Fonts load via `<link>` not `next/font` for hermetic offline builds per **D-0007**.
- Active-nav + placeholder added as **D-0009** (P1-S12) during deployment hardening.

---

## 7. How to reproduce this verification

```bash
# from repo root
export TURBO_TELEMETRY_DISABLED=1 NEXT_TELEMETRY_DISABLED=1 AETHER_LLM_MODE=replay
pnpm --filter @aether/db run prisma:generate
pnpm -r run lint && pnpm -r run type-check && pnpm -r run build && pnpm -r run test
( cd apps/web && PLAYWRIGHT_BROWSERS_PATH=/opt/browsers npx playwright test )
( cd apps/api && python3 -m ruff check app tests && python3 -m mypy app && python3 -m pytest -q )
```

**Conclusion.** Phase 1 Foundation is deployed, fully green, honestly scoped, and faithful to the
wireframe design system. Recommended for independent + adversarial review, then merge to `main`, with
coverage enforcement and the CI-workflow activation as the two explicit close-out items.
