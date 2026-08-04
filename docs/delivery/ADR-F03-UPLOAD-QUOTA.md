# ADR-F03 — Résumé upload must not silently spend a metered agent run

- **Status:** Implemented (awaiting independent review; not deployed by this change)
- **Date:** 2026-08-04
- **Finding:** `docs/delivery/PROD-UAT-2026-08-03.md` F-03 (MAJOR), reproduced live
  against https://5cb5f0620.abacusai.cloud
- **Scope:** `POST /api/resumes/upload` and the Settings → Resume Management panel

---

## 1. The defect, as reported

Upload at 01:25:55Z returned 201. `GET /agents/runs` immediately afterwards showed an
**unrequested** `storyExtractor` run with `costUsd 0.0010` and
`billingAudit.quotaPath "metered_api"`; `GET /billing/subscription` then reported
`runsUsed: 2` from exactly **one** deliberate user action. Nothing in the UI said, before
the upload, that a file upload would cost an agent run. The only mention of extraction was
the post-upload notice — `"…; story extraction ran."` — which came after the fact, never
said it was billable, and was printed unconditionally (including when the server had
reported `storyExtraction.error`, i.e. when it had **not** run).

On the Free plan (5 runs/month) that is 20% of the month's allowance per upload. A user
uploading two résumé variants to compare burns 40% before a single tailoring run.

## 2. The facts established first (this decided the remedy)

**Story extraction is genuinely metered LLM work — the metering is not incidental.**

| Question | Answer | Evidence |
|---|---|---|
| Does the auto-dispatch reach a real LLM call? | Yes | `apps/api/app/agents/story_extractor.py:253` — `self._llm.complete_json("story_extractor", …, model=get_model("STRUCTURED"))`, executed once per batch of `_BULLETS_PER_CALL = 4` résumé bullets, inside a `shared_budget` window |
| Is the backend registered as an LLM backend? | Yes | `agents.py:1360` — `_LLM_TIER_BY_BACKEND["storyExtractor"] = "STRUCTURED"` |
| Is it in the deterministic (exempt) set? | No | `agents.py:3130` `_DETERMINISTIC_BACKENDS` = scout / fitScorer / matcher / supervisor / compliance / salaryIntelligence / marketTrends / learningFeedback / notification / submission — these are exempt **because they call no model at all** |
| Is it in the "optional LLM" (per-call exempt) set? | No | `agents.py:1540` `_OPTIONAL_LLM_BY_BACKEND` = companyResearch / interviewPrep / emailAgent / recruiterOutreach / reference / sentimentAnalysis / scheduling. Its own docstring records the deliberate scoping: *"tailor / coverLetter / storyExtractor keep their existing per-backend metering exactly as-is"* |
| Where is quota reserved? | `agents.py:912-921` — `_call_is_metered(agent_name, params)` → `UsageQuotaRepository().reserve(user_id)` **before** the run row and before any LLM call; spend cap checked immediately after |
| Was the dispatch conditional on anything? | No | `resumes.py:115` (pre-fix) — `_dispatch(current_user["id"], "storyExtractor", {})`, unconditional |

So the quota consumption was *correct accounting of real spend*. What was wrong was that
the **user never asked for the spend and was never told about it**.

## 3. Options considered

### (a) Make it unmetered — REJECTED

The existing exemption seam exempts exactly one thing: a call that **reaches no model**.
`_DETERMINISTIC_BACKENDS` covers agents that never call an LLM;
`_OPTIONAL_LLM_BY_BACKEND` covers per-call paths that provably reach no model (and is
backed by a post-execution `llm_called=False` refund backstop). `storyExtractor` fits
neither: every run with résumé bullets makes real STRUCTURED-tier calls.

Following that seam anyway would create an **unmetered, unbounded LLM-spend path**: upload
N files, get N free LLM runs, with no reserve, no spend-cap check (the cap is only consulted
on the metered branch, `agents.py:913-922`) and no ceiling. That is the opposite of honest
metering, and it would have to be reconciled with the existing regression pin
`test_wave4a_company_research_hardening.py::test_metering_predicate_cannot_disagree_with_the_dispatched_call`,
which asserts `_call_is_metered("storyExtractor", {}) is True`.

