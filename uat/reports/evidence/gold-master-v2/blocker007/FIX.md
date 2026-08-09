# BLOCKER-007 — `POST /agents/fit-scorer/run` 500s on every discovery cycle

Fixer: fixer-hard. Repo `/home/ubuntu/github_repos/aether-job-career-agent`, branch `main`.
Production: https://5cb5f0620.abacusai.cloud
All measurements below are first-hand, taken by this fixer, against the production
database in a **READ ONLY** psycopg2 session (`conn.set_session(readonly=True)`).
Nothing was written to production and no DDL was issued anywhere.

---

## 1. Mechanism — confirmed first-hand

`FitScorerAgent.run` read its work list through the **board's** projection:

- `apps/api/app/agents/fit_scorer.py:74` (pre-fix) — `for job in self._repository.list_by_user(user_id):`
- `apps/api/app/repositories/job.py:380` (pre-fix line number) — the `cur.execute` inside
  `JobRepository.list_by_user`, which emits
  `SELECT {_JOB_READ_COLUMNS}, {_TAILORED_RESUME_SUBQUERY}, {_TAILORED_RESUME_STATUS_SUBQUERY},
  {_autopilot_suppressed_until_subquery()} FROM "Job" j WHERE "userId" = %s ORDER BY … DESC NULLS LAST`
  — 21 columns plus **three correlated subqueries evaluated per row**, and **no `LIMIT`**.
  `_autopilot_suppressed_until_subquery()` (`job.py:133-190`) alone contains three further
  correlated scans of `"AgentRun"` plus a `NOT EXISTS` against `"Application"`.

**What the fit-scorer actually needs.** Reading `fit_scorer.py:66-118` end to end, `run()` touches
exactly six values per row:

(line numbers are post-fix, `apps/api/app/agents/fit_scorer.py`)

| value | used at | purpose |
|---|---|---|
| `job["id"]` | `:108` (`clear_fit_score`), `:117`/`:125` (`advance_status`), `:122` (`update_fit_score`) | write key |
| `job["fitScore"]`, `job["atsScore"]` | `:88-90` (`has_persisted_score`), `:110` (skip-if-scored) | "is a score already persisted" decision |
| `title`, `description`, `requirements` | `:92` → `_job_text` `:144` → `fit_evidence.job_evidence_text` (`app/services/fit_evidence.py:38-58`) | the evidence text scored against the résumé |

It reads **none** of `tailoredResumeId`, `tailoredResumeStatus`, `autopilotSuppressedUntil`,
and none of the other 15 board columns. The subqueries were pure waste on this path.

**Measured cost, production, read-only** (`probe_prod_readonly.py`, 2026-08-09T06:39Z):

```
owner account "Job" rows                              5848   (1116 with fitScore IS NULL)
server statement_timeout                              5s
list_by_user projection, default timeout              QueryCanceled at 5005.9 ms
  "canceling statement due to statement timeout"      <- the exact production exception
same statement, SET LOCAL statement_timeout='180s'    completed in 5701.5 ms, 5848 rows
```

So the mechanism is confirmed exactly as reported: the statement genuinely needs ~5.7 s, the cap
is 5 s, and it is deterministic and worsening — every new job pushes it further over.
(The catalog is larger than the 3,000 stated in the finding: **5848** rows.)

## 2. Failing test first

`apps/api/tests/test_blocker007_fit_scorer_read_path.py` — four tests. A statement timeout is not
reproducible on a small test database, so these assert the **structural** properties that prevent it,
plus a completeness property so "bounded" can never be met by dropping rows:

| test | asserts |
|---|---|
| `test_fit_scorer_read_is_bounded_per_statement` | every `SELECT … FROM "Job"` the scorer issues carries a `LIMIT` **on the outer query** |
| `test_fit_scorer_read_omits_the_board_only_correlated_subqueries` | no scorer `SELECT` mentions `tailoredResumeId` / `tailoredResumeStatus` / `autopilotSuppressedUntil` |
| `test_fit_scorer_does_not_use_the_board_list_query` | the scorer never calls `JobRepository.list_by_user` (anti-regression) |
| `test_batched_read_is_honest_every_job_is_still_visited` | with the batch size forced to 2 and 5 scorable jobs seeded: >1 bounded read issued, `result.scored == 5`, and all 5 rows end with a non-NULL `fitScore` |

