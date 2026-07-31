# W-C TailoringLoop — verification / completion report

Agent: ai-loop-engineer. Run timestamp: 2026-07-31T07:27:51Z (all command output below captured
this run unless marked otherwise). Repo: `/home/ubuntu/github_repos/aether-job-career-agent`
(not a git repo per env banner, but is one in practice — `git log`/`git show` all work; treated
as the working repo throughout).

## 1. Starting state — what the prior (token-killed) agent left

`git show --stat HEAD` at session start `[VERIFIED]`:

```
commit 18be1a8 wip(gm-v2): W-C TailoringLoop partial + analytics/approvals/admin screen evidence (UNVERIFIED)
 apps/api/app/agents/tailor_agent.py                |  79 ++++-
 apps/api/app/routers/agents.py                     |   3 +
 apps/api/app/routers/analytics.py                  |  40 ++-
 apps/api/app/services/tailoring_loop.py            | 262 +++++++++++++++
 .../screens/analytics-screen-test.md               | 354 ++++++++++++++++++++-
 5 files changed, 713 insertions(+), 25 deletions(-)
```

I read every line of `tailoring_loop.py` (new, 262 lines) and the full diffs to
`tailor_agent.py`, `routers/agents.py`, `routers/analytics.py` before writing or changing
anything, per the "do not start over" instruction.

