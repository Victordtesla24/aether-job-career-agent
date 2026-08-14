# ORCH-B1 BLUEPRINT — U-AGI kernel + Directed Improvement (B1a / B1b / B1c)

**Author** arch sub-agent (design only — no production fix code written by this task)
**Date** 2026-08-14
**Design tree (read)** `/home/ubuntu/github_repos/aether-wt-orch-exec` — branch `orch/exec-20260814` @ `7be085a` (merge of `origin/main` @ `12945bc`)
**Production** https://5cb5f0620.abacusai.cloud — health `200 {"status":"ok","version":"0.2.0"}` @ 2026-08-14 (this session)
**Status** DRAFT — **requires explicit fable-5 orchestrator approval before ANY implementation begins.**

## Epistemic tagging contract

Every factual claim carries exactly one tag. Untagged assertions are a defect in this document.

- `[VERIFIED-WITH-SOURCE]` — read in the code/DB/live-endpoint **this session**, at the stated file:line or via the stated query. Line numbers are from the design tree at `7be085a` unless another tree is named.
- `[INFERRED]` — a conclusion derived from tagged facts; the derivation is stated inline.
- `[ASSUMED-PENDING-PROBE]` — not established; the probe that would settle it is named.

All file paths are absolute or repo-relative to the design tree. No secret value appears anywhere in this document; credential material was checked **by name and by count only**.

---

## 0. Executive summary

### 0.0 The finding that changes the shape of this ticket

**B1a is already built. It is uncommitted, on disk, in another worktree, and the backlog does not know.**

`/home/ubuntu/github_repos/aether-wt-uagi-p1a` (branch `feat/uagi-p1a`) holds a complete, TDD'd implementation of ADR-AGI-3 P1-A: 4 modified backend files (+942/−31), 4 new source files, 6 pytest suites (~114 test functions, 2,084 lines), and a build record at `uat/reports/evidence/market-perf/u-agi/p1a/BUILD-P1A.md` dated 2026-08-14T14:05Z with green GATE-A / GATE-B / GATE-C artifacts. `[VERIFIED-WITH-SOURCE: worktree inventory + BUILD-P1A.md + GATE-*.txt, this session]`

The branch `feat/uagi-p1a` has **zero commits of its own** — its HEAD is `361f021`, an ordinary ancestor of `origin/main`. `[VERIFIED-WITH-SOURCE: `git branch -a --contains feat/uagi-p1a` returns ten branches including `main`]` So the reconciliation recon, which read merged state only, recorded:

> `| B1 U-AGI kernel | … merged feat/uagi-p1a contained **no backend work** | MISSING | Full P1 build … |`
> — `docs/delivery/ORCH-DELTA-2026-08-14.md:23` `[VERIFIED-WITH-SOURCE]`

That verdict is **true about the merged tree and false about the working tree**. Commissioning "Full P1 build" as written would have a fresh implementer re-derive ~2,000 lines that already exist and pass their gates. `[INFERRED — from the two verified facts above]`

Consequently **B1a in this blueprint is scoped as _reconcile, correct, land, and finish_** — not as a from-scratch build. The parts of the parent scope that P1-A genuinely did **not** do are called out in §0.2 and are the real work.

### 0.1 What the three tickets are, after reconciliation

| Ticket | Real scope after reconciliation | Size |
|---|---|---|
| **B1a** | Rebase and land the existing P1-A working tree, after (a) an independent R-8 re-verification of all 19 charter rows — §1, (b) three corrections this review found — §0.3, (c) the supervisor-stub replacement P1-A skipped — §4.1, (d) composition with B6 and D.524 — §0.4. | Medium (mostly review + 3 targeted changes) |
| **B1b** | **Genuinely unbuilt.** `grep -rn AgentDirective` across every worktree and the main clone returns **zero hits**. `[VERIFIED-WITH-SOURCE]` Full build: table, whitelist, clamp, ratchet, rules-stage evaluation, injection, endpoint, FE display. | Large |
| **B1c** | **Genuinely unbuilt, and on clean runway** — `apps/api/app/agents/story_extractor.py` is unmodified in *every* worktree. `[VERIFIED-WITH-SOURCE]` Knob consumption + one bounded corrective loop + learning signal. | Medium |

### 0.2 What P1-A did NOT do (this is B1a's real work)

1. **The supervisor stub is untouched.** `agents.py:3406-3409` is still `_record_run(user_id, "supervisor", params, lambda: {"plan": list(_PIPELINE_PLAN)})` in the P1-A tree, byte-identical to the design tree. `[VERIFIED-WITH-SOURCE: P1-A `git diff` has no hunk within 150 lines of `_pipeline_core`]` P1-A added a *parallel* planner reachable only from the new endpoints. **Two plan concepts now coexist and one of them still lies.** The parent scope explicitly requires "no stub".
2. **The R-8 gate was not applied.** BUILD-P1A.md §preamble states: *"The charter table was taken VERBATIM from `EXEC-CLASSES.md` §6 as instructed — not re-derived."* `[VERIFIED-WITH-SOURCE]` ADR-AGI-3 Decision 1 says *"EVERY row is re-verified from code evidence (file:line) before it becomes charter data. No exceptions."* `[VERIFIED-WITH-SOURCE]` The gate is therefore **open**, whatever the build record's R-8 row claims. §1 closes it.
3. **No FE wiring** — `git diff --name-only 361f021 -- apps/web` is empty in the P1-A tree. `[VERIFIED-WITH-SOURCE]` That is correct per ADR-AGI-3 phasing (P1-B owns FE) and is recorded here so nobody expects a visible change on landing.

### 0.3 Three defects this review found in the existing P1-A build

| # | Defect | Evidence | Severity |
|---|---|---|---|
| **D-1** | **Advisory-lock collision.** `run_plan.py:37` declares `_RUN_PLAN_LOCK = 7420240724`. `services/offers.py:37` already holds `_OFFERS_LOCK = 7420240724`. The build's own docstring claims 724 was free. | `[VERIFIED-WITH-SOURCE: grep of both files; full in-tree lock inventory shows 7420240711-726, 730, 740, 751, 7420260801-807, 7420260814 all taken]` | Medium — not corruption (both are `pg_advisory_xact_lock`, transaction-scoped), but two unrelated first-hit `_ensure_table` callers serialise against each other, and the registry discipline that prevents a real deadlock is broken. **Fix: reassign to `7420260815`.** |
| **D-2** | **Charter deviates from the R-8 proof table in 3 fields, and the deviation is only recorded in a gitignored build note.** `coverLetter.dependsOn` gains `matcher`; `tailor`/`coverLetter` carry a `paramsFrom` field the reference does not define. | `[VERIFIED-WITH-SOURCE: charter quoted from P1-A `agents.py:1616-1709` vs `EXEC-CLASSES.json` "backends"]` | Low — the added edge is provably redundant (§10, DEV-1) but it must be recorded in a tracked document, which is what §10 is for. |
| **D-3** | **`RunPlanRepository` has no direct test.** The six suites exercise it only through the endpoints. | `[VERIFIED-WITH-SOURCE: test-file inventory]` | Low — §7.1 adds the missing suite. |

### 0.4 Collision matrix

`apps/api/app/routers/agents.py` is blob `c006efe` — **identical at HEAD in every worktree and the main clone**, and **no unmerged branch has a single commit touching it**. 100% of the collision surface is uncommitted working-tree state. `[VERIFIED-WITH-SOURCE]`

| Ticket | Status | Worktree / branch | Files it touches | Overlap with B1 anchors | Risk & resolution |
|---|---|---|---|---|---|
| **B1a (this)** | in-flight, **uncommitted, build-complete** | `aether-wt-uagi-p1a` / `feat/uagi-p1a` (0 ahead, 7 behind) | `routers/agents.py` +515, `services/llm_client.py` +221, `workers/tasks.py` +78, `repositories/background_jobs.py` +159; NEW `repositories/run_plan.py`, `services/run_scheduler/{__init__,planner,executor}.py` | charter after `_LLM_TIER_BY_BACKEND`; 341-line block after `orchestration_map`; 6 hunks in `_execute_reserved_run` | **Land this tree; do not rebuild.** Backend rebase hazard is **zero**: `git log 361f021..origin/main -- <the 4 files>` is empty and `361f021` is a true ancestor of `origin/main`. `[VERIFIED-WITH-SOURCE]` |
| **B2 threshold gates** | in-flight, **uncommitted, build-complete** | `aether-wt-u2c` / `feat/u2c-thresholds` | `services/quality_policy.py`, `agents/tailor_agent.py`, `agents/cover_letter_agent.py`, `services/tailoring_loop.py`, `repositories/agent_run.py` +127, `routers/agents.py` +12; NEW `services/quality_gate.py` | **`quality_policy.py` — direct**: rebinds `DIMENSION_FLOOR = QUALITY_FLOOR` imported from the new `quality_gate` leaf. **`repositories/agent_run.py` — direct**: adds `ensure_agent_run_quality_columns()` writing `qualityAttempts jsonb` + `qualityGateState text`. **`agents.py:1480-1492`** — one hunk in `_execute_reserved_run` | **HIGH for B1b.** B1b's whitelist must treat `DIMENSION_FLOOR`/`QUALITY_FLOOR` as **non-addressable** (it is an honesty floor, and after u2c it is a *shared* one — a directive touching it would move the tailoring gate and the cover gate at once). B1b's AgentRun columns must extend u2c's `ensure_agent_run_quality_columns` **or** land as a sibling `ensure_*` — never a second lazy-DDL path racing the same table. **Sequencing: land u2c before B1b.** |
| **B6 parentRunId** | **UNSTARTED** (claimed only) | none | `routers/agents.py` (run creation), additive AgentRun migration, FE map | `_record_run:944`, `_enqueue_single_agent:2340`, `_pipeline_core:3389` | **Compose, do not conflict.** B1a's `execute_run_plan` is the *first* place with a true parent/child relation for non-pipeline runs. §4.4 specifies the seam B6 should use so plan steps carry `parentRunId` without B1a owning the column. |
| **D.524 generic route async** | **UNSTARTED** (claimed only) | none | `routers/agents.py` `run_named_agent:5391-5413` | none with B1's anchors | **LOW textual, MEDIUM semantic.** §4.5 states the one rule that keeps them compatible: D.524 must **not** pass `singleton=True`, or a user-initiated run will start colliding with plan claims (see OQ-2). |
| **admin-full entitlements** | in-flight, uncommitted | `aether-wt-adminfull` / `feat/admin-full` | `routers/agents.py` +52 (`_require_active_subscription:866`, `_record_run:~1020`, `_enqueue_single_agent:~2414`), `workers/board_sweep.py` | Both quota seams B1a's plan path runs through | **MEDIUM.** Textual conflict only — B1a adds no new quota logic (R-2b: no `skip_quota` anywhere in the plan path). Land whichever first; the other rebases. |
| **u5d3 answer-bank** | in-flight, uncommitted | `aether-wt-u5d3` | `workers/apply_sweep.py` +others | none in `agents.py` | LOW now; MEDIUM for **P2**, which wants `apply_sweep` folded into the scheduler. |
| **analytics-viz, sui-b2** | in-flight, uncommitted (web only) | `aether-wt-anaviz`, `aether-wt-sui-b2` | `apps/web/**` | none | NONE for B1a/B1b/B1c backend. **P1-B** collides hard: `OrchestrationMap.tsx` gained +618 lines of linkage rendering since P1-A's base. |

**Contested-function ranking** (for sequencing implementer agents): `_execute_reserved_run` (`agents.py:1063`) is the most contested function on the file — 6 P1-A hunks + 1 u2c hunk. **No B1 ticket in this blueprint adds a hunk there.** `[INFERRED — from §4, which places every B1b/B1c injection at `_with_quality_policy:2177` and `_agent_callable:2016` instead]`

### 0.5 Cost posture

The Supervisor makes **no LLM call** in any ticket here. B1b Stage-1 is a pure rule table over rows the app already reads; ADR-AGI-1 Stage-2 stays off. `GET /agents/orchestration/plan` dispatches nothing and returns a literal `estimatedCostUsd: 0.0`. `[VERIFIED-WITH-SOURCE: P1-A `orchestration_plan` handler]` B1c's corrective retry is the only new LLM spend in B1, and it is bounded — §3.3 R3.

---

## 1. The R-8 gate — independent per-row re-verification

**Method.** The scout classification (`EXEC-CLASSES.md`, baseline `231b4f4`) is testimony. Every row below was re-checked against code **in the design tree at `7be085a`**. Card→backend mapping was re-derived by AST rather than read from the document.

**Independent AST re-derivation of the counts** (`python3 ast` over `apps/api/app/routers/agents.py`, this session) `[VERIFIED-WITH-SOURCE]`:

| Quantity | Value | Evidence at `7be085a` |
|---|---|---|
| `AGENT_CATALOG` entries | **22** | `agents.py:214-414`; card literals at `215,219,223,227,236,251,267,271,279,291,302,310,318,327,335,346,357,367,375,382,394,405` |
| Distinct backends | **20** | same extraction; zero backend-null cards |
| Shared backend | `fitScorer` × **3** | `atsOptimization:227`, `matchScoring:267`, `skillGap:310` |
| `_RUNNABLE_BACKENDS` | **19** | `agents.py:2163-2174` — every backend except `supervisor` |
| Cards covered by the charter | **21** | 22 minus `orchestration` (`agents.py:394`, backend `supervisor`) |

**Drift verdict: NONE.** Every card line number matches the scout's list exactly, so its citations hold at `7be085a` as well as at `231b4f4`. `[VERIFIED-WITH-SOURCE]`

### 1.1 The verified charter table

Every row below was re-checked against code at `7be085a` by two independent verifiers plus this architect. **Drift check first:** `git diff 231b4f4..HEAD` over *every* file either verifier cites — `routers/agents.py`, all of `app/agents/`, all of `app/repositories/`, `app/db.py`, `services/gmail_service.py`, `services/discovery/adzuna_adapter.py`, `packages/db/src/schema.prisma` — is **EMPTY**. `[VERIFIED-WITH-SOURCE]` So every discrepancy found is a **citation error in the scout's document, not staleness**, and the scout's line numbers resolve at `7be085a` exactly as at `231b4f4`.