The tests capture **real SQL**: a delegating cursor/connection wrapper is monkeypatched over
`app.repositories.job.get_connection`, so the assertions are made against the statements actually
sent to Postgres, not against a mock's call list.

**A first draft of the bounded-read test passed against the broken code and was corrected before
the fix was written.** `list_by_user`'s correlated subqueries each carry their own `ORDER BY … LIMIT 1`,
so a naive substring search for `LIMIT` calls the unbounded outer query "bounded". `_outer_query()`
strips every parenthesised group first, so only a depth-0 `LIMIT` counts. Without that correction
this test would have been fake-green.

**Fail-before** (`blocker007-failbefore2-20260809T064237Z.log`, 2026-08-09T06:42Z, pre-fix tree):
`4 failed, 6 warnings in 11.92s` — each with the intended reason (the log contains the full
unbounded SELECT text with all three subqueries, and the `_SCORING_BATCH_SIZE` AttributeError
proving no batching existed).

## 3. The fix

`apps/api/app/repositories/job.py`
- `_JOB_SCORING_COLUMNS` (`:50`) — `"id", "title", "description", "requirements", "fitScore", "atsScore"`.
  Exactly the six values above; same column set as `fit_score_remediation._EVIDENCE_COLUMNS` plus
  the two score columns.
- `_SCORING_BATCH_SIZE = 500` (`:58`) — mirrors `fit_score_remediation._BATCH_SIZE`.
- `JobRepository.iter_scoring_candidates(user_id)` (`:413`) — generator yielding every job of `user_id`,
  read in keyset-paged batches:
  `SELECT {_JOB_SCORING_COLUMNS} FROM "Job" WHERE "userId" = %s AND "id" > %s ORDER BY "id" LIMIT 500`.
  The connection is released before each batch is yielded, so the caller's per-row writes never run
  inside a held read connection (hosted cap: 25 connections, idle transactions killed at 30 s).

`apps/api/app/agents/fit_scorer.py:81` (was `:74`) — reads through `iter_scoring_candidates`
instead of `list_by_user`. This is a one-line change to the loop header plus its explanatory comment;
the body of `run()` is untouched.

`apps/api/tests/test_v5_thin_description_scoring.py`, `apps/api/tests/test_v5_thin_score_remediation.py` —
the two `_StubRepo` fakes now implement `iter_scoring_candidates` instead of `list_by_user`. Behaviour
and every assertion in those files are unchanged; only the read-contract method name moved.

### Why the fix is *not* "select only unscored jobs"

Tempting, and wrong. Two behaviours depend on the scorer walking **already-scored** rows:

1. **Retirement of pre-gate junk scores** (`fit_scorer.py:93-109`) — rows carrying a persisted score
   but too little evidence get `clear_fit_score`d. A `fitScore IS NULL` predicate would silently stop
   that remediation, which is exactly the bug `fit_score_remediation` exists to fix.
2. **RT-005 stage self-heal** (`fit_scorer.py:110-119`) — a scored job still parked at `discovered`
   is advanced to `screening`.

And the evidence gate itself deliberately stays in Python: `app/services/fit_evidence.py` and
`app/services/fit_score_remediation.py` both document that a hand-written SQL length expression would
be a second, drifting definition of "is this scorable?" (it also cannot reproduce `str.strip()`).
So the row **set** is unchanged — identical to what `list_by_user` returned. Only the per-row
projection and the statement bound changed.

### Batching honesty

- **Complete within a single run.** The walk pages until a batch comes back empty; every row is
  yielded. Verified against production data, not just in tests: 5848 of 5848 rows, 5848 distinct ids
  (§4).
- **The cursor cannot skip or repeat.** It advances on `"id"`, which no scorer write touches
  (`update_fit_score` / `clear_fit_score` / `advance_status` all set other columns).
- **One honest caveat, no worse than before.** A job INSERTed by a concurrent sweep whose `id` sorts
  below the current cursor is not seen by the run in progress; the next 30-minute discovery cycle
  scores it. That job did not exist when the old single `SELECT` ran either, so nothing regressed —
  it is stated here rather than left implicit. This is a scheduling property, not a truncation:
  no row is ever skipped *permanently*.