### (b) Make it explicit and opt-in — CHOSEN

The user decides, and is told the price before they commit. Nothing about the metering rail
changes: when extraction *is* requested it runs through the identical
`_dispatch` → `_record_run` path, with the same atomic reserve, the same spend cap, the same
`AgentRun` audit row and the same GAP-P6-RESFIX entitlement propagation.

Decisive additional fact: **the capability is not lost by removing the auto-trigger.**
Extraction already exists as a first-class explicit action — `POST /agents/story-extractor/run`
(`agents.py:2629`), wired to the Story Bank screen's "Draft missing stories" button
(`apps/web/src/lib/api/stories.ts:53`). SC-SB-01's intent ("the Story Bank reflects the new
base resume") is still reachable in one click, now as a choice rather than a charge.

### (c) Disclose before the fact but keep it automatic — REJECTED

Still charges a user for something they did not ask for. Only justified if extraction could
not be deferred; it plainly can — the standalone endpoint and its Story Bank trigger already
exist, and the extractor is *designed* to be re-run (its `_chunks` ordering puts uncovered
bullets first precisely so consecutive runs converge).

## 4. What changed

**Backend — `apps/api/app/routers/resumes.py`**

- `POST /resumes/upload` takes `extract_stories: bool = Form(default=False)`.
- The `storyExtractor` dispatch is now inside `if extract_stories:` — everything else about
  that block (including the `except HTTPException: raise` GAP-P6-RESFIX propagation) is
  untouched.
- The response reports both halves honestly:
  `storyExtractionRequested` (what was asked for) and `storyExtraction`
  (the run result, `null` when it was not requested), so no client can render
  after-the-fact copy claiming a run that never happened.

**Frontend — `apps/web/src/components/settings/resume-upload.ts` (new) and
`apps/web/src/app/dashboard/settings/settings-client.tsx`**

- A checkbox, **default off**, rendered above the upload button:
  *"Also extract STAR stories from this résumé — runs the Story Extractor agent and uses 1
  of your monthly agent runs."*
  with the sub-line *"Uploading on its own is free and uses no agent runs. You can extract
  stories later from the Story Bank."*
- The upload sends `extract_stories` to match that choice.
- The post-upload notice is now built by `buildUploadNotice()` from the server's own
  response, with three distinct outcomes that are never conflated:
  - not requested → *"… No agent run was used. Uploading on its own is free…"*
  - requested but failed → *"… Story extraction failed: `<error>` — no stories were added.
    You can retry it from the Story Bank."*
  - requested and ran → *"… Story extraction ran and added N stories — that used 1 of your
    monthly agent runs."*

### What the user now sees, and when

| Moment | Before | After |
|---|---|---|
| Before choosing a file | nothing about extraction or cost | the checkbox (off) + the run cost, in plain words |
| Uploading with the box unticked | 1 metered run silently spent | nothing spent; response says `storyExtractionRequested: false` |
| Uploading with the box ticked | (unreachable — always on) | extraction runs, metered exactly once, as `POST /agents/story-extractor/run` is |
| After the upload | *"story extraction ran."* — always, even when it had failed | the real outcome, with the run charge stated only when a run was actually used |

### Deliberate, disclosed consequence

With extraction opted out, an upload makes no LLM call and reserves nothing, so the
agent-run entitlement gate (`_require_active_subscription`, reached only via `_record_run`)
no longer applies to it: under `AETHER_REQUIRE_PAID_SUBSCRIPTION=true` a non-subscriber's
plain upload now returns 201 instead of 402. This matches every other non-agent résumé
endpoint (`POST /resumes`, `GET /resumes`, `GET /resumes/{id}` are all ungated) — the
paywall gates *agent runs*, and a plain upload has stopped being one. Pinned by
`test_plain_upload_is_not_an_agent_run_and_so_is_not_paywalled`. The 402 still fires, exactly
as before, on the opt-in path
(`test_opt_in_upload_still_propagates_402_for_a_non_subscriber`).