| # | backend | execClass | siloBasis | onRefusal | dependsOn | coversCards | Verdict | Key code evidence at `7be085a` |
|---|---|---|---|---|---|---|---|---|
| 1 | `scout` | silo | **`quota-contended`** *(was `race-proven`)* | halt-chain | — | `jobDiscovery` | **CORRECTED — siloBasis only** | Sole `_SINGLETON_AGENTS` member: `background_jobs.py:59`. Enforcement is real and twofold: partial unique index `:158-163` **plus** a two-argument advisory lock `:279-282`. **But both DB writes are `ON CONFLICT`-guarded** — `repositories/job.py:417` and `repositories/job_source_status.py:96` — so **no unguarded concurrent-write hazard is citable**, and `race-proven` fails the charter's own definition of that word. The silo is earned by the **shared external Adzuna quota** (`adzuna_adapter.py:103,107,148-166` — a process-local ledger against one deployment-wide key) and by the shipped singleton decision. The scout's own §2.2 rationale admits this in prose while the field says otherwise. `[VERIFIED-WITH-SOURCE]` |
| 2 | `fitScorer` | sequential | — | halt-chain | `scout` | `matchScoring`,`atsOptimization`,`skillGap` | **CONFIRMED** | Reads scout's rows: `fit_scorer.py:81` `iter_scoring_candidates`. Writes are a guarded CAS — `repositories/job.py:674-698`, single UPDATE + `rowcount == 1` at `:696`. Three cards, one dispatch: `agents.py:227,267,310`. **This row is the whole R-2a dedup surface.** Grade note: without scout it **no-ops** (scores nothing); it does not refuse. `[VERIFIED-WITH-SOURCE]` |
| 3 | `matcher` | sequential | — | halt-chain | `fitScorer` | `jobMatching` | **CONFIRMED** | Read-only — `matcher_agent.py:47` is its only repository call. The `matched` advance lives in the router, not the agent: `agents.py:3431-3433`, kept there per the comment at `:3427-3430` "so the standalone read-only ranking endpoint stays side-effect-free". **A plan step therefore performs no status advance.** Grade note: without fitScorer it does not no-op — `ORDER BY fitScore DESC NULLS LAST` (`repositories/job.py:276-284`) still returns a `top_job_id`, just a meaningless one. Degrade-grade, not refusal-grade. `[VERIFIED-WITH-SOURCE]` |
| 4 | `tailor` | sequential | — | halt-chain | `matcher` | `resumeTailoring` | **CONFIRMED** | Hard job edge: `_require_job_id` at the binding (`agents.py:1996-1999` → `:2293-2297`, a 422). Writes `tailor_agent.py:784` (Resume version), `:829` (ApprovalRequest), `:848` (guarded CAS), `:571`. Deliberately NOT siloed, and the codebase says so at `background_jobs.py:54-55`. `[VERIFIED-WITH-SOURCE]` |
| 5 | `coverLetter` | sequential | — | halt-chain | `tailor` *( +`matcher` — DEV-1 )* | `coverLetter` | **CORRECTED — write target** | Class/refusal/deps CONFIRMED. **But it does not write a "CoverLetter" row — there is no `CoverLetter` table.** `cover_letter_agent.py:1949` → `CoverLetterRepository.create` → **`INSERT INTO "Application"`** at `repositories/cover_letter.py:62`. Also `:1952` (ApprovalRequest), `:1972` (advance to `ready`). Tailor edge at `:1910` is **degrading** (falls back to base résumé, `tailor_agent.py:515-528`), not refusing; its only refusal-grade predecessor is `matcher` (the job id). **Material:** coverLetter writes the very table `submission`'s missing partial unique index guards — no collision today because its rows are `'draft'` and the index covers only submitted/screening/interview/offer (`db.py:1233`), but the charter must not record a separate entity that does not exist. `[VERIFIED-WITH-SOURCE]` |
| 6 | `submission` | silo | race-proven **+ see §1.2** | isolate | `tailor`,`coverLetter` | `submission` | **CONFIRMED — and the edge is stronger than claimed. DB backstop DISPROVEN on prod (§1.2)** | Two hard 422 gates: `submission_agent.py:364-374` (resume) and `:375-384` (cover letter), imported from `app.routers.jobs` at `:81-84` so the card can never be looser than the button. **Un-cited additional proof:** the selection SQL itself requires both — `_READY_TO_APPLY_SQL` at `:205-218` (`EXISTS (SELECT 1 FROM "Resume" r WHERE r."sourceJobId" = a."jobId")` + `NULLIF(BTRIM(a."coverLetter"),'') IS NOT NULL`). **It does NOT call `_require_job_id`** — `agents.py:2146-2153` uses `params.get("job_id")`, so an empty-param plan step self-selects and returns a graceful no-op (`nothing_ready`, `:249-262`) rather than a 422. That is exactly what `isolate` needs. `[VERIFIED-WITH-SOURCE]` |
| 7 | `emailAgent` | silo | race-proven | isolate | — | `emailAgent` | **CONFIRMED end to end** | The SYNTHESIS silo-vs-independent contradiction is resolved, and both stated reasons were wrong. Enqueues **without** a claim: `agents.py:3353-3355`. Plan binding `agents.py:2024-2027`; `run()` defaults `mode="triage"` (`email_agent.py:280-283`). E1 SELECT-then-INSERT `gmail_service.py:926-964` behind a **non-unique** index `:247-250`; an independent sweep of every `CREATE UNIQUE INDEX` under `apps/api/app/` found **no** unique index on `EmailThread` anywhere. E2 `email_agent.py:369-383`. E3 process-local lock `gmail_service.py:143-193`, refresh persisted `:514-519`. **Live: 0 duplicate `(userId,gmailThreadId)` groups over 433 rows on prod** — code-proven, not data-manifested (§1.2). `[VERIFIED-WITH-SOURCE]` |
| 8 | `notification` | silo | race-proven | isolate | — | `notification` | **CONFIRMED** | `notification_agent.py:224-232` (dedupe_key approval) + `_record_digest` `:284-327` (UPDATE `:299-311` else INSERT `:316-323`) behind a **non-unique** index `:112-115`; approval check-then-act `repositories/approval.py:176-197` with no unique index (`schema.prisma:268-269`). In `_APPROVAL_GATED`, `agents.py:120-125`. `[VERIFIED-WITH-SOURCE]` |
| 9 | `recruiterOutreach` | silo | **tier-conservative** | isolate | — | `recruiterOutreach` | **CONFIRMED** | Sole write `recruiter_outreach_agent.py:263-272`; a grep for both `INSERT|UPDATE|conn.commit` **and** `.create(/.update(/.upsert(` in the file returns **0**. **No race proven** — siloed because U-AGI §5.3 makes it a T3 real-world actor. `siloBasis` is what stops the charter claiming a race it cannot cite. `[VERIFIED-WITH-SOURCE]` |
| 10 | `reference` | silo | **tier-conservative** | isolate | — | `reference` | **CONFIRMED** | Sole write `reference_agent.py:261-270`; same zero-write grep result. Identical shape to #9. `[VERIFIED-WITH-SOURCE]` |
| 11 | `storyExtractor` | independent | — | isolate | — | `storyExtraction` | **CORRECTED — write set understated** | Writes `StoryEntry` (`story_extractor.py:338`) **and, transitively, the `EvidenceCorpus` mirror** — `repositories/story.py:103` `EvidenceCorpusRepository().upsert_many`, called at `:203,222,249,277`. Class **holds**: no other *agent* writes `StoryEntry` (only `routers/stories.py` and `services/story_dedup_migration.py`), and the concurrency hazard is closed by the DB — the partial unique index is at **`db.py:1157-1162`** (not the `1091-1125` cited, which is the def + docstring), and unlike the Application index it **raises loudly rather than skipping on violations**, so this guard is either real or visibly broken. The corpus mirror is read by tailor (`tailor_agent.py:24`) and coverLetter (`cover_letter_agent.py:47`) — which confirms the soft edges. `[VERIFIED-WITH-SOURCE]` |
| 12 | `compliance` | independent | — | isolate | — | `compliance` | **CONFIRMED** | Zero repository-write calls (verified by method-call grep, not just SQL keywords). Read `compliance_agent.py:115`; `_ARTIFACT_BY_AGENT` defined `:33-36`, read `:119`. `enrichedBy` `tailor`,`coverLetter` is an audit-freshness edge, never a gate. `[VERIFIED-WITH-SOURCE]` |
| 13 | `learningFeedback` | independent | — | isolate | — | `learningFeedback` | **CORRECTED — enrichedBy** | `enrichedBy` = **`["scout","fitScorer","tailor","submission"]`** (all soft), not `[]`. Its `_QUERY` (`learning_feedback_agent.py:105-115`, executed `:183`) joins `Application ⋈ Job ⋈ Resume`, selecting `j."fitScore"` (`:109`, written by fitScorer at `repositories/job.py:704`) and `r."sourceJobId"` (`:110`, written by tailor). Read-only confirmed (`:26` docstring). `[VERIFIED-WITH-SOURCE]` |
| 14 | `marketTrends` | independent | — | isolate | — | `marketTrends` | **CONFIRMED** | Read-only `market_trends_agent.py:138`; soft `scout`. `[VERIFIED-WITH-SOURCE]` |
| 15 | `salaryIntelligence` | independent | — | isolate | — | `salaryIntelligence` | **CORRECTED — `exclusiveResource` REMOVED; F-R8-4's consequence REFUTED** | The agent's `run()` (`salary_intelligence_agent.py:166-219`) does exactly one thing: `self._jobs.list_by_user(user_id)` at `:167`. **It never reaches Adzuna.** `fetch_market_benchmark` (`:638`) — the only Adzuna path — has exactly **one caller in the tree**: `routers/analytics.py:1259`, inside `GET /analytics/market-pulse`. So a `salaryIntelligence` **plan step makes zero Adzuna calls** and the charter must carry `exclusiveResource: []`. See §1.3a for the corrected finding. `[VERIFIED-WITH-SOURCE]` |
| 16 | `companyResearch` | independent | — | isolate | — | `companyResearch` | **CONFIRMED** | Read-only `company_research_agent.py:183`; conditional LLM via `_OPTIONAL_LLM_BY_BACKEND` `agents.py:1691-1702`. `[VERIFIED-WITH-SOURCE]` |
| 17 | `interviewPrep` | independent | — | isolate | — | `interviewPrep` | **CORRECTED — enrichedBy** | `enrichedBy` gains **`submission`**: `_ACTIVE_INTERVIEW_SQL` at `:150-157` reads `"Application" … status='interview'`, executed `:377`. Other reads `:292` (stories), `:362`/`:368` (jobs). Read-only. `[VERIFIED-WITH-SOURCE]` |
| 18 | `sentimentAnalysis` | independent | — | isolate | — | `sentimentAnalysis` | **CONFIRMED** | Reads only `EmailThread` — `:152`, `:162-164`, `:113` via `load_thread`. Writes none. Soft `emailAgent` is real (`email_agent.py:371,377` are the writers). `[VERIFIED-WITH-SOURCE]` |
| 19 | `scheduling` | independent | — | isolate | — | `scheduling` | **CORRECTED — "writes nothing" is FALSE; F-R8-5 claim 1 REFUTED** | It **does** write, transitively: `scheduling_agent.py:272`/`:286-288` → `calendar_service.py:219,237,256-261` → `repositories/gmail_account.py:496-510` `UPDATE "GmailAccount"` + commit. That is the **same row `emailAgent` (a silo) writes** at `gmail_service.py:514`. Class **survives** — it is a last-write-wins OAuth token refresh, not domain data, and Google keeps both tokens valid — but the row must carry the shared write instead of `writes: []`. And it is genuinely **T2**, not T1: U-AGI §5.2 defines T2 by *output gates*, and `scheduling_agent.py:413-426` calls `guarded_draft(...)` (`outreach_support.py:271-296`), which withholds the whole draft on a flag. `[VERIFIED-WITH-SOURCE]` |
| — | `supervisor` | **not a plan step** | — | — | — | (`orchestration`) | **CONFIRMED** | Absent from `_RUNNABLE_BACKENDS:2163-2174` and from `_agent_callable` (so `POST /agents/supervisor/run` hits the 404 at `:2155`); catalog card `agents.py:394`; body `:3406-3408`, literal `:3386`. Present in `_ROLE_MODEL_BACKENDS:1727-1729` (assigned a model, unmetered). `[VERIFIED-WITH-SOURCE]` |

**Distribution unchanged: 6 silo + 4 sequential + 9 independent = 19 = `_RUNNABLE_BACKENDS`.** `[VERIFIED-WITH-SOURCE]`

**Verdict: every execClass survives re-verification. Seven of the twenty rows carry corrected FACTS** — rows 1 `scout` (siloBasis), 5 `coverLetter` (write target), 11 `storyExtractor` (write set), 13 `learningFeedback` (enrichedBy), 15 `salaryIntelligence` (exclusiveResource), 17 `interviewPrep` (enrichedBy), 19 `scheduling` (writes, and its tier).

**None of the seven changes a plan's shape** — `enrichedBy` is display-only, and `siloBasis`/`writes`/`exclusiveResource` are narration inputs. But a charter that states a race it cannot cite, or an exclusive resource an agent never touches, or an entity that does not exist, is exactly the R-6 failure ("the classification becomes a lie") that the ADR makes a risk hold. **The corrected values are the ones that become charter data.** §1.1b is the exact diff to apply — a smaller set, because three of the seven corrections are to facts the shipped charter never encoded.

### 1.1a `onRefusal` is a PROPOSAL, not an observed behaviour — narrate it as such

`grep` for `execClass|onRefusal|dependsOn|enrichedBy|coversCards` across `apps/api` and `apps/web/src` returns **zero hits**. `[VERIFIED-WITH-SOURCE]` None of these fields exists in code today. The only multi-agent run surface that ships is the client batch runner, and it **halts on any refusal for every backend**:

```
apps/web/src/components/agents/OrchestrationMap.tsx:1448    if (refused) break;
```
with the rule stated verbatim at `orchestration-run-plan.ts:14-18` — *"one dispatch in flight, halt on refusal."* `[VERIFIED-WITH-SOURCE]`

