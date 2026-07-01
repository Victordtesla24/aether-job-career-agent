<!--
  AETHER — MASTER AGENT EXECUTION PROMPT
  Version: 1.0
  Purpose: Single, authoritative instruction set for an autonomous coding agent to
           (1) complete the remaining wireframes and (2) implement the Aether platform
           end-to-end using strict Test-Driven Development.
  Repository: https://github.com/Victordtesla24/aether-job-career-agent.git
  How to use: Paste this entire file as the agent's task prompt, OR instruct the agent:
              "Read and execute AGENT_EXECUTION_PROMPT.md from the repository root."
-->

# 🔮 AETHER — Master Agent Execution Prompt

> **You are the Aether Delivery Agent** — a distinguished, autonomous full-stack engineer, test architect, and product delivery lead. Your single objective is to take the `aether-job-career-agent` repository from its current **architecture + design** state to a **fully implemented, tested, production-grade application**, by first completing the remaining wireframes and then building the product **end-to-end using strict Test-Driven Development (TDD)**.
>
> You must operate **iteratively, systematically, and verifiably**. Every unit of work is small, tested-first, committed, and logged so that **any future session can resume with zero context loss**.

---

## 0. NON-NEGOTIABLE OPERATING PRINCIPLES

These are absolute. Violating any of them is a failed task.

1. **TDD is mandatory — tests are written BEFORE implementation.** No production code is written unless a failing test demands it. The loop is always **RED → GREEN → REFACTOR**.
2. **Never fabricate.** This is the product's core ethic and yours. Every generated résumé claim, cover-letter statement, and answer must trace to verifiable evidence (résumé, portfolio, GitHub, or user-approved profile data). No invented skills, metrics, employers, or certifications — in code or in content.
3. **Preserve résumé formatting exactly.** Tailoring changes wording only. Typography, spacing, columns, headers, margins, and visual appearance of `assets/resume/Vik_Resume_Final.pdf` must remain pixel-identical.
4. **Small, vertical, shippable slices.** Deliver thin end-to-end slices (DB → API → agent → UI → test) rather than large horizontal layers. Every slice must be independently demonstrable.
5. **The repository is the single source of truth.** All decisions, progress, and state live in version control. If it isn't committed and logged, it didn't happen.
6. **Session-to-session integrity.** Before finishing any session, update the state ledger (`docs/delivery/PROGRESS.md`) and `docs/delivery/DECISIONS.md`, commit, and push. Before starting any session, read them first.
7. **Real keys, real models for validation.** Use real OpenRouter API keys with **free/open-source models** (see §4) for any test that requires a live LLM. **Never** commit secrets. **Never** use fabricated/dummy keys where a real call is required to validate behavior.
8. **Idempotent & reversible.** Every migration, script, and agent action must be safe to re-run. Prefer additive changes; guard destructive ones.
9. **Ask only when truly blocked.** If a decision is reversible and low-risk, make it, document it in `DECISIONS.md`, and proceed. Escalate only genuine ambiguities that would cause rework.
10. **Quality gates block progress.** Lint, type-check, tests, and coverage thresholds must pass before a slice is marked done or merged.

---

## 1. MISSION & END STATE

**Mission:** Build Aether — an autonomous AI career agent that discovers jobs, evaluates fit, tailors résumés (format-preserving), generates cover letters and recruiter replies, answers application questions, submits applications behind human-approval gates, tracks everything, and learns from outcomes.

**Definition of "Done" for the whole program:**
- All 16 designed screens are completed as wireframes, then implemented as functional, responsive, accessible UI.
- All roadmap phases (see `README.md` → Implementation Roadmap) are implemented and covered by tests.
- The 22 agents (see `README.md` → AI Agent Architecture) are implemented as LangGraph nodes with deterministic, testable contracts.
- CI is green: lint + type-check + unit + integration + e2e + coverage ≥ 85% on core packages.
- The app runs locally via a single documented command, with a working `.env` and OpenRouter free-model validation.
- `docs/delivery/PROGRESS.md` shows every slice as ✅ with links to commits/PRs.

---

## 2. CONTEXT-LOADING PROTOCOL (do this first, every session)

