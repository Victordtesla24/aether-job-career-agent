# §22 STEP 2 — test-author report: SSE resource caps + ADR-GMV4-003

HEAD at start: `79c4164`. Repo: `/home/ubuntu/github_repos/aether-job-career-agent`.
Rulings applied: `docs/delivery/GOLD-MASTER-V3-GOVERNANCE.md` §5d (ADR-GMV4-003) and §5e
(SSE resource limits). Both read in full before writing any test.

All pytest invocations run FOREGROUND, bounded `timeout`, under
`flock /tmp/aether-pytest.lock scripts/run-tests.sh ...`. No production file touched:
`git status --porcelain apps/api/app/` is empty (verified after all edits — see bottom).
No commit made (test-author does not commit per this dispatch).

## Files

- `apps/api/tests/test_agent_run_sse.py` — REWRITTEN test 4 (ADR-GMV4-003), fixed up test 2.
- `apps/api/tests/test_agent_run_sse_limits.py` — NEW file, 5 tests (GMV4-sse-005 BLOCKER).

Verbatim evidence:
- `GMV4-sse-006-adr003-rewrite-fail-before-20260801T003102Z.txt` (full `-v` run of
  `test_agent_run_sse.py` after the rewrite)
- `GMV4-sse-005-limits-fail-before-20260801T003102Z.txt` (full `-v` run of the new
  `test_agent_run_sse_limits.py`)

## TASK 1 — `test_agent_run_sse.py` (8 tests, was 7 — test 4 split into two)

| test | verdict | right-reason? |
|---|---|---|
| `test_sse_endpoint_exists_and_sets_event_stream_content_type` | PASS (unchanged) | n/a |
| `test_sse_response_disables_nginx_buffering` | PASS (unchanged) | n/a |
| `test_sse_stream_emits_progress_events_in_order` (test 2, fixed up) | **FAIL** | YES |
| `test_sse_stream_is_scoped_to_owner` | PASS (unchanged) | n/a |
| `test_kanban_updated_emitted_when_run_output_records_a_board_change` (NEW, positive half of old test 4) | PASS | n/a — this is the ADR's positive case; current `_kanban_payload` already computes `basis`/`changes` correctly, only the unconditional emission was wrong |
| `test_kanban_updated_withheld_when_run_touched_no_board` (NEW, negative half of old test 4) | **FAIL** | YES |
| `test_sse_stream_terminates_on_complete` | PASS (unchanged) | n/a |
| `test_sse_run_not_found_returns_404` | PASS (unchanged) | n/a |

**8 tests, 6 pass / 2 fail** (verbatim pytest summary: `2 failed, 6 passed in 4.21s`).
Both failures are the RIGHT reason: current
`app/services/agent_run_stream.py::_terminal_frames` (lines 204-213) emits
`kanban_updated` unconditionally for every `status == "completed"` run,
regardless of `_kanban_payload`'s own `basis` field. ADR-GMV4-003 requires it
withheld unless `basis == "run_output"`.

Verbatim (test 2):
```
>       assert event_names == ["snapshot", "complete"], event_names
E       AssertionError: ['snapshot', 'kanban_updated', 'complete']
E       assert ['snapshot', ...', 'complete'] == ['snapshot', 'complete']
E         At index 1 diff: 'kanban_updated' != 'complete'
```

Verbatim (new negative test):
```
>       assert not kanban_events, (...)
E       AssertionError: ADR-GMV4-003: kanban_updated must be WITHHELD when the run never
  touched the board — got [{'event': 'kanban_updated', 'data': {'channel':
  'jobs:sse-owner-1', 'runId': 'run-kanban-noboard-1', 'agentName': None,
  'basis': 'run_completed', 'changes': [], 'reason': 'agent_run_completed'}}]; ...
```
`basis: 'run_completed'` in the actual payload confirms the code KNOWS this run
never touched the board — it emits the event anyway. Exactly the ADR's forbidden shape.

## TASK 2 — `apps/api/tests/test_agent_run_sse_limits.py` (NEW, 5 tests)

