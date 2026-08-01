# GMV4-sse-001 + GMV4-tailor-001 — Test-Author Report (§22 STEP 2)

Role: test-author (failing-tests-only, never implements). Repo:
/home/ubuntu/github_repos/aether-job-career-agent. Timestamp: 2026-07-31T18:08:00Z.

## Files

- `apps/api/tests/test_agent_run_sse.py` — 6 tests, GMV4-sse-001.
- `apps/api/tests/test_tailor_response_contract.py` — 4 DB-free tests, GMV4-tailor-001.
- `apps/api/tests/test_tailor_persistence_db.py` — 1 DB-isolated test, GMV4-tailor-001 §6.1(c).

## Run command (both, per task brief — no flock, no waiting on the concurrent full suite)

```
timeout 120 scripts/run-tests.sh tests/test_agent_run_sse.py -v --tb=short --no-header
timeout 120 scripts/run-tests.sh tests/test_tailor_response_contract.py -v --tb=short --no-header
```

## Results — all 10 committed tests FAIL for the right reason

[VERIFIED-WITH-FRESH-EVIDENCE `GMV4-sse-001-fail-before-20260731T180553Z.txt` @2026-07-31T18:05:53Z]
6/6 SSE tests FAILED, all on `assert resp.status_code == 200` (actual: 404
`{"detail":"Not Found"}`) or, for `test_sse_run_not_found_returns_404`, on the
body-content assertion distinguishing the app's own "Agent run not found"
from FastAPI's generic unmatched-route body — proving the SSE route is
entirely unregistered, not merely misbehaving.

[VERIFIED-WITH-FRESH-EVIDENCE `GMV4-tailor-001-fail-before-20260731T180602Z.txt` @2026-07-31T18:06:02Z]
4/4 response-contract tests FAILED, all on `assert "iterations" in body` /
`assert "gapKeywords" in body` — `TailorRunResult`'s real keys today:
`['approval_id', 'approval_status', 'changes', 'conversionMetrics',
'rejected', 'resume_id', 'warning']`.

[VERIFIED-WITH-FRESH-EVIDENCE `GMV4-tailor-001-persistence-db-contention-20260731T180200Z.txt`]
The 5th (DB-dependent) test is BLOCKED, not evidenced clean: two live
attempts both hit real infra contention (concurrent full-suite pytest
process, pid 3137656, actively truncating the shared `aether_test` schema)
— `ForeignKeyViolation` on attempt 1, a just-created row vanishing on
attempt 2. Per the brief's "fail same task twice -> STOP and escalate" rule,
no third live attempt was made. `--collect-only` confirms the file is
syntactically sound. **Escalation: re-run
`flock /tmp/aether-pytest.lock scripts/run-tests.sh tests/test_tailor_persistence_db.py -v --tb=short`
once the concurrent full-suite process has exited.**

## Plumbing vs. computation — explicit finding (required by task brief)

`TailoringLoop.run()` (`apps/api/app/services/tailoring_loop.py:152-222`)
ALREADY computes everything DEFECT-2 asks to expose: `iterations` (index +
score + gapKeywords + changes + rejected per attempt,
`tailoring_loop.py:179-186`) and an honest, never-clamped `warning`
(`tailoring_loop.py:202-212`). `TailoringAgent.run()`
(`apps/api/app/agents/tailor_agent.py:420-525`) receives
`loop_result.iterations` and WRITES it to the DB (`sections["tailoringIterations"]`,
line 463) but never copies it onto the `TailorRunResult` dataclass it returns
(fields listed at lines 281-295: no `iterations`, no `gapKeywords`). **This is
a PLUMBING job, not a computation job** — the data exists in memory at the
exact point the dataclass is constructed (`tailor_agent.py:517-525`); it is
simply not assigned to a field.