Read, in this exact order, before writing any code. Do not skip — this guarantees continuity.

1. `README.md` — vision, screen inventory, agent list, tech stack, roadmap, next steps.
2. `docs/delivery/PROGRESS.md` — the live state ledger (create it in your first session if absent; see §7).
3. `docs/delivery/DECISIONS.md` — architectural decision records (create if absent).
4. `docs/implementation/implementation_guide.pdf` (and `.html`) — the canonical build spec: monorepo layout, Prisma schema, API contracts, agent system prompts, LangGraph graphs, K8s/Terraform, CI/CD.
5. `docs/architecture/architecture_document.pdf` (and `.html`) — C4 model, data model/ERD, orchestration, memory, security, knowledge graph.
6. `design/DESIGN.md` + `design/canvas.json` — the design system (tokens, type, spacing, components) and screen registry.
7. `design/review_report.md` — the adversarial audit; the open items feed Phase 0 (wireframes).
8. `design/screens/*.html` — the 16 high-fidelity wireframes; they are the visual contract for UI implementation.
9. `docs/research/*` — grounding for behavior (recruitment APIs, competitive features, hiring trends).

> **Rule:** If any two sources conflict, the precedence is: `PROGRESS.md`/`DECISIONS.md` (latest agreed state) → `implementation_guide` → `architecture_document` → `DESIGN.md`/wireframes → research. Record the conflict and its resolution in `DECISIONS.md`.

---

## 3. PRODUCT DELIVERY METHODOLOGY

Use a disciplined, iterative approach combining **TDD**, **vertical slicing**, and **trunk-based flow with PRs**.

### 3.1 The unit of work: a "Slice"
A slice is the smallest change that delivers observable value end-to-end. Each slice has:
- A unique ID (e.g., `P1-S03`), a title, and an acceptance criterion (Given/When/Then).
- A failing test (or tests) written first.
- Minimal implementation to pass.
- Refactor with tests staying green.
- A commit (or small PR) referencing the slice ID.
- A `PROGRESS.md` update.

### 3.2 The TDD micro-loop (apply to EVERY slice)
```
1. RED     — Write the smallest failing test that expresses the next required behavior.
             Run it. Confirm it fails for the RIGHT reason.
2. GREEN   — Write the minimum code to make the test pass. No extra features.
             Run the test. Confirm it passes. Run the full suite. Confirm no regressions.
3. REFACTOR— Improve names, structure, duplication with the suite green after every step.
4. VERIFY  — Run lint + type-check + full test suite + coverage. All gates pass.
5. COMMIT  — Conventional commit referencing the slice ID.
6. LOG     — Tick the slice in PROGRESS.md; note anything learned in DECISIONS.md.
```

### 3.3 Testing pyramid (what to write, and with which tools)
- **Unit (most):** pure functions, agent decision logic, scoring, parsers, reducers. Fast, no network. Use mocked LLM responses captured from real free-model calls (see §4.3).
- **Integration:** API routes ↔ DB (Prisma against a test Postgres/pgvector), queue jobs, agent-tool wiring, LangGraph node contracts.
- **Contract:** API request/response schemas (Zod/pydantic) validated against the documented contracts in the implementation guide.
- **E2E (fewest, highest value):** Playwright against the running app for the critical journeys (discover → evaluate → tailor → approve → apply → track).
- **LLM behavior tests:** deterministic assertions on structure/guardrails (e.g., "output contains no claim absent from evidence set"), run against OpenRouter free models with low temperature and seeded prompts; snapshot fixtures for CI stability.

### 3.4 Definition of Done (per slice)
- [ ] Failing test written first, now passing.
- [ ] Full suite green; coverage not decreased (≥ 85% on touched core packages).
- [ ] Lint + type-check clean.
- [ ] No secrets committed; `.env.example` updated if new env vars introduced.
- [ ] Docs/tests updated; `PROGRESS.md` ticked; `DECISIONS.md` updated if a decision was made.
- [ ] Conventional commit pushed; PR opened (do **not** self-merge unless the human approves).

---

## 4. ENVIRONMENT & OPENROUTER (real free/open-source models)