So `onRefusal: isolate` on the nine independents and the four `isolate` silos is a **deliberate behaviour change from HEAD**, not a preserved semantic. `halt-chain` on the pipeline spine *is* preserved (`_pipeline_core`'s shipped propagation). The distinction must reach the user-facing narration and the P1-B copy: today one refusal stops everything; after B1a a refusal stops only what depended on it. Claiming that was always true would be false. `[INFERRED — from the two verified facts above]`

### 1.1b The exact charter diff B1a must apply

The `_EXEC_CLASS_BY_BACKEND` literal in the P1-A tree was copied verbatim from the unverified proof table. Five field edits bring it in line with §1.1. **Nothing else in the 19 rows changes**, and **no plan changes shape** — verify that with the existing property tests before and after.

| Row | Field | From (shipped in P1-A) | To (verified) |
|---|---|---|---|
| `scout` | `siloBasis` | `"race-proven"` | `"quota-contended"` |
| `salaryIntelligence` | *(none — the shipped charter carries no `exclusiveResource` field at all)* | — | **no change needed**; the erroneous claim lives only in `EXEC-CLASSES.json`, so do not import it |
| `learningFeedback` | `enrichedBy` | `()` | `("scout","fitScorer","tailor","submission")` |
| `interviewPrep` | `enrichedBy` | `("scout","storyExtractor")` | `("scout","storyExtractor","submission")` |
| `notification` | `enrichedBy` | `()` | `("coverLetter","submission")` — its digest window reads `Application` rows, and those two are what write them (`repositories/cover_letter.py:62`; the submission path) `[INFERRED — composition of two verified writes and one verified read; the weakest of the five, so take it or leave it explicitly rather than by default]` |

**One code change comes with the first row.** `planner.py` declares `SILO_BASES = frozenset({"race-proven", "tier-conservative"})` and `normalize_charter` refuses anything else `[VERIFIED-WITH-SOURCE]`, so `"quota-contended"` must be added to that frozenset in the same commit or the charter will not load. That is the whole change — three words and a test. `[INFERRED]`

**`enrichedBy` is display/ordering-preference only and MUST NOT create a hard edge** — the planner already enforces this separation. `[VERIFIED-WITH-SOURCE: `fieldSemantics` in the charter + `normalize_charter`'s handling]` These three additions therefore make the narration honest without touching topology.

### 1.2 Live probes this review ran (two open R-8 probes, now closed)

Read-only queries against the production database. The design tree's `DATABASE_URL` was confirmed **byte-identical** to the deployed service's (`sha256[:12] = cf5a114fd001` for both) before any query, so these results describe production. `[VERIFIED-WITH-SOURCE — hashes compared in-process; no URL or secret printed]`

**PROBE-R8-2 — does `Application_user_job_active_key` exist on prod? → NO.** `[VERIFIED-WITH-SOURCE: `pg_indexes` where tablename='Application']`

```
 Application_pkey       | UNIQUE btree (id)
 Application_userId_idx | btree ("userId")
 Application_jobId_idx  | btree ("jobId")
```

The partial unique index is **absent**, because `ensure_application_unique_active_index` skips creation while violations exist (`apps/api/app/db.py:1243-1300`) `[VERIFIED-WITH-SOURCE]`, and violations exist **and have grown**:

```
violating_pairs | extra_rows      (status IN ('submitted','screening','interview','offer')
              7 |         36       -- APPLICATION_ACTIVE_STATUSES, db.py:1233)
```
against 634 `Application` rows. `[VERIFIED-WITH-SOURCE]` The July 2026 record cited by the scout was 2 pairs / 21 rows; it is now 7 / 36. `[INFERRED — comparison of the recorded figure with this session's query]`

**Consequence, and it is a gate:** the `submission` silo's DB backstop **does not exist on production and cannot be created until 36 rows are reconciled.** A plan that treats `submission` as DB-guarded is, on this deployment, guarded only by the `BackgroundJob` singleton claim P1-A adds. That claim is real and sufficient to stop *two plans*; it does not stop a plan step racing a user's own Apply button. See G-1 in §9.

**PROBE-R8-3 — duplicate `EmailThread` rows on prod? → NONE.** 0 duplicate `(userId,gmailThreadId)` groups over 433 rows. `[VERIFIED-WITH-SOURCE]` The `emailAgent` E1 hazard is real in code and **has not manifested in data**. Say it that way in any narration; do not claim observed corruption.

**Singleton index state on prod:** `BackgroundJob_active_singleton_idx` = `UNIQUE btree ("userId","agentKey") WHERE agentKey='scout' AND status IN ('enqueued','processing')` — i.e. production holds the **original** scout-only index, not the intermediate `_v2_` variant that the P1-A build found in the shared `aether_test` schema. `[VERIFIED-WITH-SOURCE]` P1-A's `pg_get_indexdef` self-heal is therefore a no-op on prod and a genuine repair on any developer database that ran an intermediate build. `[INFERRED]`

**`RunPlan` / `AgentDirective` do not exist on prod.** `[VERIFIED-WITH-SOURCE: `pg_tables` filtered on both names returns empty; the 33 existing tables are listed in §2.0]`

### 1.3 F-R8-1 re-verified independently: enabling async does NOT make the silo class real

All four call sites read at `7be085a` `[VERIFIED-WITH-SOURCE]`:

| Site | Line | Gate | `singleton=` |
|---|---|---|---|
| `scout` | `agents.py:2908-2910` | `if background:` (`:2899`) — **not** `async_generation_enabled()` | **`True`** |
| `tailor` | `agents.py:3184-3186` | `if async_generation_enabled():` | absent |
| `coverLetter` | `agents.py:3255-3257` | `if async_generation_enabled():` | absent |
| `emailAgent` | `agents.py:3353-3355` | `if async_generation_enabled() and _email_agent_will_call_llm(params):` | absent |

**The singleton guard is bound to the `background` query parameter, not to the async flag.** Turning `AETHER_ASYNC_GENERATION` on buys exactly zero mutual exclusion. The scout's F-R8-1 is upheld in full, and P1-A's three-part remedy (extend `_SINGLETON_AGENTS`, ship a new-named index, claim at the plan's dispatch seam) is the right shape.

**F-R8-2 re-verified:** the deployed `.env` contains exactly one line matching `^AETHER_ASYNC_GENERATION=true$`; `AETHER_ORCH_PLAN_CONCURRENCY` is absent, so the code default applies. `[VERIFIED-WITH-SOURCE — matched by count, no value printed]`

### 1.3a Corrected upstream findings — two of the scout's five change meaning

**F-R8-4 (`salaryIntelligence` spends Adzuna quota outside the ledger) — mechanism CONFIRMED, consequence REFUTED, and the bypass turns out to be deliberate and budgeted.**

- *True:* `salary_intelligence_agent.py:71` imports `live_http.fetch_json`; the call at `:456` hits `_ADZUNA_API_BASE` (`:247`) without passing `adzuna_adapter._reserve_call` (`:148-166`), so those calls are invisible to `_CALL_LEDGER` (`:107`) and to `budget_snapshot()` (surfaced at `agents.py:3113,3124`). Three calls per cache miss. `[VERIFIED-WITH-SOURCE]`
- *Refuted:* the stated consequence — *"a plan that fans out `salaryIntelligence` alongside `scout` can exhaust the shared upstream key"* — **cannot happen**, because `SalaryIntelligenceAgent.run` never reaches that code. `fetch_market_benchmark` has exactly one caller: `routers/analytics.py:1259` (`GET /analytics/market-pulse`). `[VERIFIED-WITH-SOURCE]`
- *Omitted by the scout:* the bypass is **priced in**. `adzuna_adapter.py:94-98` says so — *"the margin held back from it so the separate salary-benchmark path (3 calls per cache miss) and any operator probing still fit inside the real limit"* — via `DEFAULT_DAILY_BUDGET = 250` and `DEFAULT_BUDGET_SAFETY_MARGIN = 25`. `[VERIFIED-WITH-SOURCE]`
- *Residual real risk, newly found:* `_BENCH_CACHE` (`:330`) is a bare dict with **no lock**, unlike the adapter's `_STATE_LOCK` (`:103`), so concurrent misses on one key double-spend. **That is an analytics-endpoint concurrency bug, not a plan-scheduling bound.** It is out of B1's scope; file it separately rather than letting it distort the charter. `[VERIFIED-WITH-SOURCE]`

**Net for the charter: `salaryIntelligence.exclusiveResource = []`, and B1a inherits no new plan bound from this finding.** The earlier draft of this blueprint treated it as a plan-bounds problem; that was wrong and is corrected here.

**F-R8-5 — claim 1 REFUTED, claim 2 CONFIRMED.**
1. *"`scheduling` is §5.2 T2 but writes nothing, so behaviourally T1"* — **wrong twice.** It is a category error (§5.2 defines T2 by *output gates*, not DB writes, and `scheduling` passes a real one via `guarded_draft`, `scheduling_agent.py:413-426`), and it is factually wrong anyway (it writes `GmailAccount` transitively, row 19). U-AGI §5.2 needs **no** amendment for `scheduling`. `[VERIFIED-WITH-SOURCE]`
2. *"`matcher` is documented as a writer but is read-only at HEAD"* — **confirmed**, and the drift is worse than reported: `SUPERVISOR-AND-DEPS.md` §6 is also wrong about `scheduling`, `sentimentAnalysis`, `learningFeedback` and `storyExtractor`, all four listed as reading nothing while all four execute real SELECTs. **Five of its rows are false at HEAD, not one.** `[VERIFIED-WITH-SOURCE]`

> **Binding instruction to implementers: `SUPERVISOR-AND-DEPS.md` §6 must not be used as a source for `dependsOn`/`enrichedBy`. Nor may `AGENT-GRAPH.json` (it carries none of the `submission ← tailor`, `submission ← coverLetter` or `coverLetter ← tailor` edges). §1.1 of this document is the source.**

### 1.3b Citation errors found in the scout's document

Fifteen-plus citations were imprecise **at the scout's own baseline** (drift is not the cause — §1.1). The material ones, because a reader following them lands on prose instead of code:

| Where | Cited | Actual at `7be085a` |
|---|---|---|
| `coversCards` semantics | `apps/web/src/lib/orchestration-run-plan.ts:19-24` | **Path does not exist.** The file is `apps/web/src/components/agents/orchestration-run-plan.ts` (lines correct) |
| §2.12 storyExtractor DB guard | `db.py:1091-1125` | `:1091` is the `def`, `:1092-1130` the docstring. DDL is **`db.py:1157-1162`**; the `ALTER TABLE` is `:1149-1152` |
| §2.13 compliance | `_ARTIFACT_BY_AGENT` `:120-135` | defined **`:33-36`**, read **`:119`** |
| §2.6 coverLetter write | "`CoverLetter` row — `cover_letter_agent.py:1949`" | Call site right, **target wrong**: `INSERT INTO "Application"` at `repositories/cover_letter.py:62`. No `CoverLetter` table exists |
| §2.8 emailAgent plan binding | `agents.py:2019-2021` | **`agents.py:2024-2027`** |
| §2.7 submission writes | `:393`, `:400-402`, `:446-449` | `:393`/`:400-402` are comments; actual `:399`, `:404-406`, `:450` |
| §2.8 job_alerts writes Job | `email_agent.py:415-417` | That is the docstring; the call is **`:509`**. Claim true, citation not |
| F-R8-3 skip-and-return | `db.py:1243-1300` | That range is def + docstring + fast path. The skip branch is **`:1322-1333`**; creation only at `:1334-1337` |
| §0 / §2.11 | `_ORCHESTRATION_MAPS 3731-3769`; `_APPROVAL_GATED 120-124` | **`3731-3768`**; **`120-125`** |

A dozen further off-by-1-to-6 citations (wiring lines cited instead of the read: `compliance:112→115`, `marketTrends:134→138`, `salaryIntelligence:164→167`, `companyResearch:172→183`, `interviewPrep:272-273→292/362/368/377`, `fit_scorer:73→71`, `job.py:418→417`, `gmail_service:142→143`, `learningFeedback:181→183`, `sentimentAnalysis:163→162`, `scheduling:287-289→286-288`, `_OPTIONAL_LLM_BY_BACKEND:1691-1701→1691-1702`, `_reserve_call:146-165→148-166`) leave their claims intact. **The charter data must carry the corrected numbers**, because an implementer who cannot find the evidence will re-derive it or, worse, trust the field.

### 1.4 One structural gap the charter's own tests depend on

Charter self-test #6 ("every T3 real-world actor is siloed") needs a tier table. **`AGENT_TIER` does not exist in code** — `grep -rn "AGENT_TIER\|autonomyTier"` over `routers/agents.py` and `services/` returns nothing. `[VERIFIED-WITH-SOURCE]` The nearest shipped set is `_APPROVAL_GATED` (`agents.py:120-124`), which is a **superset**: it contains `tailor` and `coverLetter`, which are T2 content producers, not T3 actors. `[VERIFIED-WITH-SOURCE]`

A test that derives T3 as `_APPROVAL_GATED - {"tailor","coverLetter"}` encodes a subtraction nobody declared, and will silently rot the first time a T2 agent joins the approval set. **B1a must land `AGENT_TIER` as declared data** (5 keys T3, the rest T1/T2 per U-AGI §5.1-5.3) next to `_EXEC_CLASS_BY_BACKEND`, and the test asserts against *that*. It is ~20 lines of data and it removes an invisible assumption. `[INFERRED]`

---

## 2. Storage design — additive-only DDL

### 2.0 The schema source of truth (this determines the form of everything below)

**This repo has no migration runner.** `apps/api/migrations/0028_uax_instrumentation.sql:3-14` states it outright: *"RECORD ONLY (documentary mirror). The API applies every statement below additively and idempotently at runtime via lazy DDL (ADR-TR-1, 'no migration runner')"*. `packages/db/package.json` adds: *"apps/api owns the live schema via raw psycopg2 + lazy DDL and documents drift against this file."* `[VERIFIED-WITH-SOURCE]` There is no `migrate` script in the root `package.json`, and no `psql -f migrations` in `start-api.sh`, `scripts/`, or `deploy/`. `[VERIFIED-WITH-SOURCE]`

**So: a new table is created by a lazy `_ensure_*()` in its repository, mirrored into `schema.prisma` (so a Prisma push never drops it) and into a numbered `.sql` file (documentation only).** All three artifacts are required; only the first one runs.

Live schema `aether` holds 33 tables; neither target table exists. `[VERIFIED-WITH-SOURCE]`

**Advisory-lock registry.** In-tree ids in use: `7420240711-726`, `730`, `740`, `751`; `7420260801-807`; `7420260814`. Highest in use = **`7420260814`** (`repositories/application_status_event.py:48`). `[VERIFIED-WITH-SOURCE: full-tree grep]` This blueprint claims:

- **`7420260815`** → `RunPlan` (**correcting D-1**; the P1-A build's `7420240724` collides with `services/offers.py:37`)
- **`7420260816`** → `AgentDirective`

**Column conventions**, taken from `BackgroundJob` — the most recent lazily-created table — rather than from the Prisma-generated ones: `id text PRIMARY KEY DEFAULT gen_random_uuid()::text`, **`timestamptz`** for all timestamps, and **`status text NOT NULL DEFAULT '…'`, never a Postgres enum.** `[VERIFIED-WITH-SOURCE: live `information_schema.columns` for `BackgroundJob`]` The last point is load-bearing: `AgentRun.status` *is* a `USER-DEFINED` enum (`"AgentRunStatus"`) `[VERIFIED-WITH-SOURCE: live `\d "AgentRun"`]`, so adding a state there would need `ALTER TYPE` — prohibited. Plan/step/directive states therefore live in the new tables as `text`.

### 2.1 `RunPlan` (B1a) — as the P1-A build already writes it, with D-1 corrected

```sql
-- apps/api/app/repositories/run_plan.py :: _ensure_table()
-- Inside ONE transaction, after: SELECT pg_advisory_xact_lock(7420260815)
--   (7420260815 corrects the shipped 7420240724, which collides with
--    services/offers.py:37 _OFFERS_LOCK — see §0.3 D-1.)

CREATE TABLE IF NOT EXISTS "RunPlan" (
    "id"             text             PRIMARY KEY DEFAULT gen_random_uuid()::text,
    "userId"         text             NOT NULL,
    "status"         text             NOT NULL DEFAULT 'planned',
    "initiator"      text             NOT NULL DEFAULT 'user',
    "concurrency"    integer          NOT NULL DEFAULT 1,
    "spacingSeconds" double precision NOT NULL DEFAULT 0,
    "steps"          jsonb            NOT NULL,
    "summary"        jsonb,
    "haltedAtStep"   text,
    "haltReason"     text,
    "startedAt"      timestamptz,
    "finishedAt"     timestamptz,
    "createdAt"      timestamptz      NOT NULL DEFAULT now(),
    "updatedAt"      timestamptz      NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS "RunPlan_userId_createdAt_idx" ON "RunPlan" ("userId", "createdAt" DESC);
CREATE INDEX IF NOT EXISTS "RunPlan_status_idx"           ON "RunPlan" ("status");
```

Notes, each with its reason:
- **No FK to `"User"`.** Deliberate in the shipped build so the shared test suite's `TRUNCATE "User"` never trips. `[VERIFIED-WITH-SOURCE: run_plan.py docstring]` It also matches the standing precedent for audit rows (`AgentRun.applicationId`/`jobId` are plain nullable columns for exactly this reason, `schema.prisma:351-361` comment) `[VERIFIED-WITH-SOURCE]`.
- **Steps are one `jsonb` array, not a child table.** A step's state is rewritten in place by `jsonb_agg(... ORDER BY ord)` over `jsonb_array_elements WITH ORDINALITY`. `[VERIFIED-WITH-SOURCE: `RunPlanRepository.record_step_state`]` This is why "the plan we showed" and "the plan we ran" are provably the same object — the row stores the planner's output verbatim plus `{"state","detail"}`.
- **`status` vocabulary** is `planned | running | completed | partial | halted | failed`. `partial` exists because two statuses would force a plan whose spine broke while nine enrichment agents succeeded to report as either a success or a stop, and both would be false. `[VERIFIED-WITH-SOURCE: executor.py + BUILD-P1A §3.2]`
- **Backfill: none, and none is correct.** A new table has no history to invent.

### 2.2 `AgentDirective` (B1b) — new

```sql
-- apps/api/app/repositories/agent_directive.py :: _ensure_table()
-- Inside ONE transaction, after: SELECT pg_advisory_xact_lock(7420260816)

CREATE TABLE IF NOT EXISTS "AgentDirective" (
    "id"             text        PRIMARY KEY DEFAULT gen_random_uuid()::text,
    "userId"         text        NOT NULL,
    "agentKey"       text        NOT NULL,   -- a _RUNNABLE_BACKENDS member; validated in Python, never a FK
    "directive"      jsonb       NOT NULL,   -- ONLY whitelisted keys survive the writer (§6)
    "clamped"        jsonb,                  -- {field: {requested, applied, reason}} for every value the kernel altered
    "rejectedKeys"   jsonb,                  -- un-whitelisted keys the issuer attempted, recorded loudly
    "rationale"      text        NOT NULL,   -- human-readable, cites the metrics that caused it
    "metricsCited"   jsonb       NOT NULL,   -- the metric snapshot the decision was made on
    "issuedBy"       text        NOT NULL DEFAULT 'supervisor-rules',  -- 'supervisor-rules' | 'supervisor-llm' (P2) | 'operator'
    "status"         text        NOT NULL DEFAULT 'active',            -- 'active' | 'superseded' | 'expired'
    "supersededById" text,                   -- set on the OLD row when a new one replaces it
    "outcome"        jsonb,                  -- P1 writes adherence + observed deltas; P2 scores efficacy
    "issuedAt"       timestamptz NOT NULL DEFAULT now(),
    "expiresAt"      timestamptz,            -- NULL = until superseded
    "createdAt"      timestamptz NOT NULL DEFAULT now(),
    "updatedAt"      timestamptz NOT NULL DEFAULT now()
);

-- The invariant that makes "one active directive per (user, agent)" a DB fact
-- rather than a convention. Partial, so superseded history is unconstrained.
CREATE UNIQUE INDEX IF NOT EXISTS "AgentDirective_active_key"
    ON "AgentDirective" ("userId", "agentKey") WHERE "status" = 'active';

CREATE INDEX IF NOT EXISTS "AgentDirective_user_agent_issued_idx"
    ON "AgentDirective" ("userId", "agentKey", "issuedAt" DESC);

CREATE INDEX IF NOT EXISTS "AgentDirective_status_expires_idx"
    ON "AgentDirective" ("status", "expiresAt");
```

Notes:
- **Immutability is structural, not procedural.** ADR-AGI-2 requires "never edited or deleted — superseded with rationale". The repository exposes **no `update` of `directive`, `rationale`, or `metricsCited`** — only `supersede(old_id, new_row)` (one transaction: insert new `active`, flip old to `superseded` and stamp `supersededById`) and `record_outcome(id, outcome)`. The partial unique index makes a double-active impossible even under a race. `[INFERRED — from ADR-AGI-2 "Immutable history" + the shipped partial-index precedent at `background_jobs.py`]`
- **`clamped` and `rejectedKeys` are first-class columns, not log lines.** ADR-AGI-2 requires the kernel to "clamp and log any out-of-range attempt" and reject un-whitelisted keys "loudly". A log line is not loud enough to survive a restart; these columns make every clamp auditable and are what the FE shows (§8).
- **No FK on `userId`/`agentKey`.** Same audit-row rule as §2.1. `agentKey` membership in `_RUNNABLE_BACKENDS` is validated in the writer; a FK would be to a Python constant, not a table.
- **Backfill: none.** No pre-existing row has a directive, and inventing one would fabricate a Supervisor decision that never happened. Every historical `AgentRun` correctly shows no directive. `[INFERRED — the same rule `policyTier` follows, `agent_run.py:121-124` comment]`

### 2.3 Additive `AgentRun` columns (B1b + B1c)

**Live `AgentRun` today: 17 columns**, no `parentRunId`, no directive column, indexes `AgentRun_pkey`, `_jobId_idx`, `_status_heartbeatAt_idx`, `_status_idx`, `_userId_idx`. `[VERIFIED-WITH-SOURCE: live `\d "AgentRun"`]` Note that `billingAuditJson` exists live but is **absent from the Prisma model** — Prisma is already not complete for this table. `[VERIFIED-WITH-SOURCE]`

```sql
-- apps/api/app/repositories/agent_run.py
-- New sibling of ensure_agent_run_policy_columns() (agent_run.py:111-138).
-- MUST be a sibling ensure_* or an extension of u2c's
-- ensure_agent_run_quality_columns() — never a second lazy-DDL path racing the
-- same table. See §0.4 (B2 collision).

ALTER TABLE "AgentRun" ADD COLUMN IF NOT EXISTS "directiveId"   text;   -- B1b: which directive amended this run's policy
ALTER TABLE "AgentRun" ADD COLUMN IF NOT EXISTS "runPlanId"     text;   -- B1a: the plan this step belonged to (NULL for ad-hoc runs)

CREATE INDEX IF NOT EXISTS "AgentRun_runPlanId_idx"   ON "AgentRun" ("runPlanId")   WHERE "runPlanId"   IS NOT NULL;
CREATE INDEX IF NOT EXISTS "AgentRun_directiveId_idx" ON "AgentRun" ("directiveId") WHERE "directiveId" IS NOT NULL;
```

- **NULL on every pre-existing row is the correct value and must never be backfilled** — the rule `policyTier` already follows (`agent_run.py:121-124`). `[VERIFIED-WITH-SOURCE]`
- **`parentRunId` is B6's column, not B1's.** This blueprint does not declare it. §4.4 specifies only the *seam* so B6 can populate it for plan steps.
- Both indexes are **partial** so they cost nothing on the ~all-NULL existing corpus.
- **Prisma mirror required** for both, plus a documentary `apps/api/migrations/00NN_*.sql`.

### 2.4 The one-line change without which the whole B1b learning loop is silently lost

`run_policy_fields` (`apps/api/app/repositories/agent_run.py:160-182`) builds the persisted `metricSnapshot` from an **explicit five-key whitelist**: `tier`, `triggers`, `knobs`, `metrics`, `thresholds`. `[VERIFIED-WITH-SOURCE]`

A `directives` key merged into `params["qualityPolicy"]` would therefore be **silently dropped** on its way to the database — the run would obey the directive and record no trace of it. B1b must add `"directives": policy.get("directives")` to that dict. This is the single highest-risk detail in B1b and it is three tokens of code. `[INFERRED — from reading the function; the omission would be invisible in every test that only asserts on knobs]`

---

## 3. Module layout and function signatures

### 3.1 B1a — `services/run_scheduler/` (exists in the P1-A tree; landed as-is except D-1)

Package: pure planning + an executor whose every side-effecting seam is injected. **Zero agent names inside** — mechanically asserted. `[VERIFIED-WITH-SOURCE: the only two name-shaped hits are the words "pipeline" in two docstrings, neither a charter key]`

`planner.py` (559 lines) — no IO:

```python
EXEC_SEQUENTIAL, EXEC_INDEPENDENT, EXEC_SILO = "sequential", "independent", "silo"
ON_REFUSAL_HALT, ON_REFUSAL_ISOLATE = "halt-chain", "isolate"
MAX_PLAN_CONCURRENCY = 3          # the ARQ worker's max_jobs

class CharterError(ValueError): ...
class PlanCycleError(CharterError): ...

@dataclass(frozen=True)
class CharterEntry:
    key: str; exec_class: str; depends_on: tuple[str, ...]; covers_cards: tuple[str, ...]
    on_refusal: str; silo_basis: str | None = None; enriched_by: tuple[str, ...] = ()
    params_from: tuple[tuple[str, str, str], ...] = ()

@dataclass(frozen=True)
class PlanStep:      # + .as_dict() -> camelCase payload
    key: str; exec_class: str; depends_on: tuple[str, ...]; covers_cards: tuple[str, ...]
    on_refusal: str; group: int; exclusive: bool; silo_basis: str | None
    unmet_dependencies: tuple[str, ...]; metered: bool; rationale: str
    params_from: tuple[tuple[str, str, str], ...] = ()

@dataclass(frozen=True)
class RunPlan:       # + .as_dict()
    steps: tuple[PlanStep, ...]; groups: tuple[tuple[str, ...], ...]; concurrency: int
    spacing_seconds: float; covered_cards: tuple[str, ...]
    collapsed_cards: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    duplicate_targets_collapsed: int = 0; metered_step_count: int = 0; notes: tuple[str, ...] = ()

def normalize_charter(raw: Mapping[str, Mapping[str, Any]]) -> dict[str, CharterEntry]:
    """Validate raw charter data into rows, refusing: an unknown execClass or
    onRefusal mode; a dangling or self-referential dependsOn/enrichedBy edge;
    silo-without-basis and basis-without-silo; a card claimed by two backends
    (this IS R-2a as a constructor precondition); and a paramsFrom source that
    is not also a dependsOn edge."""

def resolve_targets(charter, cards: Sequence[str]) -> tuple[tuple[str, ...], dict[str, tuple[str, ...]], int]:
    """Map requested catalog CARDS onto the deduplicated backends that cover
    them. Returns (keys, {key: cards}, duplicates_collapsed). An unknown card
    raises — it is never silently dropped, because a dropped card is a step the
    user asked for and did not get."""

def plan_concurrency_ceiling(*, worker_max_jobs: int, admin_dial: int) -> int:
    """max(1, min(MAX_PLAN_CONCURRENCY, worker_max_jobs, admin_dial))."""

def build_plan(charter, *, targets=None, concurrency=1, spacing_seconds=0.0,
               metered=(), collapsed_cards=None) -> RunPlan:
    """Topologically order the selection (priority-respecting Kahn; charter
    insertion order breaks ties), greedily group under the ceiling with a silo
    opening and closing its own group, and stamp each step's group, exclusivity,
    unmet dependencies, metering and human rationale."""
```

`executor.py` (290 lines) — one public function, all side effects injected:

```python
STATE_PENDING = "pending"; STATE_RUNNING = "running"; STATE_COMPLETED = "completed"
STATE_FAILED = "failed"; STATE_REFUSED = "refused"; STATE_SKIPPED = "skipped"
STATE_NOT_ATTEMPTED = "not_attempted"

def execute_plan(*, steps, dispatch, claim, release, on_state, halting_reason,
                 spacing_seconds: float = 0.0, sleep=None) -> dict[str, Any]:
    """Drive a plan to a terminal state. Returns {status, haltedAtStep,
    haltReason, steps, notAttempted, completedCount, failedCount, refusedCount}
    where status is 'completed' | 'partial' | 'halted'.

    Two propagation scopes, and only two:
      * CHAIN — an onRefusal='halt-chain' failure marks its transitive
        dependents not_attempted; 'isolate' marks nothing.
      * PLAN  — only halting_reason (a 429 quota or 402 entitlement) stops
        everything, because those answers cannot become different later in the
        same plan."""
```

`repositories/run_plan.py` — `RunPlanRepository` with `create`, `get`, `get_for_user`, `list_recent`, `mark_running` (replay-safe: returns True only if *this* call transitioned), `record_step_state`, `finish` (first-terminal-wins). Signatures as built. `[VERIFIED-WITH-SOURCE]`

### 3.2 B1b — new modules

**`apps/api/app/services/agent_directives.py`** — pure. No IO, no LLM, no agent names.

```python
DIRECTIVE_FIELDS: Mapping[str, DirectiveField]     # THE whitelist — §6. The only place it is declared.

@dataclass(frozen=True)
class DirectiveField:
    """One amendable knob: its type, its clamp ceiling, and which arithmetic
    makes 'tighten' the only reachable direction."""
    name: str; kind: type; ceiling: float | int | str
    direction: str            # 'increase' | 'restrict-enum' — never 'decrease' in P1
    consumer: str             # file:line of the code that obeys it, for the audit trail

@dataclass(frozen=True)
class DirectiveApplication:
    """What a directive did to a policy — the honest record, including no-ops."""
    knobs: dict[str, Any]
    clamped: dict[str, dict[str, Any]]      # {field: {requested, applied, reason}}
    rejected_keys: tuple[str, ...]
    applied_directive_ids: tuple[str, ...]

def validate_directive(raw: Mapping[str, Any]) -> tuple[dict[str, Any], tuple[str, ...]]:
    """Split a proposed directive into (whitelisted_fields, rejected_keys).
    Rejection is loud and recorded; it is never a silent drop, because a
    Supervisor that believes it issued an instruction nobody obeys is worse
    than one that is told no."""

def apply_directives(baseline_knobs: Mapping[str, Any],
                     directives: Sequence[Mapping[str, Any]]) -> DirectiveApplication:
    """Amend baseline knobs with active directives. The one-way rigor ratchet
    is ARITHMETIC, not a check that a future edit could forget:

        increase-direction field:  applied = min(ceiling, max(baseline, requested))

    A directive proposing a LOWER value than the baseline is therefore a no-op
    by construction — recorded in `clamped` with reason 'ratchet', never
    obeyed. There is no code path, and no field definition, that can lower a
    baseline knob."""

def effective_policy(policy: Mapping[str, Any],
                     directives: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """The single composition used by the injection seam: returns a NEW policy
    dict whose 'knobs' are amended and whose 'directives' key records what was
    applied, clamped and rejected. Never mutates its input. Never raises — a
    malformed directive degrades to the baseline policy and is recorded as
    rejected, because a broken directive must not take down an agent run."""
```

**`apps/api/app/services/supervisor_rules.py`** — Stage-1 only, deterministic, $0.

```python
@dataclass(frozen=True)
class DirectiveProposal:
    agent_key: str; directive: dict[str, Any]; rationale: str; metrics_cited: dict[str, Any]

def evaluate(policy: Mapping[str, Any], *, active: Mapping[str, Mapping[str, Any]]
             ) -> tuple[list[DirectiveProposal], list[str]]:
    """Stage-1 rule table (ordered, first match per agent wins) over the metric
    snapshot quality_policy already computes. Returns (proposals, retire_ids).

    NO LLM CALL. ADR-AGI-1 Stage 2 is out of scope for B1b and stays off behind
    AETHER_AGI_SUPERVISOR_STAGE2 (unset ⇒ off).

    Idempotent by construction: a rule whose proposal equals the currently
    active directive returns nothing, so re-evaluation does not churn history.
    That is what makes the supersede-only table safe to evaluate on every run."""
```

**`apps/api/app/repositories/agent_directive.py`** — `AgentDirectiveRepository`:

```python
def ensure_agent_directive_table() -> None: ...      # lazy DDL, advisory lock 7420260816 (§2.2)

class AgentDirectiveRepository:
    def list_active(self, user_id: str, agent_key: str | None = None) -> list[dict[str, Any]]: ...
    def list_history(self, user_id: str, agent_key: str, limit: int = 20) -> list[dict[str, Any]]: ...
    def issue(self, user_id: str, agent_key: str, *, directive: dict[str, Any],
              rationale: str, metrics_cited: dict[str, Any], clamped: dict[str, Any] | None = None,
              rejected_keys: Sequence[str] = (), issued_by: str = "supervisor-rules",
              expires_at: datetime | None = None) -> str:
        """Issue a directive. If one is already active for (user, agent) it is
        SUPERSEDED in the same transaction — insert new 'active', flip old to
        'superseded' with supersededById. Never an UPDATE of directive content."""
    def supersede(self, directive_id: str, *, reason: str) -> bool: ...
    def expire_due(self, now: datetime | None = None) -> int: ...
    def record_outcome(self, directive_id: str, outcome: dict[str, Any]) -> None:
        """Merge an outcome observation. The ONLY mutating write on a directive
        row besides status, and it never touches the instruction itself."""
```

### 3.3 B1c — story extractor changes (no new module)

Changes land in `apps/api/app/agents/story_extractor.py` (567 lines, untouched in every worktree `[VERIFIED-WITH-SOURCE]`).

```python
class StoryExtractorAgent:
    def run(self, user_id: str, *, policy_knobs: Mapping[str, Any] | None = None
            ) -> StoryExtractionResult:
        """UNCHANGED default behaviour when policy_knobs is None or {} — the
        exact contract tailor/coverLetter already have (`{}` means 'use the
        callee's shipped defaults', agents.py:2212-2223)."""

    @staticmethod
    def _criteria(policy_knobs: Mapping[str, Any] | None) -> "StoryCriteria":
        """Validation thresholds as DATA. Today _MIN_BODY_CHARS=40 /
        _MIN_TITLE_CHARS=10 are module constants (story_extractor.py:157-158);
        they become the DEFAULTS of a frozen dataclass the knobs may tighten.
        No new branching: _reject_reason reads criteria.min_body instead of the
        constant, and every other line of it is unchanged."""

    def _correct_once(self, rejected: Sequence["Rejection"], chunk, resume_text) -> list[dict]:
        """ONE bounded corrective re-prompt carrying the validator's own
        reasons back to the model. _reject_reason already produces precise,
        human-readable, per-story reasons ('metric \"savings\"=\"$1.2M\" uses
        \"1.2\", which is not evidenced by source bullet b7') — this feeds those
        verbatim as the correction instruction. Returns re-validated candidates;
        anything still rejected is DROPPED with both reasons recorded."""
```

**R3 — the three bounds that keep the corrective loop honest and cheap** `[INFERRED — composed from the verified budget mechanics below]`:

1. **Coverage before correction.** The corrective pass runs **after** the first pass over every chunk, never interleaved. Otherwise a résumé's first two bullets could consume the window and the remaining bullets would go unattempted — trading breadth for polish without telling anyone. The extractor's shipped design already prefers coverage (uncovered bullets first, `story_extractor.py:377-385`) and this preserves that. `[VERIFIED-WITH-SOURCE for the ordering; INFERRED for the consequence]`
2. **Budget-gated, using the shipped mechanism.** A correction is attempted only while `remaining_budget_seconds() >= _MIN_CHUNK_SECONDS` (15.0, `story_extractor.py:175`) — the identical guard the first pass uses at `:240`. When the budget runs out mid-correction the result says so, in the same honest form already shipped ("re-run the extractor to cover them"). `[VERIFIED-WITH-SOURCE]`
3. **Exactly one.** `_correct_once` is not a loop and takes no attempt count. A second corrective pass is not a knob, not a directive field, and not an env flag in B1c — it is a P2 decision with its own cost evidence.

**Budget note that must reach the implementer:** `storyExtractor` is **synchronous-only** — `run_story_extractor` (`agents.py:3297-3300`) calls `_dispatch` unconditionally with no `async_generation_enabled()` branch, unlike tailor/coverLetter/email. `[VERIFIED-WITH-SOURCE]` So the corrective pass spends the **180 s HTTP-edge budget** (`AETHER_LLM_BUDGET_SECONDS` default 180, `llm_client.py:243`), not the 300 s worker budget. `[VERIFIED-WITH-SOURCE]` Bound 2 is what keeps that from becoming a 524. Moving `storyExtractor` onto the async path is D.524-adjacent work and is **explicitly out of B1c's scope** (OQ-5).

**The second call site — the one nobody has been counting.** `storyExtractor` is the **only agent in the fleet dispatched from outside `routers/agents.py`**:

```python
# apps/api/app/routers/resumes.py:352-363  — inside the résumé UPLOAD handler
            from app.routers.agents import _dispatch
            extraction = _dispatch(current_user["id"], "storyExtractor", {})
        except HTTPException:
            raise                                   # a 402 paywall must reach the client
        except Exception as exc:  # noqa: BLE001 — upload must survive extraction issues
            extraction = {"error": str(exc)}
```
gated by an `extract_stories` flag at `:350`. `[VERIFIED-WITH-SOURCE]`

This matters to B1c in three concrete ways, and missing it would be the ticket's most likely regression:

1. **The corrective pass runs on the résumé-upload path too**, inside a request a user is *waiting on* with a file in flight. Bound 2 (§3.3 R3) is what keeps that upload from becoming a timeout — it is not optional polish.
2. **`AETHER_AGI_STORY_CORRECTION` therefore gates a user-visible latency change on two surfaces**, not one. Roll it out with that in mind (§9.1).
3. **The upload handler swallows every non-HTTP exception into `{"error": …}`.** A corrective loop that raised a new exception class would be silently absorbed into an upload response the user reads as success. B1c must not introduce a new raise on this path — a failed correction is a **dropped story with a recorded reason**, never an exception. `[INFERRED — from the verified `except Exception` at `:362-363`]`

---

## 4. Integration points in `agents.py` — exact anchors and replacement semantics

`apps/api/app/routers/agents.py` is **5,414 lines** at `7be085a`. `[VERIFIED-WITH-SOURCE]` Every anchor below is a current line number in the design tree.

### 4.1 B1a — the supervisor stub (the change P1-A did not make)

**Current code, `agents.py:3385-3409`** `[VERIFIED-WITH-SOURCE]`:

```python
#: Canonical pipeline plan, mirroring packages/agents LangGraph node order.
_PIPELINE_PLAN = ["scout", "fitScorer", "matcher", "tailor", "coverLetter"]
...
    # Supervisor node: plans the run (audit-recorded, defect fix — the card
    # previously showed "Never run" because the pipeline skipped this node).
    sup_out = _record_run(
        user_id, "supervisor", params, lambda: {"plan": list(_PIPELINE_PLAN)}
    )
    steps.append({"agent": "supervisor", "output": sup_out})
```

**Replacement semantics — precisely:**

1. `_PIPELINE_PLAN` stops being a hand-maintained literal and becomes a **derivation from the charter**: the topological order of `build_plan(charter, targets=_PIPELINE_BACKENDS)`.
2. The supervisor node's callable becomes `lambda: _supervisor_pipeline_plan(user_id, params)`, which calls the scheduler, persists a `RunPlan` row with `initiator='pipeline'`, and returns:
   ```python
   {"plan": [...],            # UNCHANGED KEY, UNCHANGED VALUE — the ordered backend list
    "planId": "<RunPlan id>", # new
    "source": "run_scheduler",# new — provenance, so nobody has to guess
    "groups": [[...], ...],   # new
    "rationale": {...}}       # new — per-step, the same strings /orchestration/plan renders
   ```
3. **`_pipeline_core`'s body below the supervisor node is NOT rewritten.** The five `_dispatch` calls, the `top_job_id` early return, the `NoChangesApplied` degrade, the `FabricationError` degrade and the shared budget window all stay exactly as they are. B1a makes the supervisor *tell the truth about* the sequence; it does not hand execution to the plan executor. That is P2's consolidation, and conflating them would put the pipeline's five carefully-degraded error paths at risk for no user-visible gain. `[INFERRED — the risk assessment is mine; the degrade paths are verified at `agents.py:3446-3499`]`

**Why this is provably zero-regression.** The charter's `dependsOn` over the five pipeline backends is a strict chain — `scout:[]`, `fitScorer:[scout]`, `matcher:[fitScorer]`, `tailor:[matcher]`, `coverLetter:[tailor]` — so its topological order is **unique** and equals `["scout","fitScorer","matcher","tailor","coverLetter"]`. `[INFERRED — from the verified charter rows in §1.1; a strict chain admits exactly one topological order]` The existing assertion

```python
assert sup["plan"] == ["scout", "fitScorer", "matcher", "tailor", "coverLetter"]
```
— `apps/api/tests/test_pipeline.py:57` `[VERIFIED-WITH-SOURCE]` — stays green **unchanged**, and becomes the equivalence proof rather than a restatement of a constant. Test T-A4 (§7.1) pins the derivation to the literal so a future charter edit that would silently reorder the user's pipeline fails loudly.

### 4.2 B1b — the directive injection seam (ONE place)

**`_with_quality_policy` at `agents.py:2177-2209` is the single rigor-policy enforcement seam and is already documented as such** `[VERIFIED-WITH-SOURCE]`:

> *"The SINGLE rigor-policy enforcement seam (U-AX build spec items 2-3). … Placing it here — upstream of `_agent_callable` (which reads `qualityPolicy.knobs`…) and upstream of `AgentRunRepository.start` (which persists `policyTier` + `metricSnapshot` off the same dict) — is what guarantees the tier the agent OBEYED and the tier the run card DISPLAYS are the same object, not two independent computations that could disagree."*

It is reached from all three dispatch paths — `_record_run:984`, `_dispatch:2240`, `_enqueue_single_agent:2381` — and is **idempotent** (returns unchanged if `params["qualityPolicy"]` is already a dict) and **never raises**. `[VERIFIED-WITH-SOURCE]`

**The injection is therefore four lines inside that one function**, after `resolve_policy_for_user` and inside the existing `try`:

```python
        policy = resolve_policy_for_user(user_id)
        # B1b: active directives amend the effective policy. Inside the same
        # try/except that already exists, so a directive-store failure degrades
        # to the baseline policy exactly as a policy-resolution failure does.
        from app.services.agent_directives import effective_policy
        directives = AgentDirectiveRepository().list_active(user_id, agent_key)
        policy = effective_policy(policy, directives)
```

Three consequences the implementer must not have to rediscover:

- **Persistence is inherited for free** — the amended policy is the same object that reaches `AgentRunRepository.start`, **provided §2.4's one-line whitelist extension is made.** Without it the `directives` key is dropped and the loop is silent.
- **`_agent_callable` needs no change for tailor/coverLetter.** They already read `_policy_knobs(params)`; amended knobs simply arrive amended. `[VERIFIED-WITH-SOURCE: `agents.py:1996-2015`]`
- **`agent_key` must reach the seam.** `_with_quality_policy(user_id, params)` has no agent argument today. Add a keyword-only `agent_key: str | None = None`, defaulted, and pass it from the three call sites. A `None` agent key resolves **no** directives (never "all of them") — the honest degrade.

### 4.3 B1c — the storyExtractor binding

**Current code, `agents.py:2016-2019`** `[VERIFIED-WITH-SOURCE]`:

```python
    if name in ("storyExtractor", "story-extractor"):
        from app.agents.story_extractor import StoryExtractorAgent

        return "storyExtractor", (lambda: StoryExtractorAgent().run(user_id))
```

Compare `tailor` (`:1996-2007`) and `coverLetter` (`:2008-2015`), which both compute `knobs = _policy_knobs(params)` and pass `policy_knobs=knobs`. `[VERIFIED-WITH-SOURCE]`

**`storyExtractor` is the one metered T2 content producer that receives no knobs.** Since `_dispatch` stamps the policy regardless, a storyExtractor run today **records a `policyTier` it never obeyed**. `[VERIFIED-WITH-SOURCE — `_dispatch:2240` → `_with_quality_policy` → `AgentRunRepository.start` writes `policyTier`/`metricSnapshot` via `run_policy_fields`, while the binding drops the knobs]` That is a live honesty defect, independent of B1c's loop, and B1c closes it in three lines:

```python
        knobs = _policy_knobs(params)
        return "storyExtractor", (
            lambda: StoryExtractorAgent().run(user_id, policy_knobs=knobs)
        )
```

### 4.4 Composition with B6 (`parentRunId`)

B1a does **not** declare `parentRunId`. It declares `AgentRun.runPlanId` (§2.3), which answers a different question ("which plan was this step part of") from B6's ("which run caused this run").

The seam B6 needs: `execute_run_plan`'s dispatch lambda is `lambda backend, params: _dispatch(user_id, backend, dict(params))`. `[VERIFIED-WITH-SOURCE: P1-A tree]` When B6 lands, that lambda threads B6's parent id in the same way — one keyword, one place. **B1a's requirement on B6 is only this: whatever mechanism B6 chooses (a `ContextVar`, a `_record_run` keyword) must be reachable from a worker thread, because plan steps execute inside `asyncio.to_thread`.** `[VERIFIED-WITH-SOURCE: `workers/tasks.py` P1-A branch]` A request-scoped `ContextVar` set in the HTTP layer would be empty there — the failure would be silent NULLs, not an error. `[INFERRED]`

**Ordering:** B6 lands before or after B1a without conflict, provided both use `ensure_agent_run_*` siblings rather than competing lazy-DDL paths on `AgentRun` (§0.4, B2 row).

### 4.5 Composition with D.524 (generic route → async)

D.524 converts `run_named_agent` (`agents.py:5391-5413`) `[VERIFIED-WITH-SOURCE]` from an unconditional `_dispatch` into the `if async_generation_enabled(): _enqueue_single_agent(...)` shape that `run_tailor:3168-3189` already models. `[VERIFIED-WITH-SOURCE]`

**One rule keeps it compatible with B1a, and it is easy to get wrong:**

> **D.524 must NOT pass `singleton=True`.**

Rationale: after B1a extends `_SINGLETON_AGENTS` to the 6-member silo set, a `singleton=True` enqueue from the generic route would take the same claim a plan step takes. The Agents-screen Run button reaches every agent without a dedicated route through this handler `[VERIFIED-WITH-SOURCE: the handler's own docstring names `runAgent(AGENT_ROUTE[backend] ?? backend)`]`, so a user clicking "Run" on `emailAgent` while a plan holds the claim would get a job id for **work they did not ask for** (P1-A's `singleton` path returns the in-flight job's id, 202, deliberately — `_enqueue_single_agent` docstring `[VERIFIED-WITH-SOURCE]`). Silent substitution is worse than a refusal *and* worse than a duplicate. Keeping the generic route unclaimed preserves exactly today's semantics; P1-A's claim-keyed index (`singletonKey`, not `agentKey`) is precisely what makes an unclaimed enqueue legal. `[VERIFIED-WITH-SOURCE: the shipped index predicate `WHERE "singletonKey" IS NOT NULL`]`

The residual — a plan's `emailAgent` step running concurrently with a user's own `emailAgent` run — is real, is unchanged by D.524, and is **OQ-2**.

---

## 5. API specification

All routes are additive. **No existing endpoint changes shape.**

### 5.1 B1a (as built in the P1-A tree; specified here for review, not re-implementation)

| Method | Path | Auth | Cost | Purpose |
|---|---|---|---|---|
| `GET` | `/agents/orchestration/plan` | owner | **$0** | The plan, before anything runs |
| `GET` | `/agents/orchestration/plans/{planId}` | owner | $0 | A recorded plan + per-step states |
| `POST` | `/agents/orchestration/run-everything` | owner, paid | metered per step | Enqueue ONE plan job |

**`GET /agents/orchestration/plan` → 200**

```jsonc
{
  "concurrency": 1, "concurrencyBasis": "min(worker max_jobs=3, admin dial=1)",
  "spacingSeconds": 5.0,
  "agentCount": 19, "cardCount": 21, "duplicateCardsCollapsed": 2,
  "meteredStepCount": 12, "estimatedCostUsd": 0.0,
  "groups": [["scout"], ["fitScorer"], ["matcher"], ["tailor"], ["coverLetter"], ["submission"], ...],
  "steps": [{
    "key": "fitScorer", "backend": "fitScorer",
    "execClass": "sequential", "dependsOn": ["scout"],
    "coversCards": ["matchScoring", "atsOptimization", "skillGap"],
    "cardNames": ["Match Scoring", "ATS Optimization", "Skill Gap"],
    "onRefusal": "halt-chain", "group": 1, "exclusive": false,
    "siloBasis": null, "unmetDependencies": [], "metered": true,
    "paramsFrom": [],
    "rationale": "Runs after scout; one dispatch covers 3 cards; running alone (ceiling 1), 5s after the previous step."
  }],
  "notes": ["2 duplicate card targets collapsed into their shared backend."],
  "asyncEnabled": true, "runnable": true, "refusal": null
}
```

**R-6 honesty rule, binding on every rationale string:** narration states what the scheduler **DID** — the ceiling and spacing actually in force — never what the execution class would permit. At `AETHER_ORCH_PLAN_CONCURRENCY=1` (the code default, and unset in the deployed `.env` `[VERIFIED-WITH-SOURCE]`) nine `independent` agents still run one at a time, and the plan must say so. `[VERIFIED-WITH-SOURCE: ADR-AGI-3 risk R-6 + the shipped test `test_narration_states_what_the_scheduler_DID_not_what_the_class_permits`]`

**`POST /agents/orchestration/run-everything` → 202**

```jsonc
{"job_id": "...", "planId": "...", "status": "enqueued", "stepCount": 19, "cardCount": 21, "concurrency": 1}
```

**Async-only refusal — the honest status code.** The parent scope says "honest 409/422 when `AETHER_ASYNC_GENERATION` off"; the P1-A build returns **503**. Adjudicate once (OQ-1). This blueprint's reading: **503 is the more honest of the three.** A 409 asserts a conflicting state and a 422 asserts the *request* was malformed; neither is true. The request is well-formed and the state is fine — the **server is not currently configured to do this**, which is what 503 means. Whatever is chosen, the body must name the flag and the remedy:

```jsonc
{"detail": "Run everything requires background execution, which is currently disabled on this deployment (AETHER_ASYNC_GENERATION). Run agents individually, or ask an administrator to enable background generation."}
```

Order of operations, verified in the built handler `[VERIFIED-WITH-SOURCE]`: refusal check → paywall (`_require_active_subscription`) → `RunPlan` row → `BackgroundJob` (`agentKey='orchestrationPlan'`, deliberately **not** a backend name) → ARQ enqueue (failure ⇒ mark job failed + plan failed + honest 503) → 202.

### 5.2 B1b — new

| Method | Path | Auth | Cost | Purpose |
|---|---|---|---|---|
| `GET` | `/agents/directives` | owner | $0 | Active directives for every agent, one round trip |
| `GET` | `/agents/directives/history?agentKey=&limit=` | owner | $0 | Immutable history incl. superseded |

**Deliberately ONE new surface, not two.** `GET /analytics/agent-policy` already returns a `perAgent` array covering every backend-having catalog agent `[VERIFIED-WITH-SOURCE: `routers/analytics.py:297-330`]`, and duplicating directive data into it would create two sources of the same fact — the identical failure mode the corpus calls R-2a and that P1-A's server-side `coversCards` exists to close. The Agents page fetches both and joins on `agentKey`. `[INFERRED]`

**`GET /agents/directives` → 200**

```jsonc
{
  "directives": [{
    "id": "…", "agentKey": "tailor", "status": "active",
    "directive": {"maxIterations": 7, "targetScore": 88.0},
    "clamped": {"maxIterations": {"requested": 12, "applied": 10, "reason": "ceiling"}},
    "rejectedKeys": [],
    "rationale": "Tighten tailoring effort — interview conversion 0.0% over 290 submissions against a 20% target.",
    "metricsCited": {"conversionRate": 0.0, "sampleSize": 290, "target": 0.20},
    "issuedBy": "supervisor-rules",
    "issuedAt": "2026-08-14T…Z", "expiresAt": null
  }],
  "paused": false, "pausedReason": null
}
```

`paused` reflects `AETHER_AGI_DIRECTIVES_ENABLED` (§9). When paused, the array is **still returned** (history is not a lie) and `paused: true` tells the FE to render them as "not currently applied" rather than hiding them.

**There is no `POST` in B1b.** Directives are issued by the Supervisor's rules stage inside the run path, not by an API caller. An operator-issued directive is a P2 surface with its own authorization question. `[INFERRED — from ADR-AGI-2's P1/P2 split]`

### 5.3 Error and quota semantics

Inherited unchanged from the shipped table; the two additions are marked.

| Condition | Status | Body signal | Quota effect |
|---|---|---|---|
| No active paid subscription | 402 | existing paywall payload | nothing reserved |
| Run quota exhausted | 429 | `quota_exceeded` | nothing reserved |
| Spend cap exceeded pre-run | 429 | `spend_cap_exceeded` | reserved run refunded |
| Provider subscription quota | 429 | `QuotaExhaustedError`, `retryAfter` | refunded; **never rerouted to another payer** |
| Provider out of credits (402) | 503-class | `InsufficientCreditsError` | refunded |
| LLM unavailable / circuit open | 503 | honest message | refunded |
| Guard rejected all drafts (T2) | 200 | existing honest degrade | refunded, as today |
| **Run-everything with async off** | **503** (OQ-1) | names the flag + remedy | nothing created |
| **Plan halted mid-flight by 429/402** | 200 on the poll | `{status:"halted", haltedAtStep, haltReason, notAttempted:[…]}` | each *executed* step accounted normally |

**R-2b, restated as a binding review check:** no `skip_quota=True` anywhere in the plan path. Sweep exemptions stay sweep-only. The shipped build asserts this by source inspection of both the executor module and the route `[VERIFIED-WITH-SOURCE: `test_run_everything_never_uses_skip_quota`]`; §7.1 keeps that test.

---

## 6. The directive whitelist

**This table is the whole security boundary of B1b.** A field that is not here cannot be amended by any directive, from any issuer, ever — enforced by `validate_directive` splitting unknown keys into `rejectedKeys` before anything is stored.

Baselines are the shipped values: `_STANDARD` = `{maxIterations: 5, targetScore: 85.0, coverLetterRetries: 2}`, `_HEIGHTENED` = `{7, 88.0, 3}`, `insufficient_data` inherits `_STANDARD`. `[VERIFIED-WITH-SOURCE: `quality_policy.py:117-138`; `DEFAULT_MAX_ITERATIONS = 5` at `tailoring_loop.py:82`, `DEFAULT_TARGET_SCORE = 85.0` at `:85`]`

### 6.1 Addressable fields — the complete list

| Field | Type | Baseline (std / heightened) | Clamp | Tighten direction | Consumer (verified) | Why it is safe to amend |
|---|---|---|---|---|---|---|
| `maxIterations` | int | 5 / 7 | `[baseline, **10**]` | **increase** | `tailor_agent.py:483-486` → `TailoringLoop(max_iterations=…)` → `tailoring_loop.py:379` `for i in range(1, self.max_iterations + 1)` | Pure effort: it changes how many scoring iterations run, nothing about what passes. **This is the one knob with no consumer-side ceiling** — `resolve_loop_knobs` clamps only the floor, so `maxIterations: 999` would be obeyed verbatim. The ceiling of 10 must therefore live in the directive layer. `[VERIFIED-WITH-SOURCE for the missing ceiling]` |
| `targetScore` | float | 85.0 / 88.0 | `[baseline, **95.0**]` | **increase** | `tailor_agent.py:487-490`; early-stop at `tailoring_loop.py:463`, honest verdict at `:510`, prompt text at `:518,531,622-628` | Raising it makes the loop try harder and stop later. It is **not a ship gate** — a sub-target result still ships with `warning` + `requiresReview` `[VERIFIED-WITH-SOURCE]` — so raising it cannot suppress output. Ceiling 95.0 because 100 is unreachable in practice and would burn every iteration for nothing. |
| `coverLetterRetries` | int | 2 / 3 | `[baseline, **4**]` | **increase** | `cover_letter_agent.py:97-103` `_corrective_retry_labels`, consumed at `:1478`/`:1690` | Already clamped `[2,4]` at the consumer (`_MIN_CORRECTIVE_RETRIES=2`, `_MAX_CORRECTIVE_RETRIES=4`) `[VERIFIED-WITH-SOURCE]`. The directive ceiling **matches** the consumer's rather than exceeding it, so a directive can never encode a number the consumer will silently discard. |
| `storyEvidenceStrictness` | enum `standard` \| `strict` | `standard` | `{standard, strict}` | **restrict-enum**: `standard→strict` only | B1c `story_extractor._criteria` → `_reject_reason` | The only new field, and it only ever *narrows* what the validator accepts. `strict` raises the STAR body minimum and requires the per-bullet employer binding rather than accepting the résumé-wide fallback. It cannot make the validator accept anything it rejects today. `[INFERRED — from the verified `_reject_reason` structure at `story_extractor.py:398-465`]` |

**Ratchet arithmetic (§3.2):** `applied = min(ceiling, max(baseline, requested))` for every increase-direction field; enum fields advance only along the declared order. A directive requesting a *lower* value is a recorded no-op with reason `ratchet`. There is no branch that can lower a baseline, so the ratchet cannot be forgotten by a future edit — it is the only arithmetic available. `[INFERRED]`

### 6.2 NOT addressable — enforced by absence, and by a test that names each one

None of the following is reachable through `params["qualityPolicy"]["knobs"]` today, and B1b's job is to keep it that way. Test T-B7 (§7.2) asserts each name is absent from `DIRECTIVE_FIELDS` **by name**, so a future addition has to delete an assertion that says why it exists.

| Category | Specific names | Why never |
|---|---|---|
| **Tier-decision thresholds** | `INTERVIEW_CONVERSION_TARGET` (0.20), `DIMENSION_FLOOR` (80.0), `MIN_SAMPLE_SIZE` (5) — `quality_policy.py:61,66,73` | These decide the tier. Amendable, a Supervisor could talk itself down to `standard` — the loop grading its own homework. **Note:** after B2/u2c lands, `DIMENSION_FLOOR` is *bound* to `quality_gate.QUALITY_FLOOR`, so one directive would move the tailoring floor and the cover floor together. `[VERIFIED-WITH-SOURCE]` |
| **Honesty gates** | `services/fabrication_guard.py`, the entailment window at `services/resume_tailor.py:2743`, `story_extractor._reject_reason` / `_ground_narrative` acceptance direction | ADR-AGI-2: "Honesty gates … are NOT directive-addressable." A guard the agent can relax is not a guard. |
| **Spend and quota** | spend cap, `skip_quota`, `system_run`, run quota, `AETHER_LLM_*` budget seconds | ADR-AGI-2 explicitly. Also R-2b. |
| **Approval gates** | `_APPROVAL_GATED` membership (`agents.py:120-124`), `ApprovalRequest` status | The path from model output to a real-world effect must stay through a row the model cannot write. |
| **Model / credential routing** | model id, provider, `authMode`, `credentialRef`, fallback chain | A directive that redirects a model redirects a **payer**. Structurally separate concern (ADR-AGI-3 D3, F7/F8). |
| **Execution classes** | `execClass`, `siloBasis`, `onRefusal`, `dependsOn`, `coversCards` | Charter data is re-verified against code under R-8. A runtime amendment would bypass that gate entirely. |

### 6.3 Stage-1 rules that issue directives (deterministic, $0)

Ordered; first match per agent wins; a proposal equal to the active directive is not re-issued (idempotence, §3.2).

| # | Condition (all from the metric snapshot `quality_policy` already computes) | Directive | Rationale template |
|---|---|---|---|
| S1 | `tier == 'heightened'` and `'conversion_below_20pct_target' in triggers` | `tailor: {maxIterations: +2 over effective, targetScore: +3.0}` | "Tighten tailoring effort — interview conversion {rate} over {n} submissions against a {target} target." |
| S2 | `tier == 'heightened'` and any `dimension_below_80pct_floor:*` trigger | `coverLetter: {coverLetterRetries: +1}` | "Tighten cover-letter correction — {dimension} scored {score} against the {floor} floor." |
| S3 | `tier == 'heightened'` and `storyCount == 0` | `storyExtractor: {storyEvidenceStrictness: 'strict'}` | "No evidence bank yet — hold story extraction to the strict evidence bar so the first stories are the good ones." |
| S4 | `tier` returned to `standard` and an active directive exists | *(retire)* | "Metrics recovered — returning {agent} to baseline rigor." |
| S5 | otherwise | none | — |

**Retirement is a supersede, never a delete** (§2.2). **No rule may lower a baseline** — S4 retires the amendment so the baseline reasserts itself, which is a different thing from issuing a loosening directive, and the ratchet arithmetic makes the latter impossible anyway. `[INFERRED]`

---

## 7. Test plan — failing tests first

**Discipline (binding on every implementer):** each suite is written and observed **RED against the pre-change tree** before any production line is written, and the RED output is filed to `uat/reports/evidence/market-perf/u-agi/b1/`. A "failing" test that passes against current code is itself a defect. **Do not run the suites in the design tree while a baseline run holds it** — implementers work in their own worktree.

### 7.1 B1a — `apps/api/tests/`

The P1-A tree already carries six suites (~114 tests). They are **kept**, plus:

| Test file | Test | Asserts | Kind |
|---|---|---|---|
| `test_uagi_p1a_charter.py` *(extend)* | `test_the_charter_matches_the_r8_verified_table` | All 19 rows equal §1.1 field-for-field, incl. the 2 tier-conservative bases | regression |
| ″ | `test_every_t3_actor_is_siloed_against_declared_tiers` | Uses the new `AGENT_TIER` data (§1.4), **not** `_APPROVAL_GATED` minus a hardcoded pair | **boundary** |
| ″ | `test_agent_tier_covers_every_runnable_backend_exactly_once` | `set(AGENT_TIER) == _RUNNABLE_BACKENDS` | boundary |
| `test_uagi_b1a_supervisor_plan.py` **(new)** | `test_the_supervisor_output_plan_equals_the_scheduler_derivation` | `sup["plan"] == build_plan(charter, targets=_PIPELINE_BACKENDS)` order | **boundary** — this is the zero-regression proof of §4.1 |
| ″ | `test_the_derived_pipeline_order_is_still_the_shipped_five` | Derivation `== ["scout","fitScorer","matcher","tailor","coverLetter"]` | **boundary** — a charter edit that reorders the user's pipeline fails here, loudly |
| ″ | `test_the_supervisor_records_a_plan_row_and_returns_its_id` | `planId` present, row exists, `initiator == 'pipeline'` | integration |
| ″ | `test_the_supervisor_still_makes_no_llm_call` | No model call; run cost `0.0`; `supervisor` still in `_DETERMINISTIC_BACKENDS` | **boundary** — cost |
| ″ | `test_a_plan_row_failure_never_fails_the_pipeline` | Repository raising ⇒ supervisor still returns the plan list; pipeline completes | **boundary** — degrade |
| `test_uagi_b1a_run_plan_repo.py` **(new, closes D-3)** | `test_the_advisory_lock_is_not_shared_with_another_table` | `_RUN_PLAN_LOCK` differs from every other in-tree lock id | **boundary** |
| ″ | `test_first_terminal_write_wins` / `test_mark_running_is_replay_safe` / `test_record_step_state_rewrites_only_its_own_element` | repository semantics directly | unit |
| `test_pipeline.py` *(unchanged)* | `:57` | Stays green with **no edit** | regression |

### 7.2 B1b — `apps/api/tests/`

| Test file | Test | Asserts | Kind |
|---|---|---|---|
| `test_uagi_b1b_directive_whitelist.py` | `test_only_whitelisted_fields_survive` | Unknown keys land in `rejectedKeys`, never in `directive` | **boundary** |
| ″ | `test_an_unwhitelisted_key_is_rejected_loudly_not_dropped` | `rejectedKeys` non-empty and persisted | **boundary** |
| ″ | `test_honesty_gates_are_absent_from_the_whitelist` (parametrized over every name in §6.2) | Each name absent from `DIRECTIVE_FIELDS` | **boundary** — the security assertion |
| ″ | `test_a_directive_can_never_lower_a_baseline_knob` (property test over random baselines × random requests) | `applied >= baseline` for every increase field, always | **boundary** — the ratchet |
| ″ | `test_a_value_above_the_ceiling_is_clamped_and_the_clamp_is_recorded` | `applied == ceiling`, `clamped[field].requested` preserved | **boundary** |
| ″ | `test_cover_letter_retries_ceiling_matches_the_consumers` | Directive ceiling == `_MAX_CORRECTIVE_RETRIES` | **boundary** — drift guard |
| ″ | `test_max_iterations_has_a_ceiling_the_consumer_lacks` | `maxIterations: 999` ⇒ 10 | **boundary** |
| `test_uagi_b1b_injection.py` | `test_an_active_directive_amends_the_policy_the_agent_obeys` | `_policy_knobs` returns amended values | integration |
| ″ | `test_the_amended_policy_is_the_one_persisted_on_the_run` | `AgentRun.metricSnapshot["directives"]` present — **fails without §2.4** | **boundary** — the silent-drop trap |
| ″ | `test_a_directive_store_failure_degrades_to_the_baseline_policy` | Repo raising ⇒ baseline knobs, run completes | **boundary** — degrade |
| ″ | `test_no_agent_key_resolves_no_directives` | `agent_key=None` ⇒ zero applied, never all | **boundary** |
| ″ | `test_the_seam_stays_idempotent` | Second call leaves an already-stamped params dict untouched | regression |
| `test_uagi_b1b_directive_store.py` | `test_a_directive_is_never_edited_only_superseded` | No mutating write on `directive`/`rationale`; old row `superseded` + `supersededById` | **boundary** — immutability |
| ″ | `test_two_active_directives_for_one_agent_are_impossible` | Concurrent issue ⇒ unique violation handled, exactly one active | **boundary** — race |
| ″ | `test_history_survives_supersession` | Superseded rows still returned by history | regression |
| `test_uagi_b1b_supervisor_rules.py` | `test_the_rules_stage_makes_no_llm_call` | Zero model calls; `$0` | **boundary** — cost |
| ″ | `test_no_rule_can_propose_a_loosening` | Every rule's proposal ≥ baseline on every field | **boundary** |
| ″ | `test_reevaluation_does_not_churn_history` | Same metrics twice ⇒ one directive row | **boundary** — idempotence |
| ″ | `test_a_recovered_tier_retires_the_directive_it_does_not_invert_it` | S4 supersedes; no loosening directive is written | **boundary** |
| `test_uagi_b1b_directives_api.py` | owner-scoping (another user's ⇒ 404, never a confirmation), `$0`, `paused` honesty | integration |

### 7.3 B1c — `apps/api/tests/`

| Test file | Test | Asserts | Kind |
|---|---|---|---|
| `test_uagi_b1c_story_policy.py` | `test_the_story_extractor_now_receives_the_knobs_it_records` | The binding passes `policy_knobs`; the run's `policyTier` matches what was obeyed | **boundary** — closes the live honesty defect (§4.3) |
| ″ | `test_empty_knobs_reproduce_todays_behaviour_exactly` | `{}` ⇒ output identical to the pre-change tree on a fixed fixture | **boundary** — regression firewall |
| ″ | `test_strict_strictness_only_narrows_acceptance` (property test) | Every story accepted under `strict` is accepted under `standard`; never the converse | **boundary** — the ratchet, for the enum |
| `test_uagi_b1c_corrective_loop.py` | `test_a_rejected_story_gets_exactly_one_corrective_attempt` | Call count == 1 extra, never 2 | **boundary** |
| ″ | `test_the_correction_carries_the_validators_own_reason` | The re-prompt contains the `_reject_reason` string verbatim | **boundary** — no paraphrase |
| ″ | `test_a_story_still_rejected_after_correction_is_dropped_honestly` | Dropped, **both** reasons recorded, no fabricated acceptance | **boundary** — the honesty case |
| ″ | `test_correction_never_runs_before_first_pass_coverage` | With N chunks, all N attempted before any correction | **boundary** — R3 bound 1 |
| ″ | `test_correction_is_skipped_when_the_budget_is_below_the_chunk_floor` | `remaining < 15.0` ⇒ no extra call, honest note | **boundary** — R3 bound 2 |
| ″ | `test_the_corrective_pass_never_loosens_the_validator` | Same criteria object on both passes | **boundary** |
| ″ | `test_the_outcome_signal_is_recorded_on_the_run` | `accepted_first_pass`, `accepted_after_correction`, `dropped`, reason histogram on the run output | integration |
| ″ | `test_directive_adherence_is_recorded_when_a_directive_was_active` | `AgentRun.directiveId` set; `AgentDirective.outcome` merged | integration |
| `test_uagi_b1c_upload_path.py` **(the missed surface)** | `test_the_upload_path_gets_the_same_criteria_as_the_agent_route` | `resumes.py:354` dispatch resolves the same knobs | **boundary** |
| ″ | `test_a_correction_failure_never_raises_into_the_upload_handler` | No new exception class escapes; a still-rejected story is dropped, and the upload response is unchanged | **boundary** — the silent-absorption trap (`resumes.py:362-363`) |
| ″ | `test_the_upload_stays_within_its_budget_with_correction_on` | Flag ON + exhausted budget ⇒ no extra call, upload still returns | **boundary** — latency |

### 7.4 Existing suites at risk, and why each is safe

| Suite | Why it could break | Why this design does not break it |
|---|---|---|
| `test_pipeline.py` (`:57` asserts the exact 5-element plan) | §4.1 replaces the constant with a derivation | The charter's pipeline sub-graph is a strict chain ⇒ unique topological order ⇒ identical list. The assertion is left **unedited** and becomes the proof. `[INFERRED, §4.1]` |
| `test_uax_rigor_policy.py`, `test_uax_analytics_agent_policy_api.py`, `test_uax_r3_provenance.py`, `test_uax_r3_policy_progress.py` | B1b touches the policy seam and the snapshot shape | Baseline knobs are unchanged; `directives` is an **added** key. Any assertion using exact-dict equality on the snapshot must be located during RED and adjusted deliberately — flagged as the single most likely breakage. `[INFERRED]` |
| `test_story_*` (15 files), `test_ustory1_s*` (5) | B1c changes the extractor | `policy_knobs=None/{}` reproduces today's behaviour byte-for-byte, pinned by `test_empty_knobs_reproduce_todays_behaviour_exactly`. Existing suites pass no knobs. `[INFERRED]` |
| Résumé-upload suites (any test exercising `POST /resumes` with `extract_stories`) | B1c's loop also runs on `resumes.py:354` | `AETHER_AGI_STORY_CORRECTION` is code-default OFF, so the upload path is byte-identical until it is enabled; pinned by `test_a_correction_failure_never_raises_into_the_upload_handler`. **This is the suite set most likely to be missed during RED** — locate it explicitly. `[INFERRED]` |
| `test_gap_p7_async_001.py`, `test_gap_p7_async_concurrency.py`, `test_mon020_async_scout.py` | B1a extends `_SINGLETON_AGENTS` and replaces the singleton index | P1-A's index is keyed on `singletonKey`, not `agentKey`, so an **unclaimed** enqueue is never blocked — pinned by the shipped `test_an_unclaimed_enqueue_is_never_blocked_by_the_claim_index`. `[VERIFIED-WITH-SOURCE]` |
| `test_gap_p6_paywall.py`, `test_gap_p6_billing.py`, `test_ml_w14_served_model_billing.py`, `test_sfix_s4_board_sweep_spend_cap.py` | R-5 fields + the plan's quota path | R-5 fields are additive on `AgentRun.output` (already `z.record` on the FE); no quota logic changes; no `skip_quota`. `[VERIFIED-WITH-SOURCE]` |
| `test_u1x_b_orchestrator_role.py`, `test_ml_agents_refix.py`, `test_ml_f1_f3_run_route_and_agent_list.py` | Supervisor role/model plumbing | The supervisor still makes no LLM call and stays in `_DETERMINISTIC_BACKENDS`; pinned by `test_the_supervisor_still_makes_no_llm_call`. |
| `apps/web` vitest (`agent-policy-panel`, `orchestration*`, `run-policy-inputs`) | §8 adds FE display | Additive fields only; the panel renders directives when present and is unchanged when absent. |

---

## 8. Frontend — minimal display spec (B1b)

Scope: **display only.** No control issues, edits, or cancels a directive in B1. `[INFERRED — from ADR-AGI-2's P1 scope, "Agents-page directive display"]`

**Data:** the Agents page already fetches `GET /analytics/agent-policy` (whose `perAgent` array covers every backend-having catalog agent `[VERIFIED-WITH-SOURCE: `analytics.py:297-330`]`). Add one fetch of `GET /agents/directives` and join on `agentKey`.

**8.1 `AgentPolicyPanel` (`apps/web/src/components/agents/AgentPolicyPanel.tsx`, 141 lines) — one additive block.** The panel already renders tier, "Why this tier" triggers, and the `behaviour` paragraph. `[VERIFIED-WITH-SOURCE]` Below `behaviour`, when any directive is active:

> **Supervisor directives (2 active)** — the tier above is the baseline; these tighten it further.
> · *Résumé Tailoring* — up to **7** scoring iterations (baseline 5), ATS target **88** (baseline 85)
> · *Cover Letter* — **3** corrective retries (baseline 2)

Honesty rules, mirroring the panel's existing ones: never render a directive as the *tier*; always show baseline beside amended so "tightened" is legible as a delta; when `paused: true`, render the block greyed with "not currently applied — directive issuance is paused".

**8.2 Per-agent card popover.** Each agent card gains a small badge when it has an active directive (label: **Directed**). The popover shows, in this order:

1. the amended knobs with baselines beside them;
2. the **rationale verbatim from the API** — the FE never composes its own explanation;
3. the metrics cited, as figures with their targets;
4. `issuedAt`, and `expiresAt` when set;
5. any `clamped` entry, rendered plainly: *"Supervisor asked for 12 iterations; the ceiling is 10."* — the clamp is a product-honesty feature, not an internal detail;
6. a "View history" link → `GET /agents/directives/history`.

**8.3 What the FE must not do.** No directive-derived edge on the orchestration map in B1 (map topology claims are gated on P1-A being live per ADR-AGI-3 D2's honesty gate `[VERIFIED-WITH-SOURCE]`). No "the Supervisor is learning" copy — B1's Stage-1 is a rule table, and saying otherwise would be the fabricated-capability failure the corpus legislates against. `[INFERRED]`

---

## 9. Rollout and reversibility

### 9.1 Flags — all additive, all code-default OFF or conservative

Convention verified: `AETHER_*` flags are **not** in `config.py`; each is read via `os.environ.get(...)` **at call time** so a hot env change takes effect and no flag is baked into source. `[VERIFIED-WITH-SOURCE: `agents.py:2310-2320` and its docstring]` Booleans use an explicit off-set (`_ASYNC_OFF`), never truthiness.

| Flag | Code default | Effect when off/unset |
|---|---|---|
| `AETHER_ASYNC_GENERATION` | `false` (prod `.env`: on `[VERIFIED-WITH-SOURCE, by count]`) | Run-everything refuses honestly; nothing else changes |
| `AETHER_ORCH_PLAN_CONCURRENCY` | `1` (absent from prod `.env` `[VERIFIED-WITH-SOURCE]`) | Plan runs strictly serial; class narration says so (R-6) |
| `AETHER_ORCH_PLAN_SPACING_SECONDS` | `5` | Inter-step spacing |
| **`AETHER_AGI_DIRECTIVES_ENABLED`** | **`false`** | `effective_policy` returns the baseline unchanged; agents run on tier defaults; **history is retained and still displayed** (ADR-AGI-2 reversibility clause) |
| **`AETHER_AGI_DIRECTIVES_AGENTS`** | *(empty = all)* | Per-agent pause, comma list |
| **`AETHER_AGI_SUPERVISOR_STAGE2`** | **`false`** | ADR-AGI-1 LLM escalation stays off. **B1b never turns this on**; it is gated on AGI-02's 14-day shadow per approval #3 `[VERIFIED-WITH-SOURCE]` |
| **`AETHER_AGI_STORY_CORRECTION`** | **`false`** | B1c's corrective pass is skipped; knob consumption still applies (the honesty fix is not behind the cost flag) |

`.env` writes go through the existing `services/env_file_writer.py` seam (`AETHER_ENV_FILE_PATH` `[VERIFIED-WITH-SOURCE]`). **PROBE-AGI-07 stands and is a deploy prerequisite:** confirm that module does temp-write + `os.replace` + mode `0600`. If it does not, that is a prerequisite fix, not part of this design. `[ASSUMED-PENDING-PROBE: PROBE-AGI-07]`

### 9.2 Infrastructure

**No new systemd unit.** Everything runs inside the existing `deploy/aether-api.service` and `deploy/aether-worker.service`. `[VERIFIED-WITH-SOURCE: `deploy/` listing]` Redis is present and active (`/usr/bin/redis-server`; `systemctl is-active` → `active`) `[VERIFIED-WITH-SOURCE]` — the async prerequisite for B1a's queue path is satisfied at the infrastructure layer. Worker capacity is `max_jobs = 3` (`workers/settings.py:107`, comment: "2 vCPU / ~2.5 GB free -> modest concurrency") `[VERIFIED-WITH-SOURCE]`, which is exactly the `MAX_PLAN_CONCURRENCY` the planner clamps to.

### 9.3 Security constraints (binding)

1. **No token, key, or OAuth secret in a directive, a plan row, a rationale, a log line, or an SSE frame.** Directives carry only whitelisted numeric/enum knobs (§6) — the schema makes credential material unrepresentable rather than filtered. `[INFERRED — from the whitelist being closed]`
2. **No secrets in source.** Every new knob is env-read at call time (§9.1).
3. **No silent credential-type fallthrough.** B1b/B1c add no credential path. B1a inherits P1-A's F7/F8 separation, whose deploy-blocking probe is carried forward as G-2 (§9.4).
4. **No fixture content on any production path.** `AETHER_LLM_MODE` code-default is `replay`; production must remain `auto`. `[VERIFIED-WITH-SOURCE: `llm_client.py:588`]` B1c's corrective retry is a live call or an honest failure — never a replay.
5. **User isolation on every new read.** `AgentDirectiveRepository` and `RunPlanRepository` are keyed by `userId`; another user's row is a **404, never a confirmation of existence**. `[VERIFIED-WITH-SOURCE: the shipped `get_for_user` + `test_a_plan_belongs_to_its_owner_alone`]`
6. **No destructive DDL.** §2 is `CREATE TABLE IF NOT EXISTS` / `ADD COLUMN IF NOT EXISTS` / `CREATE INDEX IF NOT EXISTS` only. **One exception exists and must be named:** P1-A's `_ensure_table` **drops** a same-named singleton index whose definition is wrong, and drops the superseded `BackgroundJob_active_singleton_idx` *after* confirming the replacement exists. `[VERIFIED-WITH-SOURCE]` Prod holds the original scout-only index (§1.2), so on production this is one index replacing another with a strictly wider guarantee, inside one savepoint. It is a deliberate, reviewed exception, not an oversight.

### 9.4 Gates before deploy

| Gate | What | Status |
|---|---|---|
| **G-1** | `submission`'s DB backstop is absent on prod (7 violating pairs / 36 extra rows, §1.2). Either reconcile the rows so `ensure_application_unique_active_index` can create the index, **or** record explicitly that the `submission` silo rests on the `BackgroundJob` claim alone. | **OPEN — blocks the first Run-everything, not the merge.** PROBE-R8-2 answered by this review. |
| **G-2** | P1-A's F8 change makes `resolve_user_credential` refuse the operator's *subscription* row for user-content generation. If the deployment-wide `ProviderCredential('anthropic')` row is a subscription, users (including the owner) running a bare `claude-*` with no credential of their own get an honest no-credential error where the owner's session previously served them. | **OPEN — blocking for deploy, not for merge.** Read `authMode` of that row and decide. `[ASSUMED-PENDING-PROBE — flagged by the P1-A build; not re-probed here because it requires reading credential rows]` |
| **G-3** | Advisory-lock D-1 corrected to `7420260815` before any `RunPlan` DDL runs in an environment that also has `Offer`. | **OPEN — blocks merge.** |
| **G-4** | RED evidence filed for all three tickets before any production line is written. | Standing. |
| **G-5** | Live `$0` verification of `GET /agents/orchestration/plan` on prod after deploy. Baseline captured this session: the route returns **404** today. `[VERIFIED-WITH-SOURCE: live curl]` The **19-dispatch Run-everything is NOT burned in tests — the first full run is the owner's.** `[VERIFIED-WITH-SOURCE: ADR-AGI-3 risk holds]` | Standing. |

### 9.5 Net-code ledger — honest, including the debt

**B1 as a whole is net code POSITIVE. Nothing is deleted in this phase, so nothing is claimed.**

| Ticket | Production statements | Deletes |
|---|---|---|
| B1a (already built) | **+610** measured by AST against `origin/main`, excluding tests `[VERIFIED-WITH-SOURCE: BUILD-P1A §5]` | nothing |
| B1a (this blueprint's additions: stub replacement, `AGENT_TIER`, D-1 fix) | ~+40, −1 (`_PIPELINE_PLAN` literal becomes a derivation) `[INFERRED — estimate]` | one constant |
| B1b | ~+250 across 3 new modules + 1 route + 4 lines at the seam `[INFERRED — estimate]` | nothing |
| B1c | ~+80 in one file `[INFERRED — estimate]` | nothing |

**This overshoots ADR-AGI-3's E1 estimate of "break-even to +200", and the estimate was wrong rather than the build being bloated** — the estimate priced a plan builder plus one executor loop, and did not price the endpoints, the F7/F8 resolver work, or R-5. `[VERIFIED-WITH-SOURCE: BUILD-P1A §5 reaches the same conclusion from its own measurement]`

**A correction to ADR-AGI-2's net-reduction expectation.** The ADR says directives "replace hardcoded per-agent tuning wherever it exists today (the current `knobs_for_tier` mapping becomes the first directive-issued content, retiring its hardcoded consumer paths)". **There is no per-agent tuning to retire.** `knobs_for_tier` is per-**tier**, not per-agent — three knobs, three tiers, one mapping `[VERIFIED-WITH-SOURCE: `quality_policy.py:117-138`]` — and it remains the **baseline authority** that directives amend. Retiring its consumers would delete the floor the ratchet ratchets *from*. B1b therefore deletes nothing, and this document records that rather than manufacturing a deletion to satisfy the law. `[INFERRED]`

**Deletion debt, with refs-proof — carried, not paid, in B1:**

| Debt | Size | Owner phase | Proof it is still referenced |
|---|---|---|---|
| Client batch runner `apps/web/src/components/agents/orchestration-run-plan.ts` (E3) | 206 lines | **P1-B** | Imported at `OrchestrationMap.tsx:110`, driven by `runPlan` at `:1408`/`:1473` `[VERIFIED-WITH-SOURCE]` |
| `workers/board_sweep.py` user-stretch (E2) | 1,242 lines total | **P2** | Live worker path; ADR-AGI-3 defers it explicitly `[VERIFIED-WITH-SOURCE]` |
| `workers/apply_sweep.py` pending-transmissions (E2) | 739 lines total | **P2** | Live; also being modified by u5d3 right now `[VERIFIED-WITH-SOURCE]` |
| `run_discovery_sweep` (`agents.py:3029-3030`) | ~100 lines | **P2** | Live route |
| `_pipeline_core`'s hand-threaded sequence | ~120 lines | **P2** | §4.1 deliberately preserves it |

**Honest statement for the ADR ledger: P1 cannot yet delete `board_sweep`/`apply_sweep` — that is P2 per ADR-AGI-3 — and P1 does not delete the client batch runner either, because that is P1-B. The net reduction the programme promises is real but is banked in E2/E3, and B1 does not draw on it.**

---

## 10. Deviations from the ADR corpus

| # | Deviation | Rationale |
|---|---|---|
| **DEV-1** | **Charter `coverLetter.dependsOn` = `("tailor","matcher")`**, where the R-8 proof table says `("tailor",)`; and `tailor`/`coverLetter` carry a `paramsFrom` field the proof table does not define. (Inherited from the P1-A build; **accepted**.) | `paramsFrom` makes the `job_id` that `_pipeline_core` threads by hand into charter DATA, which is what lets a plan carry a real target without the scheduler knowing what a job is — and lets a matcher that selected nothing produce an honest `not_attempted` instead of a raw 422. The planner refuses a `paramsFrom` edge without a matching **direct** `dependsOn`, which forces the extra edge. **The edge is provably redundant, not new information:** `matcher → tailor → coverLetter` already orders `matcher` first, so no plan changes shape, and `halt-chain` propagation is identical because the executor marks *transitive* dependents. `[INFERRED — graph reasoning over the verified rows]` A field-by-field diff of all 19 rows against `EXEC-CLASSES.json` returns exactly these three differences. `[VERIFIED-WITH-SOURCE]` |
| **DEV-2** | **The supervisor stub replacement does not route `_pipeline_core` through the plan executor** — it only makes the supervisor's recorded plan a real derivation. | Handing the pipeline's execution to the executor in the same change would put five carefully-degraded error paths (`NoChangesApplied`, `FabricationError`/`StructuralError`, the `top_job_id` early return, the shared budget window, the approval tail) at risk for no user-visible gain. ADR-AGI-3 puts that consolidation in **P2**. §4.1. `[INFERRED]` |
| **DEV-3** | **ADR-AGI-2's net-code-reduction expectation for directives is not met, and the ADR's premise is corrected.** | There is no per-agent tuning in the codebase to retire; `knobs_for_tier` is per-tier and must survive as the ratchet's baseline. §9.5. `[VERIFIED-WITH-SOURCE]` |
| **DEV-4** | **`AGENT_TIER` is introduced as new declared data**, which no ADR asks for in P1 (U-AGI §5.4 assumes it exists). | Charter self-test #6 is otherwise forced to derive T3 by subtracting a hardcoded pair from `_APPROVAL_GATED`, encoding an undeclared assumption that rots the first time a T2 agent becomes approval-gated. §1.4. `[VERIFIED-WITH-SOURCE: no `AGENT_TIER` in code]` |
| **DEV-5** | **Run-everything's async refusal is 503, not the 409/422 named in the ticket.** | The request is well-formed and the state is not in conflict; the server is not configured to perform it. Raised as **OQ-1** rather than decided unilaterally, because it is a user-visible contract. `[INFERRED]` |
| **DEV-6** | **B1b ships no `POST` to issue a directive**, though ADR-AGI-2's user-visibility section could be read as implying operator control. | P1 scope in the ADR is "issuance by the Supervisor's rules stage + display". An operator-issued directive raises an authorization question (who may tighten another user's agents?) that belongs in P2. `[INFERRED]` |

---

## 11. Open questions requiring a fable-5 ruling BEFORE implementation

Kept to the five that genuinely cannot be settled from evidence.

**OQ-1 — What status does Run-everything return when async is off?** Ticket says 409/422; the built code says 503; §5.1 argues 503. *This blueprint recommends 503 with a body naming the flag and the remedy.* One-word ruling.

**OQ-2 — Does a user-initiated run of a silo agent refuse while a plan holds the claim?** A plan's silo claim excludes another *claim*; it does not exclude a route-enqueued `emailAgent`. Two readings: **(a)** acceptable — the plan issues one dispatch per backend and the route is user-initiated, so the user is the serialization point; **(b)** insufficient — the shared Gmail credential refresh spans processes regardless of who started the run. Closing (b) means the route must refuse with a 409 while a claim is held, which is a **user-visible product change** and outside an implementer's authority. **D.524 raises the stakes** (§4.5). *Recommendation: (a) for B1, with (b) filed as a P1-B product decision.*

**OQ-3 — Does a second `RunPlan` for the same user get refused?** The 13 non-silo steps are unprotected: two rapid clicks or two tabs produce two plans and up to 26 duplicate **metered** dispatches. **(a)** refuse — a partial unique index on `RunPlan("userId") WHERE status IN ('planned','running')`, ~8 statements, atomic; but a plan whose worker is SIGKILLed stays `running` and locks the user out with no watchdog. **(b)** allow — let P1-B disable the control while a plan is live. *Recommendation: **(a) together with a staleness release**, and the release already has a shipped precedent to copy — `_apply_stale_watchdog` (`agents.py:2558`), which `_enqueue_single_agent` uses at `:2409-2413` for exactly this "dead worker must not lock the user out" problem.* `[VERIFIED-WITH-SOURCE]` That precedent is why (a) is now recommendable where the build record could only flag the risk.

**OQ-4 — Sequencing of B1b against B2/u2c.** Both modify `quality_policy.py` and `repositories/agent_run.py`; u2c is built-uncommitted and rebinds `DIMENSION_FLOOR` to a shared `QUALITY_FLOOR`. *Recommendation: land u2c first, then B1b rebases onto the shared floor.* Needs a ruling because it re-orders two claimed tickets.

**OQ-5 — Is `storyExtractor` moved onto the async path?** It is the only metered content producer that is synchronous-only, so B1c's corrective pass spends the 180 s HTTP budget rather than the 300 s worker budget (§3.3). Moving it is D.524-adjacent, out of B1c's scope as written, and would change a user-visible response shape (200 → 202 + poll). *Recommendation: **no** for B1c — bound the loop instead (R3) — and file the move as a D.524 follow-on.*

---

## Appendix A — probes run by this task

| Probe | Result | Tag |
|---|---|---|
| Live health | `200 {"status":"ok","version":"0.2.0"}` | `[VERIFIED-WITH-SOURCE]` |
| `GET /api/agents/orchestration/plan` on prod | **404** — P1-A is not deployed | `[VERIFIED-WITH-SOURCE]` |
| `GET /api/agents/catalog` on prod | 401 (auth required) — counts in §1 are code-derived by AST, **not** live-API-verified | `[VERIFIED-WITH-SOURCE]` / `[ASSUMED-PENDING-PROBE: PROBE-R8-LIVE]` |
| Design-tree `DATABASE_URL` == deployed `.env` | identical (`sha256[:12] cf5a114fd001`), so DB probes describe production | `[VERIFIED-WITH-SOURCE]` |
| **PROBE-R8-2** `Application_user_job_active_key` | **ABSENT**; 7 violating pairs / 36 extra rows over 634 `Application` rows | `[VERIFIED-WITH-SOURCE]` |
| **PROBE-R8-3** duplicate `EmailThread` | **0** duplicate groups over 433 rows | `[VERIFIED-WITH-SOURCE]` |
| `BackgroundJob` index state on prod | original scout-only `BackgroundJob_active_singleton_idx` | `[VERIFIED-WITH-SOURCE]` |
| `RunPlan` / `AgentDirective` exist? | No — 33 tables in `aether`, neither present | `[VERIFIED-WITH-SOURCE]` |
| `AgentRun` live columns | 17; no `parentRunId`, no directive column; `status` is a Postgres enum | `[VERIFIED-WITH-SOURCE]` |
| Advisory-lock inventory | highest in use `7420260814`; `7420240724` double-claimed (D-1) | `[VERIFIED-WITH-SOURCE]` |
| Redis / worker capacity | `redis-server` present, unit active; `max_jobs = 3` | `[VERIFIED-WITH-SOURCE]` |
| `AETHER_ASYNC_GENERATION` in deployed `.env` | present and `=true` (matched by count; no value printed) | `[VERIFIED-WITH-SOURCE]` |

## Appendix B — instructions to implementer agents

1. **Read §0 first.** If you are assigned B1a and you start writing a scheduler, stop — it exists.
2. Work in your own worktree. **Do not run pytest or pnpm in `aether-wt-orch-exec`** — a baseline suite holds that tree.
3. RED before GREEN, evidence filed to `uat/reports/evidence/market-perf/u-agi/b1/`. That directory is gitignored by repo convention (`uat/reports/.gitignore:1`) and will **not** travel with your branch — say so in your report rather than assuming a reviewer can see it. `[VERIFIED-WITH-SOURCE]`
4. Every line number in this document is from `7be085a`. Re-resolve before editing; report drift rather than absorbing it.
5. `git commit --only <paths>` — never bare `git add .`. Other agents have staged work in adjacent trees.
6. You do not approve your own work, and this blueprint is not approval to begin.
