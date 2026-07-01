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
