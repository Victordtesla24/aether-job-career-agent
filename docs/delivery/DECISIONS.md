# Aether Delivery Decisions Log

This file records durable, cross-session engineering and product decisions for the Aether
delivery effort. Each entry is append-only. Newest entries at the top.

---

## D-0001 — Delivery approach: vertical slices, strict TDD, single source of truth
**Date:** 2026-07-01 · **Author:** Aether Delivery Agent (Session 1) · **Status:** Adopted

**Context.** The repository currently holds architecture, design, research, and 16 high-fidelity
HTML wireframes. The design `review_report.md` flagged navigation inconsistency (a BLOCKER),
cross-screen data contradictions, and missing safety rails. Implementation has not started.

**Decision.**
1. **Vertical slices.** All work is decomposed into small, independently shippable slices with a
   stable ID (e.g. `P0-S01`). Each slice has a Given/When/Then acceptance statement, is tracked in
   `PROGRESS.md`, and lands in its own conventional commit tagged with the slice ID.
2. **Strict TDD for code.** Every code slice follows RED → GREEN → (REFACTOR). A failing test is
   written and observed to fail before the implementation is written. Wireframe/design slices are
   verified by structural checks and manual visual review rather than unit tests.
3. **Single source of truth.** `docs/delivery/PROGRESS.md` is the canonical status ledger.
   `design/DESIGN.md` is the canonical design language. `design/review_report.md` tracks audit
   findings and their resolution. This repo is the single source of truth across sessions.
4. **Branching.** Feature work happens on task branches (Phase 0 wireframes on
   `phase-0/wireframes`). `main` is never edited directly. Changes reach `main` only via PR.
5. **Secrets.** `.env` is never committed. Only `.env.example` (keys with placeholder values) is
   version-controlled. No real API key is ever logged or printed.

**Consequences.** Slower per-commit but fully auditable, resumable across sessions, and safe.

---

## D-0002 — Standardize on the 12-item sidebar (Schema A) across every screen
**Date:** 2026-07-01 · **Author:** Aether Delivery Agent (Session 1) · **Status:** Adopted

**Context.** `review_report.md` identifies two competing navigation schemas. Schema A (12 items:
Dashboard, Jobs, Resume Studio, Story Bank, Applications, Interview Center, Networking,
Email Center, Agents, Analytics, Offers, Settings) is used by 10 screens; Schema B (9 items, adds a
phantom "Cover Letters", drops 4 real screens) is used by 4 screens. This is a BLOCKER.

**Decision.** Every screen — existing and newly created — uses the identical Schema A 12-item
sidebar. The active item is highlighted with the coral accent (`#FF6B35`). The logo lockup and
bottom profile widget are standardized. The label text "Resume Studio" is used verbatim on all
screens to guarantee pixel-identical navigation (avoids mixing "Resume" / "Résumé").

**Consequences.** New screens created this session (Onboarding Wizard, Cover Letter Studio,
Notification Center) ship with Schema A. Screens touched for other slices have their sidebar
reconciled to Schema A opportunistically.

---

## D-0003 — Canonical funnel numbers
**Date:** 2026-07-01 · **Author:** Aether Delivery Agent (Session 1) · **Status:** Adopted

**Context.** `review_report.md` found three different funnel datasets across Dashboard, Tracker
Sankey, and Analytics. The delivery brief specifies a single canonical funnel.

**Decision.** The canonical application funnel is:
`847 (Jobs Found) → 412 (Applied) → 156 (Screened) → 23 (Interviewed) → 4 (Offers)`.
These exact numbers must be used everywhere funnel data appears. Analytics is aligned first
(P0-S05); Dashboard and Application Tracker will be reconciled in follow-up slices.

**Consequences.** Any screen showing funnel data must reference this set. Deviations are bugs.

---

## D-0004 — Test harness & CI toolchain
**Date:** 2026-07-01 · **Author:** Aether Delivery Agent (Session 1) · **Status:** Adopted

**Context.** The implementation guide specifies a pnpm + Turborepo monorepo with a Next.js 14
`apps/web` frontend and a FastAPI `apps/api` backend, tested in GitHub Actions.

**Decision.** For P1-S00 we bootstrap a minimal but runnable harness aligned to the guide:
- `apps/web`: TypeScript + **Vitest** for unit tests (`__tests__/health.test.ts`).
- `apps/api`: Python 3.11 + **pytest** (`tests/test_health.py`).
- Root: pnpm workspace (`pnpm-workspace.yaml`), shared scripts.
- CI (`ci/github-actions-ci.yml`): install → lint → type-check → unit tests → build, on
  **Node 20** and **Python 3.11**, with dependency caching.