**Assessment: the prior agent's work was substantively COMPLETE and correct, not partial.**
Specifically, contrary to the hand-off note ("last action: update the router to surface
`warning`"), that step had in fact already landed:

- `apps/api/app/routers/agents.py:2309` already returns `"warning": output.get("warning")` in
  `run_tailor`'s sync-path response dict.
- `TailorRunResult` (dataclass, `tailor_agent.py`) already carries a `warning: str | None` field,
  populated from `loop_result.warning`.
- `TailoringAgent.run()` already builds a `TailoringLoop(service=self._service,
  ats_engine=self._ats_engine)` (both **real** production instances — `ResumeTailorService()`
  wired to the app's real `LLMClient()`, `ATSEngine()` deterministic scorer — never a stub/mock
  on the production path), runs it, and threads `loop_result.iterations` into the persisted
  `Resume.sections["tailoringIterations"]`, `loop_result.final_bullets` into the new version,
  and `loop_result.requires_review` into `conversionMetrics["requires_review"]`.
- `apps/api/app/routers/analytics.py` already added `interview_conversion_rate` /
  `interview_conversion_healthy` to `GET /analytics/conversion`, built on the **canonical**
  `get_application_counts()` (`COUNT(DISTINCT "jobId")`), explicitly distinguished in its own
  docstring from the pre-existing, differently-denominated `market-pulse` "Interview conversion"
  factor (left untouched, correctly out of scope — no duplication, §13.1).

So my actual job this run was **verification of a design I initially assumed was broken**, not
repair. I ran the full battery below before touching any code, found 12/13 W-C tests green and
zero regressions, root-caused the 13th failure to a pre-existing, unrelated schema invariant (not
this feature), and concluded **no source change was warranted or made**. This report documents
that verification chain in full so the finding is falsifiable, not asserted.

## 2. Design as-built (read from the code, not re-derived)

`apps/api/app/services/tailoring_loop.py`:

- `TailoringLoop(service, ats_engine, max_iterations=5, target_score=85.0).run(resume_text,
  job_description, *, originals=None, evidence_extra="")` → `TailoringLoopResult`.
- Each iteration: `service.tailor(...)` → build the like-for-like scoring corpus (résumé context
  stripped of bullet lines + the candidate bullets, mirroring `_compute_conversion_metrics` so the
  loop's own convergence decisions match what the UI's before/after banner shows) → `ats_engine
  .score(...)` → record `{iteration, score, bullets, changes, gapKeywords, rejected}` → track the
  best-scoring iteration seen so far (never a later, worse one) → stop at `score >= 85` or at
  `max_iterations`.
- Retry directive (`_build_directive`): **never** re-embeds raw JD prose (documented rationale:
  JD prose contains contraction fragments like "re"/"ll" from "we're"/"we'll" and generic words
  like "about" not covered by `ats_engine._STOPWORDS` — re-emitting it would reintroduce the exact
  tokenization noise the module exists to strip). Instead it names the numeric score gap and the
  **clean** `gap_keywords` explicitly, with an explicit anti-fabrication instruction in the
  directive text itself ("NEVER invent or fabricate a skill... an unsupported keyword must stay
  out").
- `clean_gap_keywords()`: drops bare ≤2-char tokens, a fixed contraction-fragment set
  (`re/ll/ve/d/m/s/t`), a generic-noise set (`use/uses/used/using/about`), `ats_engine._STOPWORDS`
  members, and duplicates — while preserving first-seen order of real keywords.
- The anti-fabrication guard is **never bypassed or weakened**: the loop calls the real
  `ResumeTailorService.tailor()` unmodified on every iteration; that service's existing
  `unsupported_tokens()`/entailment checks reject fabricated content exactly as before, on every
  retry, no matter what the directive asks for.

## 3. Discovered iteration cap — `[VERIFIED]`

```
$ grep -n "AETHER_LLM_BUDGET_SECONDS\|get_budget_seconds" apps/api/app/services/llm_client.py
192:    deadline = time.monotonic() + (seconds if seconds is not None else get_budget_seconds())
213:def get_budget_seconds() -> float:
227:        return float(os.environ.get("AETHER_LLM_BUDGET_SECONDS", "180"))
237:    (``AETHER_LLM_BUDGET_SECONDS``, 65s in production) so the tailor GENERATION
```

`get_budget_seconds()` bounds a single `LLMClient` instance's total wall-clock life (armed once,
shared across every call made on that instance) — it is a **per-client** budget, not a
**per-loop-iteration** cap. `TailoringLoop` is handed one `ResumeTailorService` (and therefore one
`LLMClient`) and reuses it for every iteration, so that existing budget already bounds the loop's
total live-call wall-clock time for free. No existing constant governs a *multi-pass* iteration
count anywhere in the codebase (confirmed by grep across `app/` for any other "max iteration"-style
constant touching tailoring — none found). **`max_iterations=5` is the new ceiling this module
adds**, chosen as the value the hard rules mandate as the default, with the existing per-client
budget providing the wall-clock backstop underneath it. Documented verbatim in the module's own
docstring (`tailoring_loop.py:43-51`).

## 4. Migration — none added, none needed — `[VERIFIED]`

`Resume.sections` is stored as a single JSON(B) blob (`apps/api/app/repositories/resume.py:43-55`,
inserted via `json.dumps(sections)`) — it already accepts arbitrary keys with no schema change.
`tailoringIterations` is simply a new key inside that existing JSON payload
(`tailor_agent.py`: `{"bullets": ..., "raw_text": ..., "tailoringIterations":
loop_result.iterations}`). No `ALTER TABLE`, no new column, no backfill required — the additive-
schema hard rule is satisfied by construction because the column was already schema-flexible.
`migration_added: false`.

## 5. Test run — the 3 W-C files — `[VERIFIED]`

Command (per the mandated invocation, run from repo root, flock-wrapped, one call):

```
flock /tmp/aether-pytest.lock -c "scripts/run-tests.sh tests/test_wc_tailoring_loop.py tests/test_wc_tailoring_persistence.py tests/test_wc_interview_conversion_rate.py -v"
```

Verbatim result:

```
[run-tests.sh] DATABASE_URL(_TEST) pinned to schema=aether_test — safe to proceed.
============================= test session starts ==============================
collected 13 items

tests/test_wc_tailoring_loop.py::test_loop_uses_discovered_default_of_five_and_stops_once_target_reached PASSED [  7%]
tests/test_wc_tailoring_loop.py::test_clean_gap_keywords_strips_tokenization_noise PASSED [ 15%]
tests/test_wc_tailoring_loop.py::test_loop_embeds_clean_gap_keywords_directive_into_next_iteration PASSED [ 23%]
tests/test_wc_tailoring_loop.py::test_loop_exits_immediately_once_target_score_is_met PASSED [ 30%]
tests/test_wc_tailoring_loop.py::test_loop_stops_at_max_iterations_when_score_never_reaches_target PASSED [ 38%]
tests/test_wc_tailoring_loop.py::test_loop_surfaces_honest_warning_with_best_achieved_score_when_capped_out PASSED [ 46%]
tests/test_wc_tailoring_loop.py::test_loop_never_lets_a_fabricated_keyword_close_the_gap PASSED [ 53%]
tests/test_wc_tailoring_persistence.py::TestTailoringLoopPersistence::test_tailored_resume_persists_per_iteration_history PASSED [ 61%]
tests/test_wc_tailoring_persistence.py::TestTailoringLoopPersistence::test_tailor_run_never_claims_success_below_the_85_target PASSED [ 69%]
tests/test_wc_interview_conversion_rate.py::TestInterviewConversionRate::test_interview_conversion_rate_is_a_real_computation_not_a_placeholder PASSED [ 76%]
tests/test_wc_interview_conversion_rate.py::TestInterviewConversionRate::test_interview_conversion_rate_denominator_is_distinct_submitted_jobs FAILED [ 84%]
tests/test_wc_interview_conversion_rate.py::TestInterviewConversionRate::test_interview_conversion_rate_zero_when_no_interviews_yet PASSED [ 92%]
tests/test_wc_interview_conversion_rate.py::TestInterviewConversionRate::test_interview_conversion_rate_green_threshold_is_one_in_five PASSED [100%]

=================================== FAILURES ===================================
_ TestInterviewConversionRate.test_interview_conversion_rate_denominator_is_distinct_submitted_jobs _
...
>       _seed_application_rows(
            user_id,
            [
                ["submitted", "submitted", "interview"],  # 1 job, 3 rows, 1 interview
                ...
            ],
        )
tests/test_wc_interview_conversion_rate.py:112:
...
psycopg2.errors.UniqueViolation: duplicate key value violates unique constraint "Application_user_job_active_key"
DETAIL:  Key ("userId", "jobId")=(c32c986d7a9eff5e398660c23, caf844190e4ebec4e20fbc21e) already exists.
app/db.py:126: UniqueViolation
=========================== short test summary info ============================
FAILED tests/test_wc_interview_conversion_rate.py::TestInterviewConversionRate::test_interview_conversion_rate_denominator_is_distinct_submitted_jobs
================== 1 failed, 12 passed, 6 warnings in 20.19s ===================
```

**Result: 12 passed, 1 failed.** I made **no source-code changes** between this run and the start
of the session — this is both the "before" and "after" state, and re-running would reproduce it
identically (confirmed conceptually: no writes were made anywhere in `apps/api/app`).

## 6. Root-cause of the 1 failing test — `[VERIFIED]`, not fixed, not adjusted

`test_interview_conversion_rate_denominator_is_distinct_submitted_jobs`'s own
`_seed_application_rows` helper inserts, for its first "job," THREE raw `Application` rows on ONE
`jobId`, with statuses `["submitted", "submitted", "interview"]` — i.e. **two rows simultaneously
carrying an "active" status** (`submitted` and `interview` both belong to
`APPLICATION_ACTIVE_STATUSES = ("submitted", "screening", "interview", "offer")`,
`apps/api/app/db.py:547`).

This collides with a **pre-existing, legitimate, unrelated** invariant: a partial unique index
`Application_user_job_active_key` on `("userId","jobId") WHERE status = ANY(active statuses)`,
added by a different workstream (RT-004 / ML-W-17, `ensure_application_unique_active_index()`,
`apps/api/app/db.py:545-600`) specifically to close a race condition that could otherwise mint two
simultaneously-active `Application` rows for one job. Confirmed the index is live in the shared
`aether_test` schema right now:

```
$ psql "$BASE" -c "SET search_path TO aether_test; SELECT indexname, indexdef FROM pg_indexes WHERE tablename='Application';"
 Application_user_job_active_key | CREATE UNIQUE INDEX "Application_user_job_active_key" ON aether_test."Application"
   USING btree ("userId", "jobId")
   WHERE (status = ANY (ARRAY['submitted'::"ApplicationStatus", 'screening'::"ApplicationStatus",
                               'interview'::"ApplicationStatus", 'offer'::"ApplicationStatus"]))
```

This index is created lazily the first time any test hits `POST/PATCH /applications*`
(`apps/api/app/routers/applications.py:339,520`) and — per the shared-test-DB nature of this
repo — **persists across the whole session regardless of which test files are run together**
(indexes survive `TRUNCATE`). It is not something this run created, and it is not scoped to my W-C
files; it would block this exact seed pattern in any test run, in isolation or otherwise.

The test's own docstring frames the 3-row job as "re-tailored/re-drafted cover-letter versions of
the one submitted application" — but in the real system, re-drafting doesn't add a second row with
an *active* status; draft/refine cycles are `'draft'`-status rows (explicitly the *many-allowed*
case per `APPLICATION_ACTIVE_STATUSES`'s own comment), and a status transition (submitted →
interview) is an **UPDATE of the existing active row**, not a second INSERT. The seed data
describes a state the real application lifecycle cannot produce.

**This is a test-authoring defect, not a gap in the `interview_conversion_rate` implementation.**
I verified the implementation's actual DISTINCT-job semantics independently, without touching the
test file, via an ad hoc rolled-back transaction against the same test DB (evidence, not committed
as a test — nothing added to the pytest suite):

```
$ psql / python3 ad hoc (BEGIN ... ROLLBACK, no data persisted):
  seeded ONE job with 2 Application rows: status='draft' + status='interview'
  (passes the real unique-active-index invariant, unlike the failing test's seed)
  ran the exact SQL from get_application_counts():
    SELECT COUNT(DISTINCT "jobId") AS total,
           COUNT(DISTINCT "jobId") FILTER (WHERE status <> 'draft') AS submitted,
           COUNT(DISTINCT "jobId") FILTER (WHERE status IN ('interview','offer')) AS interviewed
    FROM "Application" WHERE "userId" = %s AND "jobId" = ANY(%s)
  result: (1, 1, 1)   -- one job, 2 rows -> counted ONCE in every column, not twice
  rolled back -- no data persisted
```

This confirms `COUNT(DISTINCT "jobId")` genuinely collapses multiple `Application` rows for one
job to one count (the exact property the test intends to pin), for every seed shape the real
schema actually permits. Combined with the 3 *other* interview-conversion tests passing (basic
ratio, zero-interviews floor, and the 1:5 healthy-threshold boundary — the latter two exercising
the same `get_application_counts` code path), I'm confident the `interview_conversion_rate`
feature itself is correctly implemented; only this one test's illegal seed data is broken.

Per the hard rule ("never adjust a test... report honestly if red"), **I left the test file
untouched** and did not touch the `Application_user_job_active_key` index (a different
workstream's deliberate anti-race-condition fix, explicitly out of my scope and off the "stay out"
adjacent surface). Filing this as a finding for test-author/reviewer:

- **Finding WC-INTERVIEW-SEED-001** (OPEN, for test-author/reviewer — not fixed by this run):
  `test_interview_conversion_rate_denominator_is_distinct_submitted_jobs`'s seed data violates
  `Application_user_job_active_key`. Two interpretations, both requiring only a TEST-FILE change
  (never touched here): (a) change the multi-row job's statuses to one non-active (`'draft'`) +
  one active status, e.g. `["draft", "interview"]`, which still proves the DISTINCT-job property
  without an illegal double-active state; or (b) if the intent was truly "two temporally-separate
  submissions of the same job," seed a realistic lifecycle (first row terminal — `'rejected'`/
  `'withdrawn'` — before the second row is inserted), matching how `APPLICATION_ACTIVE_STATUSES`'s
  own comment says re-application is legitimately modeled.