## 5. Other silent metered dispatches on non-agent user actions (audit)

Sweep: every cross-module use of `app.routers.agents._dispatch` / `_record_run`, plus every
`LLMClient()` construction and `complete_json`/`complete` call site outside `app/agents/`.

| Call site | Verdict |
|---|---|
| `resumes.py:115` → `_dispatch("storyExtractor")` on `POST /resumes/upload` | **THE defect (F-03)** — fixed here |
| `cover_letters.py:946` → `_record_run("coverLetter")` on `POST /cover-letters/{id}/refine` | Not silent — refine is an explicit user request for new LLM output, and the metering was added deliberately by ADV-ENT-001 to close an *unmetered* hole. **Residual (LOW): the Cover Letter studio's refine control does not state that a refine costs a run.** Same disclosure class as F-03, far weaker case (the user is asking for generation); reported, not fixed here — out of F-03's scope. |
| `board_sweep.py:671` → `_dispatch(..., system_run=True, skip_quota=True)` | Correct by construction — system operation, explicitly quota-exempt, audit row stamped `systemRun: true` |
| `workers/tasks.py` (`_run_single_agent_body`, `_pipeline_core`) | Async execution of runs the user already requested; shares `_call_is_metered` with the sync path |
| `cover_letters.py:784` `LLMClient()` | Inside `_refine_cover_letter_body`, which is wrapped by the `_record_run` above — metered and audited |
| `services/resume_tailor.py:2098` `LLMClient()` | `ResumeTailorService`, reached only through the `tailor` agent; routers import only its deterministic helpers (`extract_bullets`, `unsupported_claim_tokens`) |
| `POST /applications/{id}/submit`, `POST /jobs/{id}/apply` | Deterministic DB operations — no agent dispatch, no LLM call |

**No other endpoint dispatches a metered agent as a side effect of a non-agent user action,
and no router reaches an LLM outside `_record_run`.**

Two *disclosure* residuals of the same family (both are explicit user actions, so neither is
a silent spend; neither is fixed here):

- Story Bank → "Import from Resume" / "Draft missing stories"
  (`apps/web/src/app/dashboard/stories/page.tsx:104`) calls
  `POST /agents/story-extractor/run` without stating that it costs a run.
- Cover Letter studio → refine (`apps/web/src/app/dashboard/cover-letters/page.tsx:214`)
  likewise.

Also observed and out of scope (pre-existing, logged as ADV-ENT-004 in
`GOLD-MASTER-V2-STATE.json`): on the opt-in path a 402 is still raised *after* the `Resume`
row is persisted, and there is no `DELETE /resumes` to undo it. The default (opt-out) path
no longer reaches that 402 at all, so the exposure is strictly reduced by this change.

Adjacent observation, **not fixed** (different defect class, would be scope creep):
`storyExtractor` has a genuine no-LLM-call path — `StoryExtractorAgent.run` returns early
with `"no achievement bullets found in the user's own resume"` when the résumé yields no
bullets (`story_extractor.py:208-215`) — yet it is metered per-backend, so that $0 run still
consumes a reserved run. This is exactly the class `_OPTIONAL_LLM_BY_BACKEND` + the
`llm_called=False` backstop exist to fix (as done for companyResearch / interviewPrep /
emailAgent / the outreach family). It now only reaches users who explicitly opted in, so
F-03's "silent" half is closed either way. Recommend a follow-up finding.

## 6. Tests

New: `apps/api/tests/test_f03_upload_silent_quota_spend.py` (8 tests) —
`apps/web/src/__tests__/settings/resume-upload-quota-disclosure.test.ts` (10 tests).
Updated to re-point at the still-dispatching path (assertions preserved verbatim, never
weakened): `apps/api/tests/test_resume_upload.py`.

Fail-before evidence, pass-after evidence and the full command lines are recorded in
`uat/reports/evidence/models-live/f03/`.