Verified before writing: `apps/api/app/db.py:8-9` (25-conn ceiling),
`AgentRunRepository.get_by_id` opens an unpooled `get_connection()` call every poll,
`agent_run_stream.poll_seconds()` defaults `AETHER_SSE_POLL_SECONDS=1.0`,
`apps/web/src/lib/api/agents.ts:57` `JOB_POLL_INTERVAL_MS = 3000`, and
`grep -rn "concurrent\|semaphore\|Semaphore" apps/api/app/routers/agents.py
apps/api/app/services/agent_run_stream.py` → zero matches (no cap anywhere);
`app/rate_limit.py` is never imported by `routers/agents.py`.

Design: pins BEHAVIOUR only (HTTP status/body/timing), never a specific mechanism —
verified empirically first (throwaway probes, not committed) that a single shared
`TestClient` hit from real Python threads gives genuine concurrency (N truly-concurrent
blocking requests return together near the shared deadline, not serially), and that a
`Request`-based `get_current_user` override reading `X-Test-User-Id` lets many distinct
simulated users share one app/client — needed so the GLOBAL-cap test can bypass any
PER-USER cap.

| test | verdict | right-reason? |
|---|---|---|
| `test_concurrent_streams_are_capped_per_user` | **FAIL** | YES |
| `test_concurrent_streams_are_capped_globally` | **FAIL** | YES |
| `test_stream_rejection_is_honest_not_a_silent_hang` | **FAIL** | YES |
| `test_default_poll_interval_is_not_more_aggressive_than_the_client_poll` | **FAIL** | YES |
| `test_stream_releases_its_db_connection_on_disconnect` | **PASS** | **behaviour already exists** — see note below |

**5 tests, 4 fail / 1 pass.**

### Verbatim failures

`test_concurrent_streams_are_capped_per_user` (8 concurrent streams, same user):
```
E       AssertionError: none of 8 concurrent streams opened by the SAME user were
  rejected -- no per-user concurrent-stream cap exists yet (GMV4-sse-005, BLOCKER,
  §5e); statuses=[200, 200, 200, 200, 200, 200, 200, 200]
```

`test_concurrent_streams_are_capped_globally` (24 concurrent streams, 24 distinct users):
```
E       AssertionError: 24 concurrent streams from 24 DISTINCT users (deliberately
  bypassing any per-user cap) all succeeded -- no GLOBAL concurrent-stream cap exists
  yet (GMV4-sse-005, BLOCKER, §5e); statuses=[200, 200, ... 200] (24 total)
```

`test_stream_rejection_is_honest_not_a_silent_hang`:
```
E       AssertionError: no request was rejected among 8 oversubscribed concurrent
  streams for one user -- no connection-ceiling cap exists yet (GMV4-sse-005,
  BLOCKER); statuses=[200, 200, 200, 200, 200, 200, 200, 200]
```

`test_default_poll_interval_is_not_more_aggressive_than_the_client_poll`:
```
E       AssertionError: AETHER_SSE_POLL_SECONDS default resolved to 1.0s -- MORE
  aggressive than the real client poll of 3000ms
  (apps/web/src/lib/api/agents.ts:57); §5e requires the default be >= 3.0s.
E       assert 1.0 >= 3.0
```

### The one PASS — explicit disclosure, not assumed absence

`test_stream_releases_its_db_connection_on_disconnect` **passes today**. This is NOT a
defective/tautological test — the behaviour it pins genuinely already exists:
`app/routers/agents.py:2194` already wires `is_disconnected=request.is_disconnected`
into `iter_agent_run_events`, and the generator (`agent_run_stream.py:274-276`) checks
`is_disconnected()` at the top of every poll loop, before scheduling the next poll —
so after a client disconnects, at most ONE more in-flight poll completes and then
polling (and therefore further `get_connection()` opens, since every poll in this
codebase is its own open-use-close connection) stops. Measured: 32 `get_by_id` calls
at the moment the client context closed, still 32 one full second later (10x the
0.1s poll interval used).

I verified this is NOT a tautology with a throwaway (uncommitted) counterfactual probe:
calling `iter_agent_run_events` directly with `is_disconnected=None` (simulating a
regression where the router stops wiring the disconnect check) and continuing to pump
the generator produced 98 additional `reload_run` calls in the same window — proving
the test would genuinely catch that regression if it ever landed. §5e's actual
production risk is aggregate connection churn under many simultaneous streams
(covered by the other 4 tests), not a single stream failing to notice disconnect —
that specific, narrower property is already correct.

