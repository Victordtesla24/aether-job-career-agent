# Aether Delivery Progress
Last updated: 2026-07-02 by Aether Delivery Agent Session 3 (Phase 2)
Current phase: Phase 2 — Intelligence (in progress)  |  Current slice: P2-S01 complete; P2-S02 next
Branch: phase-2/intelligence  |  CI: unchanged from Phase 1 (`.github/workflows/ci.yml` mirror at `ci/github-actions-ci.yml`)

## Phase 2 — Intelligence (in progress)
Strict TDD (RED → GREEN → REFACTOR), small vertical backend slices, conventional commits per slice on
`phase-2/intelligence`, pushed to `origin` after each slice. `main` is untouched. No secrets committed;
the résumé PDF (`assets/resume/Vik_Resume_Final.pdf`) is read-only and never modified — its
`format_hash` prefix `0700d1aa` is pinned and must never change.

> **Branch base (important).** The Phase 2 spec assumed Phase 1 was merged to `main`, but it was not —
> `main` still holds only Phase 0 (wireframes). The Phase 1 foundation lives on the unmerged remote
> branch `phase-1/foundation`. Accordingly `phase-2/intelligence` was branched **from
> `phase-1/foundation`, not from `main`**, so Phase 2 builds on the real foundation. See DECISIONS
> D-0010. Phase 1 should still be reviewed & merged to `main` on its own track; the eventual Phase 2 PR
> will target `main` once Phase 1 lands (or be retargeted/rebased as directed).

### Phase 2 Slice Ledger
| ID      | Title                                       | Status | Tests    | Commit    | Notes |
|---------|---------------------------------------------|--------|----------|-----------|-------|
| P2-env  | Prisma baseline migration (Phase 1 schema)  | ✅     | n/a      | `368493c` | phase-1/foundation had schema.prisma but no committed migration; baseline added so DB provisions reproducibly (all P1 tables + pgvector) |
| P2-S01  | User repo + real auth (bcrypt + JWT)        | ✅     | 7/7 (py) | `4d1c166` | `/auth/register` (bcrypt, 201, no hash leak, 409 dup, 422 weak) + `/auth/login` (JWT userId/email/iat/exp 24h) + `get_current_user` Bearer guard; protected `GET /jobs`; web NextAuth wired to real backend; TS `UserRepository.create` |
| P2-S02  | Job discovery adapters + persistence        | ⬜     | —        | —         | seek/linkedin/indeed adapters + JobRepository + jobs router |
| P2-S03  | ATS scoring engine (TF-IDF + embeddings)    | ⬜     | —        | —         | deterministic 0–100 |
| P2-S04  | FitScorer agent                             | ⬜     | —        | —         | wires ATS engine to Job rows |
| P2-S05  | Resume tailoring agent (LLM + guard)        | ⬜     | —        | —         | evidence-traced; replay-mode until real key |

### Phase 2 Environment State
- Postgres 17 + pgvector 0.8.3 running locally (databases `aether` + `aether_test`); Prisma migrations
  applied to both. Python services use raw `psycopg2` over the Prisma-migrated schema (DECISIONS D-0013).
- `.env` present locally and git-ignored (never committed); `.env.example` updated with Phase 2 vars.
- **OpenRouter: PENDING A REAL KEY.** No live `OPENROUTER_API_KEY` was available in this session
  (`.env` holds a placeholder), so `scripts/validate-openrouter.mjs` reports "not set" and live LLM
  calls cannot be exercised here. Phase 2 LLM work (P2-S05+) therefore runs in **replay mode**
  (`AETHER_LLM_MODE=replay`) against recorded/deterministic fixtures, and the fabrication guardrails are
  enforced in code (independent of any model output) so correctness does not depend on the key. **Action
  for the user:** provide a valid OpenRouter key to run the online record pass + connectivity validation.
- Auth deps pinned: `bcrypt==4.0.1` (passlib 1.7.x is incompatible with bcrypt ≥4.1).

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