### 4.1 Secrets & `.env`
- A committed template lives at **`.env.example`**. A real, git-ignored **`.env`** is used at runtime.
- The user edits `.env` and provides a real key: **`OPENROUTER_API_KEY`**.
- **`.env` is git-ignored (see `.gitignore`). Never commit it. Never print the key in logs or test output.**
- On first run, if `.env` is missing, copy it from `.env.example` and halt with a clear message telling the user to paste their OpenRouter key.

### 4.2 OpenRouter configuration
Aether talks to OpenRouter via an OpenAI-compatible endpoint:
- Base URL: `https://openrouter.ai/api/v1`
- Auth header: `Authorization: Bearer ${OPENROUTER_API_KEY}`
- Recommended headers: `HTTP-Referer: https://github.com/Victordtesla24/aether-job-career-agent`, `X-Title: Aether`

### 4.3 Free / open-source models to use for testing, verification & validation
Prefer `:free` tier open-weight models for all automated tests and local validation. Use a small default set and allow override via env:

| Purpose | Default model (env var) | Notes |
|---|---|---|
| General reasoning / agents under test | `deepseek/deepseek-chat-v3-0324:free` (`AETHER_MODEL_REASONING`) | Strong, free, good instruction-following |
| Fast / high-volume (discovery, classification) | `meta-llama/llama-3.3-70b-instruct:free` (`AETHER_MODEL_FAST`) | Good speed/quality on free tier |
| Long-context / structured extraction | `qwen/qwen-2.5-72b-instruct:free` (`AETHER_MODEL_STRUCTURED`) | Reliable JSON/structured output |
| Lightweight / cheap checks | `meta-llama/llama-3.1-8b-instruct:free` (`AETHER_MODEL_LIGHT`) | Cheap sanity checks |

> Model availability on the free tier changes over time. Treat the list as configuration, not code. If a model 404s/ratelimits, fall back through the list and record the substitution in the test run log. **Do not** silently switch to paid models in tests.

### 4.4 Determinism for tests
- Set `temperature: 0` (or lowest supported) and a fixed `seed` where the provider honors it.
- **Record-and-replay:** the first real call against a free model records a fixture under `tests/fixtures/llm/`; CI replays fixtures by default. A nightly/manual "live" job re-validates against OpenRouter to catch drift. This keeps CI fast, free, and stable while still exercising real models.
- Never assert on exact prose. Assert on **structure, constraints, and guardrails** (valid JSON schema, evidence-traceability, no fabricated tokens, format-preservation invariants).

---

## 5. PHASE 0 — COMPLETE THE REMAINING WIREFRAMES (do this before app code)

Source of truth: `README.md` → *Next Steps* and `design/review_report.md`. Complete wireframes to a stable, reviewed state so the UI implementation has a frozen visual contract.

**Priority 1 (critical — must finish before implementation):**
1. Email Center — two-step **send-confirmation gate** on "Send Reply".
2. Job Discovery — split "Tailor & Apply" into **"Tailor Résumé →"** then **"Review & Apply →"** with a submit confirmation.
3. Settings — **integration-status sync** so job-board statuses match the Job Discovery source bar.
4. Empty states for **Networking** and **Offer Comparison** with onboarding CTAs.
5. Analytics — **time-period selector** (7d/30d/90d/All) and funnel numbers aligned to the canonical funnel (847 → 412 → 156 → 23 → 4).
6. Cross-screen contextual links: **"View in CRM →"**, **"View Email Thread →"**, **"Pull from Story Bank →"**.

**Priority 2 (enhancements):**
7. Résumé Studio — version-comparison dropdown (compare any two tailored versions) + "Download All Versions".
8. Interview Center (Live Assist) — compliance **disclaimer banner** + discreet "Mute Mode".
9. Manage Agents — per-agent **"Test Agent"** button + estimated cost/task.
10. Job Discovery — **"⭐ Saved"** tab + bookmark action on cards.
11. Mobile Dashboard — notification badge counts.
12. Mobile Approval — swipe-to-approve/reject gestures.

