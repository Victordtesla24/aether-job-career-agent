# NF-final-PII-002 — pipeline-branch fix (review gap)

**Timestamp:** 2026-07-20 00:28 UTC (this session)
**Branch:** `fix/nf-pii-002-async-refuse`
**Fix commit:** `3409976c51419184a99699800d0fc3428a8c8412`
**Prior (incomplete) commit:** `bf8cbc375e39b995f210aff8b117f308a7cbcbf3`
**Merge base with main:** `d313d23b6e7177b94f11c1419ffd21b0ac0a0e87`
**Worktree used:** `/tmp/claude-2000/-home-ubuntu/c60dc115-9302-4f64-8221-563feb393b13/scratchpad/fixer-nfpii002` (created via `git worktree add --force ... fix/nf-pii-002-async-refuse`, since the branch was already checked out read-only by the reviewer's worktree `.claude/worktrees/agent-ae3ad484e5fc979c8`; verified `git log -1` showed `bf8cbc3` before any edit; worktree removed with `git worktree remove --force` after commit — branch retains the commit) [VERIFIED-WITH-FRESH-EVIDENCE]

## Source of the gap

`uat/reports/evidence/manual-verification/reviews/consolidated-residuals-review.json`,
`fix/nf-pii-002-async-refuse` entry, verdict `FAIL`. The reviewer's own
adversarial pytest (run against the branch worktree, this-session-prior)
demonstrated: seeding a `pipeline`-agentKey `BackgroundJob`, monkeypatching
`app.workers.tasks._run_pipeline_body` to raise `MissingResumeError`, then
calling `run_agent_job` — result `status == 'failed'` and
`error == 'MissingResumeError: Add your resume before generating a cover
letter.'` — the identical class-prefix leak NF-final-PII-002 describes, still
present for the pipeline (`/agents/pipeline/run`) async path because bf8cbc3
only patched the single-agent branch of `run_agent_job`
(`apps/api/app/workers/tasks.py`), not the pipeline branch's
`except Exception` at line 174 (pre-fix numbering).

## Fail-before (this session)

Test added to `apps/api/tests/test_gap_p7_async_001.py`:
`test_pipeline_missing_resume_completes_not_failed`. Mirrors
`test_pipeline_partial_refund_on_midrun_crash`'s monkeypatch-of-
`_run_pipeline_body` seam (a metered step reserves one run on the job via
`UsageQuotaRepository().reserve()` + `BackgroundJobRepository().increment_reserved()`,
as a real pipeline step does under `_pipeline_job_ctx`) but raises
`MissingResumeError("Add your resume before generating a cover letter.")`
instead of a crash, then asserts the honest-completion contract.

Command:
```
DATABASE_URL="$DATABASE_URL_TEST" AETHER_CREDENTIAL_KEY="X5-HScT0p...(redacted)" \
AETHER_ASYNC_GENERATION=false flock /tmp/aether-pytest.lock python3 -m pytest \
  -q -p no:xdist -o addopts="" tests/test_gap_p7_async_001.py
```
(DATABASE_URL_TEST resolved via `grep -E '^DATABASE_URL_TEST=' .env` only —
never sourced the full `.env`; verified `schema=aether_test` before running.)

Result on `bf8cbc3` (pre-fix, code unmodified from the branch as reviewed):
```
FAILED tests/test_gap_p7_async_001.py::test_pipeline_missing_resume_completes_not_failed
AssertionError: assert 'failed' == 'completed'
  - completed
  + failed
Captured log call: ERROR aether.worker:tasks.py:179 pipeline job ... failed: MissingResumeError: Add your resume before generating a cover letter.
1 failed, 15 passed, 38 warnings in 52.96s
```
This reproduces the exact reviewer-observed symptom (raw class-prefixed error,
status `failed`) with fresh evidence from this session. [VERIFIED-WITH-FRESH-EVIDENCE]

## Fix implemented

`apps/api/app/workers/tasks.py`, pipeline branch of `run_agent_job` (inside
`if job["agentKey"] == "pipeline":`): added

```python
except MissingResumeError as exc:
    _pipeline_job_ctx.reset(token)
    honest_message = str(exc).strip() or "Add your resume before generating this."
    honest_result = {
        "resume_id": None,
        "missingResume": True,
        "message": honest_message,
    }
    if repo.mark_completed(job_id, honest_result):
        repo.refund_pipeline_outstanding(job_id)
    logger.info(
        "pipeline job %s refused (MissingResumeError): no resume on "
        "file, refunded", job_id
    )
    return
```

placed between the existing `except _TransientError:` and the generic
`except Exception as exc:` (unchanged, still catches every other exception
class and still calls `mark_failed` + `refund_pipeline_outstanding` +
`_honest_message`). Mirrors the single-agent handler's message construction
(`str(exc).strip()`, same fallback text, no class-name prefix) but uses
`refund_pipeline_outstanding` (this job's own outstanding
`quotaReservedCount − quotaRefundedCount`, not a user-wide delta) instead of
`refund_single_reservation`, since pipeline jobs track per-step reservations —
per the reviewer's `required_change_before_resubmit` instruction.

Diff stat: `apps/api/app/workers/tasks.py` +25, `apps/api/tests/test_gap_p7_async_001.py`
+59. No other files touched. No refactor of unrelated code.

## Pass-after (this session)

Same command, same env, run against the fixed code:
```
16 passed, 38 warnings in 53.94s
```
All 16 tests in `test_gap_p7_async_001.py` pass, including:
- `test_pipeline_missing_resume_completes_not_failed` (new — was the sole
  failure pre-fix)
- `test_missing_resume_completes_not_failed` (single-agent, bf8cbc3's own
  test — confirmed still green, not weakened)
- `test_pipeline_partial_refund_on_midrun_crash` (confirms the generic
  `except Exception` pipeline-crash path is unchanged/still correct)
- `test_noop_tailor_completes_not_failed` and all enqueue/status/quota tests

[VERIFIED-WITH-FRESH-EVIDENCE, this session]

## Prohibited-pattern scan

`git diff | grep -iE "eslint-disable|@ts-ignore|': any'|as any|Math\.random\(\)|TODO|FIXME|pytest\.mark\.skip|pytest\.mark\.xfail|no-verify"`
→ clean (no matches). No `--no-verify` used on commit.

## Commit

```
3409976c51419184a99699800d0fc3428a8c8412
fix(NF-final-PII-002): honest async MissingResumeError surfacing for pipeline jobs (review gap)
```
On branch `fix/nf-pii-002-async-refuse`. Not merged, not pushed, main untouched.

## Scope note

This fixer does not approve its own work. A separate reviewer must
re-adjudicate this commit against
`required_change_before_resubmit` in `consolidated-residuals-review.json`
before the branch is considered closeable.