- No result cap, no "first N jobs" shortcut, no silent drop anywhere.

### What was explicitly NOT done

- The statement timeout was **not** raised — that hides the defect and it returns.
- No DDL was issued against production.
- No test was weakened: nothing skipped, xfailed, or loosened. Two stub fakes were renamed to the
  new read contract, with their assertions untouched.

## 4. Measured after-cost — the shipped code path, against production

`probe_after_fix_readonly.py` imports the real `app.repositories.job` and calls the real
`JobRepository.iter_scoring_candidates` with `get_connection` swapped for a read-only equivalent
(2026-08-09T06:47Z):

```
owner_job_count            5848
rows_yielded               5848      <- every row, no truncation
all_rows_covered           true
distinct_ids               5848      <- no repeats
columns_returned           [atsScore, description, fitScore, id, requirements, title]
statements                 13        (12 full batches + 1 terminating empty read)
slowest_statement_ms       107.7
statement_timeout_headroom 46.4x under the 5s cap
total_wall_ms              1831.7
```

| | before | after |
|---|---|---|
| worst single statement | **5005.9 ms → CANCELED** (5701.5 ms of real work) | **107.7 ms** |
| headroom under the 5 s cap | none — over by ~0.7 s and growing | 46.4× |
| rows returned to the scorer | 0 (the statement died) | 5848 |
| end-to-end read | never completed | 1831.7 ms |

The 1831.7 ms wall time is dominated by 13 connection establishments (~130 ms each) — the repo's
standing short-lived-connection convention, deliberately kept: holding one connection open across
the whole scoring loop would risk the hosted 30-second idle-transaction kill. Pure query time for
the same walk on a single connection measured **180.7 ms** (`probe_prod_readonly.py`, `narrow_batched`).

### Index analysis — **no index needed, no migration required**

Existing indexes on `"Job"` (read from `pg_indexes`, production):
`Job_pkey (id)`, `Job_userId_idx ("userId")`, `Job_status_idx (status)`,
`Job_userId_sourceUrl_key ("userId","sourceUrl")`.

`EXPLAIN (ANALYZE, BUFFERS)` of the new batch query on production:

```
Limit  (cost=0.28..82.03 rows=500 width=471) (actual time=0.005..0.518 rows=500 loops=1)
  Buffers: shared hit=507
  ->  Index Scan using "Job_pkey" on "Job"  (cost=0.28..936.50 rows=5726 width=471)
        Index Cond: (id > ''::text)
        Filter: ("userId" = 'c6c8…'::text)
Execution Time: 0.546 ms
```

The keyset predicate is served by the primary key; `userId` is a cheap filter. 507 buffers for 500
rows is one buffer per row — optimal.

Honest caveat: the planner filters `userId` rather than seeking on it because **one** user currently
owns all 5848 rows, so the filter is non-selective. If the `"Job"` table becomes genuinely
multi-tenant (many users with large catalogs), each batch would read other users' pkey entries and a
composite `("userId", "id")` index would restore the seek. **That is a future migration, and this
fixer did not create it** — it is not needed at current data volumes (0.546 ms), and adding an index
to production is a migration decision for the orchestrator/migrator, not a fixer's DDL.

## 5. Test results

Fail-before, pre-fix tree — `blocker007-failbefore2-20260809T064237Z.log` (2026-08-09T06:42Z):
```
4 failed, 6 warnings in 11.92s
```

Pass-after, targeted suites — `blocker007-passafter-20260809T064410Z.log` (2026-08-09T06:44Z):
```
scripts/run-tests.sh tests/test_blocker007_fit_scorer_read_path.py
                     tests/test_v5_thin_description_scoring.py
                     tests/test_v5_thin_score_remediation.py
                     tests/test_fit_scorer_agent.py
                     tests/test_rt_005_board_stage_sync.py
                     tests/test_rt_008_event_trigger.py -q
47 passed, 6 warnings in 196.35s
```

Full backend suite — `blocker007-fullsuite-20260809T075936Z.log`, run detached under
`flock /tmp/aether-pytest.lock` via `scripts/run-tests.sh -q`, started 2026-08-09T07:59:35Z:

```
2720 passed, 1 skipped, 134 warnings in 3996.06s (1:06:36)
EXIT=0
```

**0 failed, 0 errors.** No `FAILED`/`ERROR` line anywhere in the log. All five changed/added files
have mtimes before 07:59:35Z, so this green run is on the exact tree being committed.

(An earlier attempt at the full suite was killed by the harness at 89% with 0 failures; it produced
no summary line and is therefore NOT the evidence — the run above is a complete re-run.)

**Reconciling with the stated 2698-passed baseline.** This is a shared working tree that currently
also carries two other sessions' uncommitted test files. `--collect-only` on the three untracked
test files present: **21 tests** — `test_blocker007_fit_scorer_read_path.py` (4, mine),
`test_ml_email_drafting_fix.py` (12, another session), `test_gm2s15_f03_resume_upload_quota.py`
(5, another session). 2698 + 21 = 2719, one short of 2720. That remaining +1 is **not accounted
for by this diff** — my change adds exactly one test file (4 tests), deletes no test, and skips
nothing. [INFERRED] it comes from the 2698 figure having been measured on a slightly different
tree state. The load-bearing fact is unambiguous either way: **0 failures, 0 errors, exit 0.**

`ruff check` clean on all five changed/added files.

## 6. Still needs production verification — NOT verified by this fixer

This fixer did **not** deploy and did **not** push (both orchestrator-authorised). Everything below
is unverified against the running production service:

1. **`POST /agents/fit-scorer/run` returns 200 on production after deploy.** The DB-level cost is
   measured and proven; the endpoint has not been exercised post-fix because the fix is not deployed.
2. **The discovery timer's next cycle scores jobs.** Expect the 1116 currently-unscored rows to be
   worked through, and `/var/log/aether/api.log` to stop producing
   `psycopg2.errors.QueryCanceled … agents.py:2534 run_fit_scorer`.
3. **End-to-end run duration.** The read is now ~1.8 s; the ATS scoring of 1116 unscored rows is
   CPU-bound and untouched by this fix. Whether the whole synchronous request completes inside the
   HTTP/gateway timeout on the first post-fix cycle is **unmeasured** and should be watched. If it
   does time out, that is a *different* defect (synchronous long-running agent run) and must be
   filed separately rather than fixed by capping the batch walk.
4. **`GET /jobs` and the other unbounded `list_by_user` callers are NOT fixed and remain exposed to
   the same 5 s cap** — deliberately out of scope for BLOCKER-007, reported here so it is not lost:
   - `apps/api/app/routers/jobs.py:116` (`GET /jobs`) — same unbounded board projection. It is the
     next statement to cross the timeout as the catalog grows; it survives today only because it is
     usually called with a `status` filter that cuts the row count.
   - `apps/api/app/agents/matcher_agent.py:47`
   - `apps/api/app/agents/salary_intelligence_agent.py:124`

## 7. Exact counts

| measurement | result |
|---|---|
| new tests, fail-before (pre-fix tree) | 4 failed / 0 passed |
| new tests + directly affected suites, pass-after | 47 passed / 0 failed |
| full backend suite, final tree | **2720 passed, 1 skipped, 0 failed, 0 errors** (exit 0) |
| `ruff check` on the 5 changed/added files | clean |
| production rows read by the new path | 5848 of 5848, 5848 distinct ids |
| worst statement, before → after | 5005.9 ms (CANCELED) → 107.7 ms |
| index needed | no |
| migration required | no |

## 8. Files changed

```
apps/api/app/repositories/job.py                        +80 / -1
apps/api/app/agents/fit_scorer.py                       +9  / -1  (1 logic line + comment)
apps/api/tests/test_blocker007_fit_scorer_read_path.py  new, 295 lines, 4 tests
apps/api/tests/test_v5_thin_description_scoring.py      stub read-contract rename only
apps/api/tests/test_v5_thin_score_remediation.py        stub read-contract rename only
```

Committed to local `main` with `git commit --only <these paths>` plus this evidence directory.
**Not deployed and not pushed** — both orchestrator-authorised.
This fixer does not approve its own work; BLOCKER-007 remains OPEN pending independent review and
the production verification listed in §6.