## 7. Regression suite — `[VERIFIED]`

```
flock /tmp/aether-pytest.lock -c "scripts/run-tests.sh tests/test_gap_p5_tailoring.py tests/test_gap_p6_tailoring_ats.py tests/test_tailoring_agent.py -v"
...
23 passed, 6 warnings in 39.21s
```

Zero regressions across the pre-existing tailoring test surface (fabrication rejection, evidence
grounding, story-bank wiring, format-hash/child-version integrity, ATS-lift assertions).

Ruff (`ruff check`) on all 4 touched files: **All checks passed!**
`python3 -m ast.parse` on all 4 touched files: **OK** (no syntax errors).

## 8. Anti-fabrication guard — explicitly re-verified

`test_loop_never_lets_a_fabricated_keyword_close_the_gap` (passing) wires the **real**
`ResumeTailorService` + real `ATSEngine` (no stubs) against an LLM double that repeatedly tries to
inject "Kubernetes" — a skill the seeded résumé's evidence never proves — across every one of 3
loop iterations. Assertion: zero fabricated/unsupported tokens leak into `final_bullets`,
"kubernetes" never appears in the output, and `result.success is False` (the loop never reaches 85
via fabrication — it honestly reports failure instead). This is the sacred behavior the brief
called out; it is intact and covered by a real, currently-green test.