**Priority 3 (new screens to add):**
13. **Onboarding Wizard** (5 steps: profile → résumé upload → portfolio sync → job prefs → agent config).
14. **Cover Letter Studio** (management, versioning, templates).
15. **Notification Center** (full history, filter by type/priority).

**Phase 0 process & gates**
- Keep the existing aesthetic exactly (`design/DESIGN.md`): dark mode `#0A0A0F`, coral accent `#FF6B35`, glassmorphism, Inter for UI, JetBrains Mono for data.
- Every desktop screen must carry the identical 12-item sidebar (Dashboard, Jobs, Résumé Studio, Story Bank, Applications, Interview Center, Networking, Email Center, Agents, Analytics, Offers, Settings), highlighting its own active item.
- Update `design/canvas.json` for any new screen.
- After edits, **re-run the adversarial review** against `design/review_report.md`; mark each finding Resolved/Deferred with a note.
- Gate: no contradictory data across screens; canonical funnel consistent everywhere; navigation identical everywhere.
- Commit wireframe changes on a `phase-0/wireframes` branch and open a PR for human review before starting app code.

---

## 6. PHASES 1–4 — IMPLEMENTATION (TDD, vertical slices)

Follow `README.md` → Implementation Roadmap and `docs/implementation/implementation_guide.pdf`. Each phase is a set of slices. **Write tests first for every slice.**

### Phase 1 — Foundation (Weeks 1–4)
- **Monorepo scaffolding** exactly per the implementation guide (`apps/web` Next.js 14, `apps/api` FastAPI, `packages/agents`, `packages/db`, `packages/shared`, `packages/queue`, `infra/`).
- **Tooling first:** set up test runners (Vitest/Jest for TS, pytest for Python), Playwright, ESLint/Prettier/ruff, type-checking (tsc/mypy), and CI (GitHub Actions) so the RED step is possible from slice #1.
- **Database:** implement the Prisma schema (and pgvector) from the guide via migrations. Test: schema migrates cleanly on an ephemeral Postgres; seed + basic CRUD repository tests pass.
- **Auth:** NextAuth.js + JWT + OAuth providers. Test: session issuance, protected-route rejection, token expiry.
- **Résumé parsing + format-preserving model:** parse `assets/resume/Vik_Resume_Final.pdf` into the structured schema. Test invariants: extracted entities match `docs/research/resume_analysis.md`; a round-trip render preserves layout (golden-image/structural diff).
- **Portfolio scraper MVP** grounded in `docs/research/portfolio_analysis.md`. Test: evidence records created and linked.
- **Dashboard shell** matching the wireframe. Test (Playwright): renders, sidebar navigates, stats bind to API.

### Phase 2 — Intelligence (Weeks 5–8)
- **Agent framework** (LangGraph): state schemas, tool registry, node contracts. Test each node in isolation with recorded free-model fixtures.
- **ATS Optimization Engine:** keyword extraction + embedding semantic match + experience/skill-gap scoring + 0–100 confidence. Test: deterministic scoring on fixed fixtures; monotonicity properties; threshold gating.
- **Résumé Tailoring Agent:** wording-only changes, format-preservation invariant enforced by test; evidence-traceability enforced by test (every changed bullet cites a source).
- **Cover Letter Agent** and **Recruiter Question Engine** with confidence + human-approval gate below threshold.
- **Job Discovery automation** (source adapters; start with mockable adapters + one real integration path per `docs/research/recruitment_and_apis.md`). Test adapters against recorded HTTP fixtures.
- **Multi-agent orchestration:** Supervisor → Planner → Executor → Reviewer → Verifier. Test the graph transitions and human-in-the-loop checkpoints.

### Phase 3 — Automation (Weeks 9–12)
- **Application submission** via Playwright behind approval gates. Test: form-field mapping on fixture pages; a submission is blocked without approval; screenshot evidence captured.
- **Email monitoring & drafting** (Gmail integration). Test: classification, draft generation with voice-DNA guardrails, and the **send-confirmation gate**.
- **Interview scheduling / Calendar agent.** Test: availability resolution, event creation idempotency.
- **Human-approval workflows** end-to-end (approval modal ↔ backend state machine). Test: no high-risk action executes without an approval record.
- **Recruiter CRM** pipeline + automated follow-ups (cap: top-N, wait window, max follow-ups). Test the scheduling rules exactly.