**Consequences.** Later slices extend these apps rather than re-scaffolding. Vitest chosen over
Jest for speed and zero-config ESM/TS support; it is swappable without changing slice contracts.

**Update (D-0005 cross-ref).** The CI workflow is stored at `ci/github-actions-ci.yml` (an inert
template) rather than `.github/workflows/ci.yml`, so branches push and merge to `main` without
requiring the GitHub App `workflows` permission. Activation instructions live in `ci/README.md`.
This keeps CI-CD simple with no permission friction; the workflow is copied into
`.github/workflows/` only when the team chooses to switch CI on.

---

## D-0006 — Auth: framework-free JWT session layer now, NextAuth route wiring in P1-S06
**Date:** 2026-07-02 · **Author:** Aether Delivery Agent (Session 2) · **Status:** Adopted

**Context.** P1-S03 delivers authentication, but Next.js itself is not introduced until the
dashboard shell (P1-S06). NextAuth.js requires `next`/`react` as peer dependencies and its route
handler cannot run without a Next.js app. Pulling those heavy peers a slice early — purely to host a
handler that has nothing to serve yet — would add fragility with no functional payoff.

**Decision.** In P1-S03 we implement the security-critical core as framework-agnostic,
fully-unit-tested TypeScript in `apps/web/src/lib/auth/`:
- `jwt.ts` — sign/verify session tokens via `jose` (the same library NextAuth uses internally), so
  the token format matches what NextAuth will issue later.
- `session.ts` — session model + forgiving token→session resolution.
- `require-auth.ts` — a `requireAuth` guard that reads a Bearer header or the session cookie and
  returns a discriminated result; works with the Fetch `Request` used by Next.js route handlers /
  middleware and with plain test doubles.
- `credentials.ts` — `authorizeCredentials`, the Credentials-provider callback, written with its
  data-access and password-verification dependencies injected (wired to `UserRepository` + a real
  hash comparison in P1-S06). The returned user never carries the password hash.
- `options.ts` — `authConfig`, a NextAuth-shaped config object (Credentials provider + stateless
  JWT session strategy) ready to hand to `NextAuth(authConfig)`.
- `test-helpers.ts` — token/session factories shared by unit tests and future E2E setup.

**Consequences.** The auth contract is provable without booting a framework and the suite stays
green offline. When P1-S06 adds Next.js, the NextAuth route handler
(`app/api/auth/[...nextauth]/route.ts`) simply consumes `authConfig` + the `jose` helpers and the
Credentials `authorize` delegates to `authorizeCredentials`. Signing secret is read from
`NEXTAUTH_SECRET` (already in `.env.example`) and is never logged.



---

## D-0007 — Web: App Router + offline-safe fonts via `<link>` (not `next/font`)
**Date:** 2026-07-02 · **Author:** Aether Delivery Agent (Session 2) · **Status:** Adopted

**Context.** P1-S06 introduces Next.js for the dashboard shell. Two choices needed pinning: (1) how
to load the Inter / JetBrains Mono web fonts and Font Awesome icon set, and (2) how the NextAuth
route handler deferred in D-0006 gets wired.

**Decision.**
- **App Router** (`src/app/*`) is the routing model. The 12-item Schema-A sidebar renders straight
  from a single pure-data contract, `src/lib/navigation.ts` (no React/Next imports), so the ordering
  is unit-testable under a plain Node/Vitest environment and is asserted by
  `__tests__/navigation.test.ts`.
- **Fonts/icons load via `<link>` tags in the root layout `<head>`**, not `next/font`. `next/font`
  fetches font files from Google at *build* time; that would make `next build` (and therefore CI and
  offline builds) network-dependent and non-deterministic. Loading via `<link>` keeps builds hermetic.
  Because this is the correct App Router pattern (there is no Pages-Router `_document.js`), the legacy
  `@next/next/no-page-custom-font` lint rule is disabled in `.eslintrc.json` with this rationale.
- **NextAuth wiring (fulfils D-0006).** `src/lib/auth/next-auth-options.ts` builds a real
  `NextAuthOptions` (Credentials provider + stateless-JWT session) whose `authorize` delegates to the
  P1-S03 `authorizeCredentials`. `src/app/api/auth/[...nextauth]/route.ts` exports the `NextAuth`
  handler as both `GET` and `POST`. The user-lookup / password-verify dependencies are placeholders
  returning `null`/`false` (no user store is seeded yet); they are wired to `UserRepository` + a real
  hash comparison in Phase 2. Secret is read from `NEXTAUTH_SECRET`; never logged.