Two claims in the source finding do **not** hold at the backend layer once
read (documented in the test file's module docstring, not silently
dropped, so the implementer does not duplicate work):
- `conversionMetrics.baselineATSScore`/`.tailoredATSScore` already exist in
  the response (`tailor_agent.py:94-119`, wired at `472-479`) and are already
  read by `apps/web/src/app/dashboard/resume/page.tsx:365-366` (the
  "Before: X% -> After: Y%" banner). The screen-tester's "rendered nowhere"
  observation is real but is a **different page** —
  `apps/web/src/app/dashboard/jobs/page.tsx` never reads `conversionMetrics`
  at all (confirmed via that page's own test docstring,
  `__tests__/tailor-score-refresh.test.tsx:6-8`) — not a missing backend
  field. Both DEFECT-2 tests that touch this were redesigned to fail on the
  genuine remaining gap (traceability of the after-score to a real
  optimizer iteration via `iterations`) rather than on presence of
  `conversionMetrics` itself, which would have trivially passed today and
  been a defective test.
- The anti-dishonesty warning text (§5.3.1 point 5) is already honest and
  never clamps (`tailoring_loop.py:202-212`, `tailor_agent.py:524`). The
  anti-dishonesty test (`test_tailor_sub_target_score_is_reported_honestly`)
  was strengthened past the (currently-passing) prose-honesty check into a
  **verifiability** requirement — the warning's numeric claim must be
  cross-checkable against the real per-iteration trail — which genuinely
  fails today for the same root cause (`iterations` missing).

Additional wrinkle discovered while writing these tests, noted in the test
file for the implementer but out of GMV4-tailor-001's direct scope:
`_compute_conversion_metrics` builds its OWN fresh `ATSEngine()`
(`tailor_agent.py:94`) instead of reusing the loop's `ats_engine`, and scores
against a DIFFERENT job-description string than the loop used internally
(`job.get("description") or ""` at line 474 vs. the loop's
`f"{title} at {company}. {description}"` at line 399) — so
`conversionMetrics.tailoredATSScore` is a separately, independently
recomputed number, not simply a copy of the loop's own winning-iteration
score.

## Prohibited-pattern self-check

- No `assert True`, no tautologies, no mocking heavy enough to pass
  regardless of implementation (stubs replace only the DB/LLM boundary; all
  assertions target real production code paths: `TailoringAgent.run`,
  `TailorRunResult`, `create_app`/routing, `get_current_user` override).
- No skip/xfail anywhere in either committed file.
- No production file modified by this agent: `git status --porcelain
  apps/api/app/` at the time of writing showed only `main.py` and
  `services/ats_engine.py` modified — both pre-existing changes from other
  concurrent agents in this swarm, confirmed identical before and after this
  session's work (never touched by this agent).
- 2 tests that would have trivially PASSED today
  (`test_tailor_response_includes_ats_score_before_and_after` naive version,
  `test_tailor_sub_target_score_is_reported_honestly` naive version) were
  caught and rewritten to fail for a genuine reason rather than committed as
  defective/tautological tests; a 3rd (`test_scripted_service_sanity_...`,
  a harness self-check, not one of the 5 assigned tests) was removed
  entirely rather than parked as a passing test.

## Process note (not a defect) — concurrent-commit attribution

This session's two tailor-test files were staged via `git add`, but a
`git commit` race with a concurrently-running "janitor" agent's own commit
resulted in both files landing inside that agent's commit (`86a1fef
"fix(gm-v4): execute approved deletions; disclose VIOL-006 orchestrator
secret echo"`) rather than a dedicated `test(GMV4-tailor-001): ...` commit.
Content is correct and verifiable (`git show 86a1fef --stat` lists both
files with the expected line counts); no history rewrite was attempted
(shared, actively-changing repo — rebase/amend would risk other agents'
concurrent work). The SSE commit (`f77631e
"test(GMV4-sse-001): failing test for missing agent-run SSE stream
endpoint"`) is clean and contains only this session's file.