## 9. Residual risks / handoff items

1. **Frontend does not yet consume `warning`/`requires_review` from the tailor-run response.**
   `apps/web/src/lib/api/resumes.ts`'s `ConversionMetrics`/`TailorRunResult` TypeScript interfaces
   have no `requires_review`/`warning` fields, and `apps/web/src/app/dashboard/resume/page.tsx`'s
   `runTailor()` handler only branches on `noChangesApplied` (the guard-rejected-everything case) —
   a real sub-85 result with genuine changes currently surfaces no inline warning to the user, even
   though the backend now returns one on every such response. No failing frontend test was provided
   for this in my dispatch (the 13 RED tests are all backend `pytest`), and my mandate is
   backend-scoped (`ai-loop-engineer`) with an explicit "no scope creep" hard rule and "never
   implement without a failing test gate" — so I did **not** touch frontend code. **UNSURE**
   whether this is intended for a later UI-focused wave or was meant to be closed here; filing both
   interpretations per the "never ask the user" rule. Evidence: `apps/web/src/lib/api/resumes.ts:49-70`,
   `apps/web/src/app/dashboard/resume/page.tsx:115-135`.
2. **WC-INTERVIEW-SEED-001** (§6 above) — one W-C test file has a seed-data bug colliding with an
   unrelated, legitimate schema invariant from a different workstream. Needs a test-author/reviewer
   fix to the test file itself; the underlying `interview_conversion_rate` feature is verified
   correct independently (§6 ad hoc verification).