**Alternatives.** `next/font` (rejected: build-time network); embedding the sidebar order in the
component (rejected: not independently testable); pulling NextAuth peers back in P1-S03 (rejected in
D-0006).

**Consequences.** `next build`, `type-check`, `lint`, Vitest (25 web tests) and a Playwright smoke
test (`e2e/dashboard.spec.ts`, 2 tests asserting the 12 nav items render and `/`→`/dashboard`) all
pass offline. Build tooling added to `@aether/web`: `next`, `react`, `react-dom`, `next-auth`,
`tailwindcss`/`postcss`/`autoprefixer`, `@types/*`, `eslint-config-next`, `@playwright/test`. The
`build` script is now `next build` (the orphaned `tsconfig.build.json` and `.eslintrc.cjs` were
removed). `unrs-resolver` was added to `pnpm-workspace.yaml`'s allowed build scripts (a native
dependency of `eslint-config-next`). **Reversible?** Yes — fonts could later move to `next/font` with
a self-hosted/offline cache without touching the navigation contract or auth wiring.


## D-0008 — Activate CI at `.github/workflows/ci.yml` (mirror retained; staged push)

**Date:** 2026-07-02 · **Author:** Aether Delivery Agent (Session 2) · **Status:** Adopted

**Context.** Phase 1 needs a live CI gate. Through Phase 0 the workflow was parked as an inert
template at `ci/github-actions-ci.yml` (D-0004) because the Abacus GitHub App is not guaranteed the
`workflows` permission, and a push that touches `.github/workflows/**` is rejected without it. Slice
P1-S11 also introduced offline LLM fixtures that CI must exercise deterministically.

**Decision.**
- **Activate** the pipeline at `.github/workflows/ci.yml`, and keep `ci/github-actions-ci.yml` as a
  **verbatim mirror** (kept identical on every edit via `cp`). The mirror guarantees the exact
  workflow stays reviewable/tracked even if the workflow push is rejected.
- **Pipeline shape.** Four PR/push jobs — `security` (fails if `.env` is tracked or a real-looking
  `sk-or-v1-<32+ alnum>` key appears in source), `node` (Node 20: install → **`@aether/db`
  `prisma:generate`** → lint → type-check → unit tests → build, all recursive across the workspace,
  with `AETHER_LLM_MODE=replay`), `api` (Python 3.11: ruff → mypy → pytest), and `e2e` (Playwright
  chromium smoke, `needs: node`). One schedule/dispatch-only job — `live-openrouter` — is
  `continue-on-error` (non-blocking), skips when `OPENROUTER_API_KEY` is unset, and never gates PRs.
- **Prisma generate precedes type-check/build** because the web app and repositories type-check
  against `@prisma/client`; without a generated client the Node job would fail.
- **Key-scan regex requires a long tail** (`{32,}`) so clearly-synthetic placeholders (the
  `redactSecrets` unit test's short `sk-or-v1-abcdef…`, and the fixtures README's `sk-...`) are not
  false-positives, while real 64-hex keys are still caught. The pattern does not match itself in the
  workflow file (it is followed by `[`).