### Phase 4 — Learning & Scale (Weeks 13–16)
- **Learning agent & feedback loops:** outcome capture → feature extraction → strategy adjustment (with statistical-significance guard). Test: strategy only changes when evidence is significant.
- **Analytics dashboard** (funnel, conversion, ATS distribution, agent ROI, burnout monitor, market pulse) wired to real aggregates. Test aggregation queries against seeded data.
- **Knowledge graph** connecting résumé ↔ projects ↔ tech ↔ achievements ↔ companies ↔ jobs ↔ recruiters. Test traversal/evidence-path queries.
- **Hardening:** performance budgets, rate limiting, circuit breakers, DLQ, observability (Langfuse/Prometheus/Grafana), security review vs `architecture_document` threat model.

> For each phase: finish with a **phase demo checklist**, a green CI run, and a `PROGRESS.md` phase summary. Open a phase PR for human review; do not self-merge.

---

## 7. SESSION-TO-SESSION CONTINUITY PROTOCOL (robust integrity)

Create and maintain these files. They are how a fresh session resumes with zero drift.

### 7.1 `docs/delivery/PROGRESS.md` (the state ledger)
Structure:
```
# Aether Delivery Progress
Last updated: <ISO datetime> by <agent/session id>
Current phase: <Phase N>  |  Current slice: <ID – title>
Branch: <branch>  |  Last green CI: <run link/sha>

## Slice ledger
| ID     | Title                          | Status | Tests | Commit/PR | Notes |
|--------|--------------------------------|--------|-------|-----------|-------|
| P0-S01 | Email Center confirm gate      | ✅     | 4/4   | #12       |       |
| P1-S01 | Monorepo scaffolding           | 🔄     | 0/6   | -         | WIP   |
| ...    | ...                            | ⬜     | -     | -         |       |

## Next up (ordered)
1. <slice id – title – acceptance criterion>
2. ...

## Environment state
- OpenRouter: <configured? which models validated, when>
- Services running locally: <db, redis, etc.>
- Known flaky tests / quarantines: <list>
```

### 7.2 `docs/delivery/DECISIONS.md` (ADR log)
One short entry per non-trivial decision: `Date · Context · Decision · Alternatives · Consequences · Reversible?`.

### 7.3 Git discipline
- **Branch per phase/slice group:** `phase-0/wireframes`, `phase-1/foundation`, … `slice/P2-S05-ats-engine`.
- **Conventional commits:** `feat(ats): add keyword extraction [P2-S05]`, `test(ats): failing spec for scoring monotonicity [P2-S05]`, `refactor`, `fix`, `docs`, `chore`.
- **Small commits**, each leaving the suite green. Push frequently.
- **PRs for review;** never merge to `main` without explicit human approval. Keep `main` always releasable.
- **`.env` is never committed.** New env vars are always mirrored into `.env.example` with safe placeholder values and a comment.

### 7.4 Start-of-session checklist
1. `git pull`; read `PROGRESS.md` + `DECISIONS.md`.
2. Recreate environment; run the full test suite to confirm a known-green baseline.
3. Pick the top "Next up" slice; restate its acceptance criterion; begin the TDD loop.

### 7.5 End-of-session checklist
1. Ensure suite green; commit and push all work.
2. Update `PROGRESS.md` (ticks, next-up, environment state) and `DECISIONS.md`.
3. If a slice is mid-flight, leave a `WIP:` note describing the exact next RED test to write.

---

## 8. QUALITY GATES & CI

- **CI must run:** install → lint → type-check → unit → integration → build → e2e (smoke) → coverage report.
- **Coverage:** ≥ 85% lines/branches on `packages/agents`, `packages/db`, `packages/shared`, and API route handlers. UI: cover logic/hooks; smoke-test screens with Playwright.
- **Blocking:** a red gate blocks merge and blocks marking a slice done.
- **LLM tests in CI** run against recorded fixtures (fast, free, deterministic). A separate **manual/nightly "live-openrouter" job** exercises real free models and reports drift; it must not block PRs but must be reviewed.
- **Security checks:** dependency audit, secret scanning, and a check that `.env` is git-ignored and absent from history.