3. Market-pulse's own, separately-computed "Interview conversion" probability factor
   (`apps/api/app/routers/analytics.py`, `interview_rate` in the probability-score block) still uses
   a raw non-DISTINCT `Application` row count, diverging from the new canonical
   `interview_conversion_rate` on `/analytics/conversion`. This is a **pre-existing, already-known,
   explicitly out-of-scope divergence** (documented in the prior agent's own code comment and in
   `uat/reports/evidence/gold-master-v2/screens/analytics-screen-test.md` finding ML-ANALYTICS-004)
   — not introduced or worsened by this work, and my brief explicitly scoped only the new named
   metric, not a market-pulse rewrite. Left untouched.
4. Iteration cost: a genuinely stuck tailoring run (never converges) now makes up to 5 real
   sequential LLM calls per `/agents/tailor/run` instead of 1, bounded underneath by the existing
   per-`LLMClient` wall-clock budget (§3). This is the intended design per the brief but is worth
   flagging as a real, larger latency/cost envelope for the worst case (score plateaus below 85
   every iteration) — not a defect, a known trade-off already documented in the module's own
   docstring.

## 10. Return-schema summary

```json
{
  "artifact": "uat/reports/evidence/gold-master-v2/waves/WC-fix-report.md",
  "commits": [],
  "files_changed": [],
  "prior_work_assessment": "substantively complete and correct — not partial; the hand-off note's claimed unfinished step (router warning surfacing) was in fact already done",
  "max_iterations_cap": 5,
  "tests": {"passed": 12, "failed": 1},
  "all_green": false,
  "migration_added": false,
  "regressions": [],
  "anti_fabrication_preserved": true,
  "residual_risks": [
    "frontend does not consume warning/requires_review from tailor-run response (no failing FE test provided; flagged, not implemented)",
    "WC-INTERVIEW-SEED-001: one interview-conversion test's seed data violates the pre-existing Application_user_job_active_key unique index (test-authoring defect, not an implementation gap; feature independently verified correct via ad hoc rolled-back-transaction query)",
    "market-pulse's separate legacy interview_rate factor still non-canonical (pre-existing, explicitly out of scope, unchanged by this run)"
  ]
}
```
