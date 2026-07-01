# Aether Delivery Progress
Last updated: 2026-07-02 by Aether Delivery Agent Session 2
Current phase: Phase 1 — Foundation  |  Current slice: monorepo scaffolding + core packages (in progress)
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
| P1-S03  | NextAuth.js + JWT + requireAuth middleware        | ⬜     | -     | -         |
| P1-S04  | Resume parser (pdfplumber, format-preserving hash)| ⬜     | -     | -         |
| P1-S05  | Portfolio/GitHub scraper MVP (fixture-backed)     | ⬜     | -     | -         |
| P1-S06  | Dashboard shell (12-item Schema-A sidebar)        | ⬜     | -     | -         |
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