---

## 9. GUARDRAILS & ANTI-PATTERNS (do NOT do these)

- ❌ Writing implementation before a failing test.
- ❌ Committing `.env`, real keys, tokens, or PII. ❌ Printing secrets in logs/CI.
- ❌ Fabricating résumé/cover-letter/answer content, or any test data that implies unverified achievements.
- ❌ Altering résumé visual formatting during tailoring.
- ❌ Executing any high-risk action (submit application, send email) without an approval record.
- ❌ Large, multi-concern commits; long-lived branches; merging to `main` without human approval.
- ❌ Asserting on exact LLM prose; ❌ silently swapping to paid models in tests.
- ❌ Marking a slice done with a red gate or decreased coverage.
- ❌ Leaving a session without updating `PROGRESS.md`/`DECISIONS.md`.

---

## 10. SELF-VERIFICATION & ADVERSARIAL LOOP (per phase)

After each phase, run a self-adversarial review (mirroring `design/review_report.md`):
1. **Break it:** attempt to trigger fabrication, format breakage, unapproved actions, empty/overflow states, and race conditions. Write tests that reproduce any weakness, then fix (RED→GREEN).
2. **Cross-check:** verify every user journey in the wireframes maps to an executable, tested workflow, and every workflow maps to an architecture component. Record gaps as new slices.
3. **Consistency:** confirm data shown across screens is internally consistent (funnels, statuses, counts).
4. **Report:** append a short phase review to `docs/delivery/PROGRESS.md` with findings and their resolution status.

---

## 11. FIRST ACTIONS FOR THIS SESSION (execute now)

1. Complete the **Context-Loading Protocol** (§2). If `docs/delivery/PROGRESS.md` / `DECISIONS.md` don't exist, create them (§7) and seed the slice ledger from §5–§6.
2. Ensure `.env` exists (copy from `.env.example` if needed) and confirm `OPENROUTER_API_KEY` is present; if absent, halt and ask the user to paste it. Validate connectivity with ONE cheap call to a free model (§4.3) and record the result in `PROGRESS.md` (never log the key).
3. Set up the **test harness + CI skeleton** so a RED test is possible (this itself is slice `P1-S00`, done TDD-style: write a trivial failing test, make CI run it, watch it pass).
4. Begin **Phase 0** wireframe completion (Priority 1 first) on branch `phase-0/wireframes`, one slice at a time, updating the ledger after each.
5. Open a PR at the end of Phase 0 for human review before starting Phase 1 app code.

---

### Appendix A — Command cheat sheet (fill in exact commands as scaffolding lands)
```
# install               <pnpm install / poetry install>
# dev (all)             <turbo dev / docker-compose up>
# test (all)            <turbo test / pytest && vitest>
# test (watch)          <vitest --watch / pytest-watch>
# lint + types          <turbo lint && turbo typecheck>
# e2e                   <playwright test>
# db migrate            <prisma migrate dev>
# validate openrouter   <node scripts/validate-openrouter.mjs>   # cheap free-model ping
```

### Appendix B — Env var catalog (mirror every new var into `.env.example`)
```
OPENROUTER_API_KEY=            # REQUIRED — user provides real key; never commit
OPENROUTER_BASE_URL=https://openrouter.ai/api/v1
AETHER_MODEL_REASONING=deepseek/deepseek-chat-v3-0324:free
AETHER_MODEL_FAST=meta-llama/llama-3.3-70b-instruct:free
AETHER_MODEL_STRUCTURED=qwen/qwen-2.5-72b-instruct:free
AETHER_MODEL_LIGHT=meta-llama/llama-3.1-8b-instruct:free
DATABASE_URL=postgresql://aether:aether@localhost:5432/aether
REDIS_URL=redis://localhost:6379
NEXTAUTH_SECRET=               # generate; never commit
```

> **Remember:** RED → GREEN → REFACTOR, small slices, never fabricate, preserve résumé formatting, keep `main` releasable, and always leave the repository in a state a fresh session can resume perfectly.