- **Push structure (workflows permission).** The Abacus GitHub App installation lacks the `workflows`
  permission, so GitHub rejects any push that creates/updates a file under `.github/workflows/**`
  (confirmed empirically — the first attempt to push a commit containing `.github/workflows/ci.yml`
  was `remote rejected`). Crucially, the byte-identical **mirror** `ci/github-actions-ci.yml` lives
  *outside* `.github/workflows/` and pushes without any special permission. The slice is therefore
  split so everything lands on the remote except the one genuinely-blocked file:
  1. `f109757` — the full pipeline as the tracked mirror `ci/github-actions-ci.yml` + `ci/README.md`.
  2. a `docs(progress)` commit recording the slice (+ this ADR + the Phase 1 self-review).
  3. a final commit that drops the identical file into `.github/workflows/ci.yml` to activate it.
  Commits 1–2 are pushed normally; commit 3 is the only thing that can be rejected. **To finish
  activation**, either grant the app the `workflows` permission
  (<https://github.com/apps/abacusai/installations/select_target>) and re-push, or copy
  `ci/github-actions-ci.yml` into `.github/workflows/ci.yml` via the GitHub web editor (a UI commit is
  authored as the user, not the app, so no extra permission is needed). See `ci/README.md`.

**Alternatives.** Keep CI inert (rejected: Phase 1 wants a live gate); split web from packages into
separate jobs (rejected: one recursive Node job is simpler and covers every package's tests, which the
old web-only job missed); add a coverage-threshold gate now (deferred: `@vitest/coverage-v8` is not yet
a dependency — wiring coverage + per-package thresholds is its own slice, and adding an unconfigured
gate would break the green pipeline).

**Consequences.** Every gate was verified locally before commit: recursive lint / type-check / build
exit 0, 63 unit tests green, API 22 pytest + ruff + mypy clean, Playwright smoke green, and both
security checks behave correctly. Coverage enforcement (directive target ≥85% on
`agents`/`db`/`shared` + API handlers) remains a tracked follow-up. **Reversible?** Yes — the workflow
can be reverted to inert-template-only by deleting `.github/workflows/ci.yml`; the mirror and harness
remain.

---

## D-0009 — Graceful placeholder + pathname-aware sidebar for unbuilt dashboard routes (P1-S12)

**Context.** Deploying Phase 1 exposed a UX gap: the 12-item Schema-A sidebar links to a route per
section, but only `/dashboard` has a page (the feature workspaces are later phases). On the live
deployment, clicking any of the other 11 nav items returned a bare Next.js 404, and the dashboard
layout hard-coded `activeHref="/dashboard"` (a TODO deferred in P1-S06), so the active highlight never
tracked the current route.

**Decision.** Harden the shell so it degrades gracefully instead of shipping dead links:
- Add a pure `findNavItemByHref(href)` resolver in `apps/web/src/lib/navigation.ts` — prefix-based,
  most-specific-match-wins, returning `undefined` for a path that maps to no known section. It is
  React/Next-free so it unit-tests in plain Node (as the rest of the nav contract does).
- Make `Sidebar` a client component that reads `usePathname()` and highlights the owning section on
  *any* route (`activeHref` remains an optional override for tests/stories). The dashboard layout no
  longer passes a hard-coded value — this closes the P1-S06 "active item resolved in a later slice" TODO.
- Add a catch-all `app/dashboard/[...slug]/page.tsx` that renders the resolved section title inside the
  existing shell with an honest "planned for a later phase" panel; unknown routes fall back to a generic
  placeholder. Every route now returns 200, not 404.

**Alternatives.** (a) Leave the 404s and document them (rejected: a deployed foundation demo where 11/12
nav clicks 404 misrepresents readiness and invites reviewer noise). (b) Build stub *feature* pages
(rejected: that is later-phase scope and risks fabricating functionality the wireframes imply but Phase 1
does not yet deliver — the placeholder is explicit that the workspace is not built). (c) A single
`not-found.tsx` (rejected: it cannot title the section or keep the correct nav active, and still reads as
an error rather than a roadmap state).

**Consequences.** +4 resolver unit tests (web 25 → 29) and +1 Playwright smoke; full suite green; verified
on the live deployment (all 12 nav routes 200). The placeholder is deliberately honest about scope, so it
does not overstate Phase 1. **Reversible?** Yes — deleting the catch-all route restores the prior
behaviour; the resolver is additive and independently useful for future active-nav needs.



## D-0010 — Cover letters live on the `Application` row (no new Prisma model)

**Date.** 2026-07-02 (P2-S07)

**Context.** The Prisma schema has no `CoverLetter` model, but P2-S07 needs to persist drafts,
list them, and route them through the approval gate. Adding a model means a schema migration on
the shared hosted Postgres mid-phase.

**Decision.** Store each draft on an `Application` row (`coverLetter` column, `status=draft`);
the cover-letter id *is* the application id. `ApprovalRequest.type` only enumerates
`application_submit | email_send | offer_response`, so cover-letter approvals use
`application_submit` with `payload.kind = "cover_letter"` as the discriminator.

**Alternatives.** (a) New `CoverLetter` model + migration (rejected for now: schema churn mid-slice
on a shared DB; the Application row is the natural owner since a letter exists only in service of an
application). (b) Extend the `ApprovalType` enum (rejected: Postgres enum migration for a value the
payload can express losslessly).

**Consequences.** Zero schema changes; drafts appear in both `/cover-letters` and the applications
kanban (`draft` column) for free. **Reversible?** Yes — a later `CoverLetter` model can be backfilled
from `Application.coverLetter`.

## D-0011 — Record-replay LLM client; CI and tests never call a model

**Date.** 2026-07-02 (P2-S04..S08)

**Context.** Fit scoring, tailoring, cover letters and story extraction all need LLM output, but
tests must be deterministic, free, and offline; and generated claims must never outrun the resume.

**Decision.** `LLMClient` with `AETHER_LLM_MODE=record|replay` (default **replay**): replay reads
fixtures from `apps/api/tests/fixtures/llm/<prompt_name>/<key>.json`; record mode (opt-in, live key)
writes them. Model tiers resolve from `AETHER_MODEL_<TIER>` env vars. Fixture content policy: every
number/entity in a fixture must exist in the real base resume, because the fabrication guard and
token-subset validators run on replayed output exactly as they would on live output.

**Alternatives.** Mock at the HTTP layer per test (rejected: N copies of the same canned payloads,
and no path to "flip one env var and go live"). Skip validation in tests (rejected: the guard *is*
the product).

**Consequences.** 74 API tests run hermetically; live mode is a config change, not a code change.
**Reversible?** Yes — the client is a thin seam; swapping in a provider SDK touches one module.

## D-0012 — Web API access: nginx `/api/` proxy + demo auto-login client

**Date.** 2026-07-02 (P2 frontend + deployment)

**Context.** The Next.js app (:3000) and FastAPI (:8000) sit behind one nginx vhost
(`5cb5f0620.abacusai.cloud`). Browser code needs a same-origin API base (no CORS) and a bearer
token, but the demo deployment has no interactive login UI yet.

**Decision.** nginx routes `location /api/ { proxy_pass http://127.0.0.1:8000/; }` (prefix
stripped) ahead of the catch-all `/` → :3000. `src/lib/api/client.ts` resolves the base URL
(env override → `/api` in the browser → `localhost:8000` for SSR/tests), auto-logs-in with the
seeded demo user on first request, caches the JWT in `localStorage`, and retries once on 401.
Both services run under systemd (`aether-api.service`, `aether-web.service`).

**Alternatives.** Next.js rewrites to :8000 (rejected: couples deploy topology into app config and
double-proxies). Cookie session via NextAuth against FastAPI (deferred: real login UX is a later
slice; the client seam already accepts an injected token).

**Consequences.** Same-origin API calls, zero CORS config, demo works logged-out; swapping
auto-login for real auth only touches `getToken()`. **Reversible?** Yes.

## D-0013 — Orchestration: LangGraph `StateGraph` with an inspectable per-node seam

**Date.** 2026-07-02 (P2-S10)

**Context.** Phase 2 needs the supervisor → scout → matcher → tailor → coverLetter flow expressed
as a real graph (the Phase-3 runtime target) while staying unit-testable without network or model
calls, and while honouring the approval gate.

**Decision.** `AetherGraph` builds a compiled `@langchain/langgraph` `StateGraph` over an
`Annotation`-typed state, *and* exposes `runNode(name, state)` — a direct, synchronous seam that
records a `GraphRunRecord` per invocation. Approval-gated nodes (`tailor`, `coverLetter`) return
`pending_approval` and halt the chain rather than acting. Tests exercise both the node seam and the
compiled graph.

**Alternatives.** Hand-rolled async pipeline (rejected: throws away LangGraph checkpointing and
interrupts we want in Phase 3). Only testing the compiled graph (rejected: per-node assertions and
run auditing get much noisier).

**Consequences.** +6 TS tests; `@langchain/langgraph` + `@langchain/core` added to
`packages/agents`. **Reversible?** Yes — nodes are plain functions; the graph wiring is one file.

## D-0014 — Volatile OpenRouter free-tier model ids: env-configured with automatic fallback chain

**Date.** 2026-07-09 (post-review hardening)

**Context.** An independent review found the live LLM agent endpoints returning 500: three of the
four configured OpenRouter free-tier model ids (`deepseek/deepseek-chat-v3-0324:free`,
`qwen/qwen-2.5-72b-instruct:free`, `meta-llama/llama-3.1-8b-instruct:free`) had been retired
upstream (HTTP 404). OpenRouter's free-tier catalogue is volatile — ids appear and disappear
without notice — so any hard-coded id will eventually rot.

**Decision.** Model ids stay configuration (`AETHER_MODEL_REASONING/STRUCTURED/FAST/LIGHT` env
vars, refreshed to currently-live ids: `openai/gpt-oss-120b:free`,
`qwen/qwen3-next-80b-a3b-instruct:free`, `meta-llama/llama-3.3-70b-instruct:free`,
`meta-llama/llama-3.2-3b-instruct:free`) and `LLMClient` gains a resilience chain in `auto` mode:
1. call the configured model; 2. on any failure (404/429/5xx/network/empty content) retry once
with `openai/gpt-oss-20b:free`; 3. fall back to the recorded fixture if one exists; 4. otherwise
raise a typed `LLMUnavailableError`, which the agents router maps to a clean **HTTP 503
"LLM backend unavailable"** — never an unhandled 500. Successful live calls record a fixture only
when none exists, so curated replay fixtures are never clobbered by variable live output. CI and
tests remain in `replay` mode.

**Alternatives.** Pinning to paid models (rejected: cost for a demo); querying the OpenRouter
`/models` catalogue at startup (rejected: adds a network dependency to boot and still races
mid-flight retirements); hiding failures by always serving fixtures (rejected: masks real outages).

**Consequences.** +7 pytest (`test_llm_resilience.py`) covering the fallback chain, fixture
fallback and the 503 contract; `FabricationGuard` no longer false-positives on sentence-initial
title-case words; the cover-letter agent gained a corrective drafting loop (≤3 attempts, feeding
flagged terms back to the model). **Reversible?** Yes — model ids are env vars; the fallback chain
is one method.


## D-0015 — Tailoring guard: evidence normalization instead of raw-verbatim token matching

**Context.** In production the tailoring agent returned `changes: 0` on every run: the
anti-fabrication validator in `resume_tailor.py` required every token of a rewritten bullet to
appear *verbatim* in the original bullet set. Any legitimate rewording — a unicode hyphen
(`e‑commerce` vs `e-commerce`), `≈92%` vs `92 percent`, `10,000` vs `10000`, `leading` vs `led`,
or a harmless stopword ("the", "of") — was flagged as fabrication, so the guard reverted every
bullet and the agent could never produce a tailored resume.

**Decision.** Novelty is now judged against a *normalized evidence index* built from the full
resume text (`_evidence_index` / `unsupported_tokens`):
1. **Unicode folding** — hyphen/dash/minus variants → `-`, curly quotes → `'`, `≈`/`∼` → `~`,
   `％` → `%`, nbsp/thin spaces → space, `…` → `...`, `×` → `x`;
2. **Case folding + light stemming** — suffix stripping (`ing`, `ed`, `er`, `est`, `es`, `ly`,
   `s`, `ies→y`) so inflectional variants of an evidenced word are accepted;
3. **Number-format equivalence** — numeric tokens compare by value after comma/format stripping,
   so `92%`, `≈92%` and `92 percent` are one fact;
4. **Stopword exemption** — function words and numeric qualifiers (`percent`, `approximately`,
   `roughly`, …) carry no factual claim and are never counted as novel.
A bullet is rejected (and reverted to the original) **iff** it still contains a content token
whose stem/value is absent from the resume evidence — new skills, tools, employers and metrics
are still rejected exactly as before.

**Alternatives.** Semantic-similarity scoring via the LLM (rejected: uses the very component the
guard must not trust); whitelisting per-bullet diffs by hand (rejected: unscalable); loosening the
guard to "reject only numbers" (rejected: would admit fabricated skills/tools).

**Consequences.** Tailoring now yields real accepted changes in production (verified live:
`changes: 22` with 3 genuinely-novel bullets rejected) while all negative fabrication tests still
pass. +11 pytest (`test_guard_normalization.py`) pin the accept/reject contract.
**Reversible?** Yes — the normalization pipeline is three pure functions in `resume_tailor.py`.


## D-0016 — Approval resolution propagates to the linked Application

**Context.** Phase-2 audit journey J4: approving or rejecting an `application_submit` approval
flipped only the `ApprovalRequest` row. The linked `Application` (FK `applicationId`) stayed in
`draft` forever, so the Applications kanban never reflected any decision (defect D2).

**Decision.** `ApprovalService.resolve()` now synchronises the linked application in the same
operation: **approve → `submitted`**, **reject → `rejected`**. The update is guarded with
`WHERE status = 'draft'` (and the owning `userId`) so a late decision can never regress an
application that already advanced (e.g. to `interview`), and approvals without an
`applicationId` are untouched.

**Alternatives.** A DB trigger (rejected: hides business logic in the schema); doing it in the
router (rejected: the service is the single resolution path and is also used by tests/agents);
an async job (rejected: adds a queue dependency for a two-row transaction).

**Consequences.** Approve/reject now has a visible, verified effect on the tracker — confirmed on
production with DB before/after snapshots (draft→submitted and draft→rejected). +2 pytest in
`test_approvals.py` pin the contract. **Reversible?** Yes — one static method call in `resolve()`.


## D-0017 — Hard wall-clock LLM budget, shared pipeline deadline, and provider override

**Context.** Phase-2 audit defect D1: cover-letter and pipeline runs hit the edge's ~100 s cut-off
(524). `AgentRun` rows recorded coverLetter calls of 133–157 s despite a declared 60 s budget —
httpx's read timeout is **per chunk**, so a model that keeps trickling tokens never times out.
In the pipeline, each agent's own `LLMClient` had an independent budget, so budgets stacked.

**Decision.** Three changes in `llm_client.py`:
1. **Hard cap** — live calls execute in a worker thread; `future.result(timeout=…)` abandons any
   call that exceeds the wall-clock budget, regardless of streaming behaviour.
2. **`shared_budget()`** — a contextvar-based deadline; the pipeline wraps its tailor+coverLetter
   dispatches so all LLM clients in scope share one budget instead of adding theirs up.
3. **Provider override** — `AETHER_LLM_BASE_URL`/`AETHER_LLM_API_KEY` point the agent layer at any
   OpenAI-compatible endpoint (e.g. Anthropic's `/v1` with Claude model ids via `AETHER_MODEL_*`),
   and `AETHER_MODEL_FALLBACK` makes the fallback model configurable. OpenRouter remains the
   default when unset.

**Alternatives.** Raising the edge timeout (rejected: not under our control and hides the bug);
async cancellation of the httpx stream (rejected: cancellation points depend on the server
yielding); background jobs + polling (valid future work, but a UX/API contract change out of
audit scope).

**Consequences.** On production, cover-letter runs complete in ≈60 s (HTTP 200) and the full
pipeline in ≈62 s — no 524s. The abandoned worker thread may linger until the provider closes the
socket (bounded, no user impact). +3 pytest in `test_llm_resilience.py`.
**Reversible?** Yes — env vars default to previous behaviour; the cap is one executor block.


## D-0018 — Root-resume ingestion endpoint + explicit resume selection for tailoring

**Context.** Section C of the Phase-2 audit required registering a second base resume (the BA/PO
variant, `assets/resume/Vik_Resume_BA_Final.pdf`) in the app so it appears in Resume Studio,
persists in the DB, and is tailorable. The API previously had no way to create a resume — the only
root resume was the demo-seeded one — and `TailoringAgent.run()` always tailored against
`ensure_base_resume()`, ignoring any other root.

**Decision.** Two additive API changes:
1. **`POST /resumes`** (`routers/resumes.py`) — creates a new **root** resume (no `parentId`) from
   `{label, raw_text, contact?, format_hash?}`. Sections are built server-side (`raw_text`,
   bullets via `extract_bullets`, contact); `format_hash` defaults to `sha256(raw_text)[:16]`;
   version comes from `repo.next_version(user_id)`. Returns 201 with the stored resume.
2. **`resume_id` selection** — `TailoringAgent.run(user_id, job_id, resume_id=None)`: when a
   `resume_id` is supplied (via the existing `POST /agents/tailor/run` body, whose
   `JobTargetRequest` gained an optional `resume_id`), the agent tailors against that resume
   (`get_by_id`, unknown id → 404); otherwise behaviour is unchanged (base resume).

**Alternatives.** Multipart PDF upload with server-side parsing (rejected for audit scope: heavier
surface, the PDF already lives in the repo and `scripts/ingest_ba_resume.py` extracts its text
deterministically); a `is_default` flag switch on resumes (rejected: changes existing tailor
semantics; explicit per-run selection is safer and reversible).

**Consequences.** BA resume registered on production as a root resume (id
`c57a44d136100943494554143`, version 15); a live tailoring run against it produced **20 accepted
changes** with a child resume inheriting the parent's `formatHash`. +4 pytest in
`tests/test_resume_ingest.py` (create, 422 validation, tailor-with-resume_id, 404 unknown id).
**Reversible?** Yes — both changes are additive; omitting `resume_id` reproduces prior behaviour.

## D-0019 — Swarm-directive conformance: real auth gate, 13-item nav, AU$ salaries, 30-min discovery timer
**Date:** 2026-07-12 · **Author:** Aether Delivery Agent (swarm directive execution) · **Status:** Adopted

**Context.** The aether-swarm execution directive audits production against its Section 5.4
success criteria. Five failed: SC-AUTH-03 (silent demo auto-login meant anyone with the URL saw
the workspace — BUG-013), SC-CL-02/SC-CC-07 (Cover Letter Studio absent from the sidebar),
SC-CL-01 (`/dashboard/cover-letter` fell through to the catch-all), SC-CC-05 (salaries rendered
bare `$`, not `AU$`), and SC-JOB-10 (no 30-minute scheduled discovery).

**Decision.**
1. `getToken()` no longer auto-logs-in with demo credentials; an unauthenticated browser session
   is redirected to `/login` and the request fails 401. A client-side `AuthGuard` wraps the
   dashboard layout. The `/login` form still prefills the demo account (demo environment).
2. **D-0002 amended:** the primary sidebar is now 13 items — "Cover Letter Studio"
   (`/dashboard/cover-letters`) sits between Resume Studio and Story Bank. The 2026-07-01
   rejection targeted a then-phantom screen; the workspace is now real.
3. `next.config.mjs` permanently redirects `/dashboard/cover-letter` → `/dashboard/cover-letters`.
4. Salary labels prefix `AU$` (or `US$` when `currency === "USD"`).
5. `aether-discovery.timer` (systemd, `OnCalendar=*:00/30`, logs to
   `/var/log/aether/discovery.log`) runs `scripts/discovery_cron.sh`: login → scout with the
   user's saved target role/location → fit-scorer. Runs are verifiable as AgentRun rows.

**Consequences.** REQ-05's "20 named agents" remains deliberately unmet at 7 agents: fabricating
13 non-existent agent cards would violate the directive's higher-priority constraint 2 (no
mock/simulated data in production UI). The registry shows exactly the agents that exist.

## D-0020 — Agents-screen truthfulness: env-derived providers, planned cards, real cost attribution, real ATS panel
**Date:** 2026-07-12 · **Author:** Aether Delivery Agent (swarm directive execution, phase 2) · **Status:** Adopted

**Context.** The second swarm-directive audit found the Agents screen surfacing fabricated data:
provider cards defaulted to "connected" with invented details ("Claude Pro · 45 messages
remaining", "$12.40 credit remaining") regardless of real credentials; 16 catalog entries with no
backend showed status "active"; run costs were priced against catalog-"recommended" models the
runtime never uses; the Test Run modal returned simulated "actual" figures (est × 0.97); and the
workflow graph mislabelled real agents (storyExtractor as "Learning", matcher as "Memory").
Resume Studio also never displayed an ATS score (SC-RS-05).

**Decision.**
1. Provider status/detail/models derive from the server env at request time
   (`_provider_env_state`): Anthropic = connected via the direct `AETHER_LLM_API_KEY`
   subscription token on api.anthropic.com (SC-AG-05 — never via OpenRouter); OpenRouter =
   connected-standby (key present); OpenAI/Gemini/Groq/Bedrock = unconfigured (no keys). A user
   override can only downgrade, never fabricate a connection; PUT returns 409 when marking a
   keyless provider connected. The stale fabricated "gemini connected" row was deleted.
2. Catalog entries without a backend are status "planned" (roadmap cards, dimmed, no toggle) —
   21+1 named cards satisfy REQ-05's spirit while constraint 2 bars fake activity. A new "Story
   Extraction Agent" card owns the real storyExtractor; "Learning / Feedback" is honestly planned;
   "Orchestration" maps to the real supervisor node.
3. Run costs bill the model the agent ACTUALLY uses (tailor/coverLetter → AETHER_MODEL_REASONING
   = claude-fable-5 at $10/$50 per MTok; storyExtractor → STRUCTURED = claude-haiku-4-5 at $1/$5);
   deterministic agents (scout, fitScorer, matcher, supervisor) record zero LLM spend. Test Run
   "actual" figures come from the last real completed run (null if never run).
4. The workflow graph shows the real 7-agent topology in pipeline order.
5. `GET /resumes/{id}/ats` scores a version against its source job with the deterministic ATS
   engine; Resume Studio shows the breakdown panel for tailored versions (SC-RS-05).

**Consequences / accepted deviations.** SC-RS-06 (AI-Detection %) is NOT implemented — no honest
measurement exists without a third-party detector, and an invented percentage violates
constraint 2. SC-AG-08/REQ-10 (Langfuse) and Gmail OAuth (SC-EC-02+, SC-AUTH-04) remain blocked on
credentials/interactive consent. SC-ST-05 is partial: per-agent model preference persists but the
runtime stays pinned to the validated Anthropic tiers.