## Ambiguities judged, both readings recorded

1. **§5e per-user/global cap exact numbers.** The ruling states caps must exist and
   the global one must sit "below 25 with headroom" but names no specific numbers.
   Reading (a) (used): tests assert only that *some* rejection occurs under
   deliberate oversubscription (8 same-user / 24 distinct-user), plus a headroom
   assertion (`accepted <= 20` of 24 distinct-user attempts) — passes for ANY
   per-user cap well under 8 and ANY global cap ≤ 20. Reading (b) (rejected): pin an
   exact cap value (e.g. "per-user cap == 3") — rejected because the ruling never
   specifies one and a fixer choosing a different, still-reasonable number would then
   fail a correct fix.
2. **`test_stream_releases_its_db_connection_on_disconnect` — "must FAIL today" vs.
   observed PASS.** Reading (a) (used, per the brief's own explicit instruction "say
   WHICH explicitly, do not assume absence"): report the true, verified result — the
   underlying disconnect-awareness already exists and is not itself the DoS surface;
   keep the test as a real regression guard. Reading (b) (rejected): weaken/invert the
   assertion until it fails today regardless of truth — rejected as dishonest
   (prohibited: no fake-fail tests to satisfy a checklist).
3. **What counts as "the run touched no board" for ADR-GMV4-003's negative test.**
   Reading (a) (used): a completed run with a realistic non-board `output` shape
   (`{"tailoredResumeId": ..., "atsScore": ...}`, i.e. a tailoring run) — most
   representative of the real false-positive scenario the ADR reasoning describes.
   Reading (b) (considered): `output: None`/absent entirely — also valid and already
   covered by test 2 (which uses a run dict with no `output` key at all), so the two
   tests together cover both `output` shapes that should withhold the event.

## `git status --porcelain apps/api/app/` proof (production files untouched)

```
$ git status --porcelain apps/api/app/
<empty output>
```

Full `git status --porcelain` also shows only test files + evidence + pre-existing
unrelated changes (a log file this run did not touch, two frontend `.test.tsx` files
not authored in this dispatch):
```
 M apps/api/tests/test_agent_run_sse.py
 M uat/reports/evidence/gold-master-v2/runtime/monitor-errors-CORRECTED.log
?? apps/api/tests/test_agent_run_sse_limits.py
?? apps/web/src/app/dashboard/jobs/__tests__/degraded-scoring.test.tsx
?? apps/web/src/app/dashboard/resume/__tests__/degraded-scoring.test.tsx
```
(`.pytest_cache`/`__pycache__` churn omitted — not source.)

No commit made per this dispatch's scope (test-author writes tests; a separate
`fixer-hard` implements against them and a reviewer/qa closes the gate).

**Caveat on the `apps/api/app/` proof above (not this repo being an isolated
worktree):** the `git status --porcelain apps/api/app/` snapshot embedded above was
captured immediately after finishing all edits and IS accurate for that instant. A
later re-check in the same session showed `apps/api/app/db.py`,
`apps/api/app/repositories/story.py`, and `apps/api/app/services/story_paraphrase.py`
newly modified — a CONCURRENT, unrelated workstream in this shared (non-worktree)
repo, adding additive `StoryEntry` archive columns for GMV4-story-004 (visible in the
diff: `ensure_story_archive_columns`, `archivedAt`/`mergedIntoId`/`mergeSnapshot`).
Confirmed none of it touches SSE/`agent_run_stream`/`routers/agents.py`/`rate_limit.py`,
and I never opened those three files for editing this session (only read `db.py`,
never wrote to it). Re-ran both test files after noticing this (`flock
/tmp/aether-pytest.lock scripts/run-tests.sh tests/test_agent_run_sse.py
tests/test_agent_run_sse_limits.py -q`) and results were unchanged: `6 failed, 7
passed`. Flagging per the shared-`aether_test`-schema discipline in the runbook —
this is environmental noise from another concurrent agent, not a residual of this
dispatch.
