# Aether Delivery Progress
Last updated: 2026-07-02 by Aether Delivery Agent Session 2
Current phase: Phase 1 — Foundation  |  Current slice: FastAPI skeleton + `/health` (P1-S09, next)
Branch: phase-1/foundation  |  CI: to be activated at `.github/workflows/ci.yml` this phase (slice P1-S10)

## Phase 1 — Foundation (in progress)
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
| P1-S09  | FastAPI skeleton + `/health`                      | ⬜     | -     | -         |
| P1-S10  | CI activation (`.github/workflows/ci.yml`)        | ⬜     | -     | -         |
| P1-S11  | LLM fixture record-replay infra                   | ⬜     | -     | -         |

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

---

## Phase 0 — Wireframes (complete, merged to `main`)

## Workflow (per user directive)
One branch per phase. Work stays on that single branch until the phase is complete, then:
**independent review + verification + adversarial review → incorporate feedback → merge to `main`** — only then is the next phase's branch opened. CI-CD is kept deliberately simple: the GitHub Actions workflow is version-controlled at `ci/github-actions-ci.yml` (not under `.github/workflows/`) so pushes/merges need no special GitHub App `workflows` permission.

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
