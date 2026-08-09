# BLOCKER-008 — `GET /jobs` 500s: the primary jobs list is dead for the owner

Fixer: `fixer-hard`. Repo `/home/ubuntu/github_repos/aether-job-career-agent`, branch `main`.
Production: https://5cb5f0620.abacusai.cloud

Every measurement below is first-hand, taken by this fixer against the **production** database in a
**READ ONLY** psycopg2 session (`conn.set_session(readonly=True)`). Nothing was written to
production, no DDL was issued anywhere, no secrets were printed, no sub-agents were used, and the
statement timeout was never raised in any shipped code path (only inside the probes, to measure how
much real work the cancelled statement actually needs).

Probe scripts and raw output are in this directory; every claim below cites one of them.

---

## 1. Mechanism — confirmed first-hand, and it is worse than the fit-scorer's was

`probe_prod_readonly.py` → `probe-before-20260809T094614Z.json` (2026-08-09T09:46Z):

```
owner "Job" rows                                     5932   (one user owns all of them)
server statement_timeout                             5s
GET /jobs        (list_by_user, sort=createdAt)      QueryCanceled at 5006.1 ms
GET /jobs?sort=fitScore                              QueryCanceled at 5006.1 ms
  "canceling statement due to statement timeout"     <- the exact production exception
same statement, SET LOCAL statement_timeout='180s'   completed in 6885.9 ms, 5932 rows
```

The same pre-fix projection re-measured 13 minutes later
(`probe4-after-20260809T095938Z.json`) needed **7861.4 ms**. The spread between the two readings is
ordinary load variance; what matters is that both bracket **6.9–7.9 s against a 5 s cap** — 38–57%
over — and that the cost is linear in the catalog, so it only moves one way as jobs accumulate. The
cancellation is deterministic, not intermittent: it reproduced on both sorts, on every attempt.

**Confirmed: this is the same `psycopg2.errors.QueryCanceled` mechanism as BLOCKER-007**, at
`apps/api/app/routers/jobs.py:116` → `JobRepository.list_by_user`
(`apps/api/app/repositories/job.py:373` pre-fix): one `SELECT` over `"Job"` with **no `LIMIT`**,
21 columns plus **three correlated subqueries evaluated per row**.

### 1.1 Where the 6885.9 ms actually goes — measured, not assumed

Same read-only session, same 5932 rows, timeout raised so each variant completes. Each row is an
INDEPENDENT variant — the base projection plus the named subquery group — not a cumulative build-up:

| variant | ms | attributable to the subqueries |
|---|---:|---:|
| base: `_JOB_READ_COLUMNS`, no correlated subqueries | 265.8 | — |
| base + the two tailored-résumé subqueries | 838.8 | +573.0 |
| base + the `autopilotSuppressedUntil` subquery | **6010.2** | **+5744.4** |
| base + all three (exactly what production runs) | 6885.9 | +6620.1 |

**87% of the cost is one subquery**, `_autopilot_suppressed_until_subquery()`
(`job.py:156-214` pre-fix). `probe2-before-20260809T094817Z.json` explains why:

```
AgentRun rows for the owner        7394   (3277 with agentName='coverLetter')
Job rows passing the subquery's eligibility gate    5505   (of 5932)
Job status mix   screening 5501 | ready 340 | applied 30 | discovered 30 | tailoring 27 | archived 4
```

The subquery joins `AgentRun` to `Job` on `(r."input"->>'job_id') = j."id"` — a JSONB extraction
**no index can serve** (confirmed against `pg_indexes`, §4) — and the shape evaluates it twice per
eligible row: once for the letterless candidates, once for the `MAX("createdAt")` success floor. With
5505 of 5932 rows passing the gate, that is on the order of 11,000 passes over a 3,277-row history
per request. The **+5744.4 ms is measured**; the pass count is [INFERRED] from the query shape, since
the planner is free to reorder — but the direction is not in doubt, because removing exactly this
subquery is what takes the statement from 6010.2 ms to 265.8 ms. That is the defect.

### 1.2 What the endpoint actually needs — this IS the board projection

Unlike the fit-scorer, the correlated subqueries here are **genuinely used**. Checked against every
consumer, not assumed:

| derived field | consumer |
|---|---|
| `tailoredResumeId` | `apps/web/src/app/dashboard/jobs/page.tsx:435` — seeds the apply step so an already-tailored job opens at "Review & Apply" (RT-010). Schema: `apps/web/src/lib/api/jobs.ts:44` |
| `tailoredResumeStatus` | drives the "Tailored (pending review)" vs "(approved)" badge. Schema: `apps/web/src/lib/api/jobs.ts:48` |
| `autopilotSuppressedUntil` | `apps/web/src/app/dashboard/jobs/page.tsx:240-244` (`autopilotSuppressionHint`) — the honest "Autopilot paused for this job until …" line (ML-W25). Schema: `apps/web/src/lib/api/jobs.ts:54` |

So the answer is **not** "drop the subqueries" (BLOCKER-007's answer). Every field stays; only *how*
they are read changed.

### 1.3 Frontend consumers — none can paginate, and one reads `.length` as a fact

Eight call sites, all typed as a **bare JSON array**:

```
apps/web/src/app/dashboard/page.tsx:149              /jobs?sort=fitScore     DashboardJob[]
apps/web/src/app/dashboard/agents/page.tsx:366       /jobs?sort=fitScore     Array<{id}>
apps/web/src/app/dashboard/applications/page.tsx:472 /jobs                   Job[]   (error swallowed, §7)
apps/web/src/app/dashboard/cover-letters/page.tsx:104 /jobs                  Job[]
apps/web/src/app/dashboard/jobs/page.tsx:426         /jobs?<filters>         JobRow[]
apps/web/src/app/dashboard/jobs/page.tsx:479         /jobs?include_stale=true Job[]  -> reads all.length
apps/web/src/app/dashboard/resume/page.tsx:104       /jobs                   Job[]
apps/web/src/components/topbar.tsx:70                /jobs?                  Array<{id,title,company}>
```

`dashboard/jobs/page.tsx:479` uses `all.length` as **the user's real catalog size** — the BLOCKER-006
"your board is empty but you have N persisted rows" disclosure. A default page size would make that
number a lie. Two more reasons offset/cursor pagination is the wrong answer here: `GET /jobs`'s
active feed is computed **in Python after the query** (`routers/jobs.py:124` → `active_feed`, which
drops prohibited sources, terminal statuses, stale rows and cross-board duplicates — 5932 rows in,
**2835 out**, measured with the shipped filter in `probe2`), so a SQL page of N is not a page of N
feed rows; and the feed's dedupe is order-dependent across the whole set.

**Decision (task §3): no page/offset parameter, no truncation.** The screen stays CORRECT. What is
bounded is each *statement*, not the result.

---

## 2. Failing test first

`apps/api/tests/test_blocker008_jobs_list_read_path.py` — 8 tests (5 functions, one parametrised ×4).

| test | asserts | before |
|---|---|---|
| `test_jobs_list_read_is_bounded_per_statement` | every `Job` read `GET /jobs` issues is bounded — depth-0 `LIMIT`, or `"Job"` restricted to an explicit `"id" = ANY(%s)` id set | **FAIL** |
| `test_agentrun_is_never_scanned_once_per_job_row` | any statement touching `"AgentRun"` must bound the `Job` rows it does so for | **FAIL** |
| `test_paged_board_read_returns_every_row` | page size forced to 2, 5 jobs seeded → all 5 returned, no repeats, >1 statement | **FAIL** |
| `test_sort_order_still_matches_the_databases_own_ordering` ×4 (`fitScore`/`createdAt`/`title`/`company`) | `DESC NULLS LAST` preserved, compared against the **database's own** `ORDER BY` | pass (guard) |
| `test_row_contract_is_unchanged` | all 24 fields still present on every row | pass (guard) |

The last two pass before *and* after by design: they exist so boundedness cannot be bought by
changing the response contract or the ordering. Stated plainly rather than presented as reproductions.

Assertions are made against **real captured SQL** — a delegating cursor/connection wrapper is
monkeypatched over `app.repositories.job.get_connection`, so what is checked is the statements
actually sent to Postgres.

### The fake-green trap the task warned about — demonstrated, then avoided

The correlated subqueries each carry their own `ORDER BY … LIMIT 1`. Run against the **pre-fix** SQL:

```
naive substring 'LIMIT' in statement  : True   <- FAKE GREEN
depth-0 'LIMIT' in statement          : False  <- honest
occurrences of LIMIT total            : 3
```

The suite therefore reuses BLOCKER-007's depth-0 `_outer_query()` idiom
(`test_blocker007_fit_scorer_read_path.py:160-172`) rather than a fresh naive check.

**Fail-before** (`blocker008-failbefore-20260809T095512Z.log`, 2026-08-09T09:55Z, pre-fix tree):
`3 failed, 5 passed, 6 warnings in 20.59s`. Each failure message contains the full unbounded
`SELECT` with all three subqueries — the exact statement production cancels.

---

## 3. The fix — `apps/api/app/repositories/job.py` only (one file)

**A. `_BOARD_PAGE_SIZE = 500`** (`job.py:66`) — mirrors `_SCORING_BATCH_SIZE`. A per-STATEMENT
bound, never a result cap.

**B. `_autopilot_suppression_expiry_sql()` + `_autopilot_suppression_map()`** (`job.py:149-271`)
replace `_autopilot_suppressed_until_subquery()`. The per-row correlated subquery becomes one
set-based CTE query over an explicitly supplied, bounded id set — it walks the cover-letter history
**once per statement** instead of once per row:

- `elig` = the sweep's eligibility gate (`board_sweep._saturated_job_ids`'s WHERE clause), bounded by
  `j."id" = ANY(%s)`;
- `floors` = `board_sweep._SINCE_LAST_SUCCESS_OR_CLEAR`'s success floor as a `GROUP BY` instead of a
  correlated `MAX`;
- `rn = limit` = `board_sweep._job_suppression_expiry`'s `idx = len(rows) - limit`, i.e. the oldest of
  the `limit` most-recent qualifying failures. Fewer than `limit` rows → no row has `rn = limit` →
  the job is absent → `None`, the same answer as the Python function's `len(rows) < limit` guard.

**C. `list_by_user`** (`job.py:457-556`) — keyset-paged walk on `"id"`, each page carrying
`_JOB_READ_COLUMNS` + the two (now cheap, because bounded) tailored-résumé subqueries, followed by one
bounded suppression statement for that page's ids. One connection for the whole walk — the same
connection count as the single statement it replaces.

**D. `_order_board_rows()`** (`job.py:273-298`) — `ORDER BY <col> DESC NULLS LAST` applied after the
walk, because the pages themselves must be ordered by the keyset column.

**E. `get_by_id`** (`job.py:615-641`) — reads the suppression value through the **same**
`_autopilot_suppression_map`. This is deliberate: leaving the detail path on the old correlated form
would have created a FOURTH encoding of the suppression predicate inside a module whose own
THIRD-COPY WARNING exists to prevent exactly that. Cost there is one extra bounded single-id
statement on an already-open connection.

Copy count is unchanged: `board_sweep.py` (source of truth), `scripts/clear_cover_suppression.py`
(ops escape hatch), and this module — still three, still to be updated together.

### 3.1 Equivalence is proven, not asserted

`probe3_equivalence_readonly.py` → `probe3-equivalence-20260809T095150Z.json` compared the two forms
of the suppression value **row by row over all 5932 production jobs**:

```
shipped correlated form      5927.0 ms, 38 suppressed jobs
proposed set-based, 500/page 12 statements, slowest 27.1 ms, 222.6 ms total, 38 suppressed jobs
mismatches                   0
```

`probe4_after_fix_readonly.py` (§4) then went further and compared **all 24 fields of all 5932 rows**
produced by the real shipped `list_by_user` against the pre-fix projection: **0 differences**.

### 3.2 Honest disclosure of the three behaviour deltas

1. **Tie ordering is now deterministic.** The old `ORDER BY <col> DESC NULLS LAST` had no tiebreaker,
   so rows with equal sort keys came back in an arbitrary order; they now keep the walk's `id` ASC
   order (Python's sort is stable). Strictly more deterministic, never less — but it means
   `active_feed`'s "which of two duplicates survives" can differ from a previous arbitrary draw.
2. **Text sorts (`sort=title`/`sort=company`) now compare in Python.** Production and the test
   database are both `C.UTF-8`, where Python's codepoint order **is** the database's collation —
   verified empirically against the production server (`pg 17.9`, `datcollate=C.UTF-8`; the same
   four-string DESC probe returns an identical order from Postgres and from Python). This is not
   left as an assumption: `test_sort_order_still_matches_the_databases_own_ordering` asserts the
   agreement against the database's own `ORDER BY`, so a future move to a linguistic collation fails
   a test instead of silently reordering the board. Neither sort value is reachable from the UI
   (`dashboard/jobs/page.tsx:326` types `sort` as `"fitScore" | "createdAt"`).
3. **The read is no longer one atomic statement.** The 25 statements run in one transaction at
   READ COMMITTED, so a row UPDATEd by an agent mid-walk is read at whichever page's snapshot covers
   it, and a row INSERTed below the cursor is picked up by the next request. The window is the ~1 s
   the walk takes, against a board the UI re-polls every 20 s. Critically, neither can drop,
   duplicate or invent a row — the cursor advances on the immutable primary key, which no job
   mutation writes.

### 3.3 What was explicitly NOT done

- The statement timeout was **not** raised in any shipped code path.
- **No DDL** was issued anywhere; no migration file was created.
- No page/offset parameter, no default result cap, no "first N jobs" shortcut — nothing truncated.
- No test weakened: nothing skipped, xfailed, or loosened; no existing test edited.
- No frontend file changed. No router change. `routers/jobs.py` is untouched.

---

## 4. Measured after-cost — the shipped code path, against production

`probe4_after_fix_readonly.py` → `probe4-after-20260809T095938Z.json` (2026-08-09T09:59Z) imports the
real `app.repositories.job` and calls the real `JobRepository.list_by_user`, with `get_connection`
swapped for a read-only equivalent and both lazy-DDL guards stubbed to no-ops so the probe cannot
issue DDL:

```
owner_job_count                     5932
rows returned                       5932      <- every row, no truncation
distinct ids                        5932      <- no repeats
all_rows_covered                    true
fields per row                      24        <- identical key set to pre-fix
statements                          25        (12 pages + 12 suppression + 1 terminating empty read)
slowest page statement              104.5 ms
slowest suppression statement       34.2 ms
NULLS LAST preserved                true
descending order preserved          true
suppressed jobs                     38        <- identical to the pre-fix projection
tailored jobs                       296       <- identical to the pre-fix projection
total, sort=createdAt               1016.8 ms
total, sort=fitScore                1069.7 ms

field-by-field vs the PRE-FIX projection, all 5932 rows:   0 differences, 0 extra/missing rows
```

| | before | after |
|---|---|---|
| worst single statement | **5006.1 ms → CANCELED** (6885.9–7861.4 ms of real work) | **104.5 ms** |
| headroom under the 5 s cap | none — over by ~1.9–2.9 s and growing | **47.8×** |
| rows returned to the caller | 0 (the statement died) | 5932 |
| end-to-end repository read | never completed | 1016.8 ms |
| HTTP result | 500 | expected 200 — see §6, not yet verified live |

### Index analysis — **no index needed, no migration required**

Production indexes read from `pg_indexes`:
`Job_pkey (id)`, `Job_userId_idx ("userId")`, `Job_status_idx (status)`,
`Job_userId_sourceUrl_key ("userId","sourceUrl")`, `AgentRun_userId_idx`, `AgentRun_status_idx`,
`AgentRun_status_heartbeatAt_idx`, `Application_jobId_idx`, `Application_userId_idx`,
`Resume_userId_idx`, `Resume_userId_formatHash_idx`.

`EXPLAIN (ANALYZE, BUFFERS)` on production, the new page query:

```
Limit  (cost=0.28..81.48 rows=500 width=667) (actual time=0.008..0.644 rows=500 loops=1)
  Buffers: shared hit=506
  ->  Index Scan using "Job_pkey" on "Job" j
        Index Cond: (id > ''::text)
        Filter: ("userId" = 'c6c8…'::text)
Execution Time: 0.678 ms
```

…and the new suppression query for a 500-id page:

```
Subquery Scan on ranked … (actual time=10.599..10.608 rows=4 loops=1)
  CTE runs -> Seq Scan on "AgentRun" r (actual time=0.025..8.653 rows=3277 loops=1)
  -> WindowAgg -> Sort -> Nested Loop Anti Join -> Hash Left Join -> Hash Join
       -> Bitmap Heap Scan on "Job" j  (Recheck Cond: id = ANY (...))
Execution Time: ~10.6 ms
```

The one sequential scan of `AgentRun` now happens **once per statement** rather than once per row —
8.65 ms of the 10.6 ms, and flat in the number of jobs on the page. An expression index on
`"AgentRun" (("input"->>'job_id'))` would remove even that, and is **not needed**: 10.6 ms is 470×
under the cap. **This fixer created no index and issued no DDL.**

Honest caveat, identical to BLOCKER-007's: the planner filters `userId` rather than seeking on it
because one user currently owns all 5932 rows. If `"Job"` becomes genuinely multi-tenant with many
large catalogs, a composite `("userId","id")` index would restore the seek. That is a **future
migration for the orchestrator/migrator**, not needed at current volumes (0.678 ms), and not created
here.

---

## 5. Test results

| run | result | artifact |
|---|---|---|
| new tests, **fail-before** (pre-fix tree, 09:55Z) | **3 failed, 5 passed** | `blocker008-failbefore-20260809T095512Z.log` |
| new tests + the ML-W25 suppression lockstep suite (09:58Z) | **20 passed, 0 failed** | `blocker008-passafter-20260809T095803Z.log` |
| 14 affected suites (10:00Z) | **162 passed, 0 failed** | `blocker008-affected-20260809T100025Z.log` |
| full backend suite, frozen tree (10:14Z) | **2728 passed, 1 skipped, 0 failed** | `blocker008-fullsuite-20260809T101409Z.log` |

The 14 affected suites: `test_blocker008_jobs_list_read_path`, `test_ml_w25_autopilot_suppression_visibility`,
`test_job_discovery`, `test_jobs_insights_apply`, `test_blocker_006_empty_feed`,
`test_rt_005_board_stage_sync`, `test_rt_009_010_apply_wiring`, `test_gap_p6_sourcing`,
`test_source_availability`, `test_clear_pipeline`, `test_applications_pipeline_clear`,
`test_blocker007_fit_scorer_read_path`, `test_fit_scorer_agent`, `test_job_alert_intake`.

`test_ml_w25_autopilot_suppression_visibility.py` is the load-bearing one: 11 tests that assert the
API's `autopilotSuppressedUntil` equals `board_sweep._job_suppression_expiry(...)` **exactly**, for
both `GET /jobs` and `GET /jobs/{id}`, across saturation / below-threshold / genuine-success /
ops-clear / has-an-Application / applied / archived / no-fitScore cases. It passes unchanged — no
test in it was edited.

All runs were executed via `scripts/run-tests.sh` under `flock /tmp/aether-pytest.lock` on
session-unique timestamped log paths. `ruff check` clean on both changed/added files.

**The full-suite run is on the exact committed tree, and that was enforced rather than assumed.** A
first full-suite run was started at 10:06:59Z; two further edits then landed on `job.py` (both purely
docstring text — the READ COMMITTED note and the measurement figures). Rather than argue that a
docstring cannot change behaviour, that run was discarded and the suite restarted at **10:14:09Z** on
a frozen tree. The two shipped files were hashed before the run and are unchanged after it:

```
89320c538e2285302d700d90aef533fd6adece2090cd4c0b04e6a9588f79a063  apps/api/app/repositories/job.py
ec1acc6411eeda9e78990e2d52da8ac884717887bfae45c5eee6debf05d6352e  apps/api/tests/test_blocker008_jobs_list_read_path.py
```

(Only this evidence file changed after the run started — it records the run's own result.)

**One disclosed redaction.** Pytest's failure output repr'd the `auth_headers` fixture, printing 3
ephemeral JWTs for randomly-generated `@example.com` users on the `aether_test` schema (which the
suite TRUNCATEs on every run). They are not production credentials and grant nothing, but they are
bearer tokens, so each was replaced in the committed log with `Bearer <REDACTED-EPHEMERAL-TEST-JWT>`.
Nothing else in any artifact was altered — the failure messages, the captured pre-fix SQL and the
summary line are verbatim, and a re-run reproduces `3 failed, 5 passed` on the pre-fix tree.

**FULL SUITE — `blocker008-fullsuite-20260809T101409Z.log`, started 2026-08-09T10:14:09Z:**

```
2728 passed, 1 skipped, 134 warnings in 4018.09s (1:06:58)
EXIT=0
```

**0 failed, 0 errors.** No `FAILED`/`ERROR` line anywhere in the log. The stated baseline is
**2720 passed / 0 failed**; this run is 2720 + **8**, and 8 is exactly the number of tests this diff
adds (`test_blocker008_jobs_list_read_path.py`: 4 functions + 1 parametrised x4). The delta is fully
accounted for — no test was added by accident, none was removed, none was skipped, and the single
skip is the same pre-existing one the baseline carries. The log contains no bearer tokens
(this suite had no failures, so no fixture was repr'd).

---

## 6. Still needs production verification — NOT verified by this fixer

Not deployed, not pushed (both orchestrator-authorised). Unverified against the running service:

1. **`GET /jobs` and `GET /jobs?sort=fitScore` return 200 after deploy.** The DB-level cost is
   measured and the row/field output is proven byte-identical, but the endpoint has not been
   exercised post-fix because the fix is not deployed.
2. **End-to-end response time and payload size.** The repository read is now ~1.0 s, but the active
   feed for this account is **2835 rows ≈ 10.6 MB of JSON** (`probe2`). Serialisation and transfer
   are untouched by this fix. If `GET /jobs` is slow *after* deploy despite the DB read being ~1 s,
   that is a **different** defect (an unpaginated 10 MB board payload) and must be filed separately —
   fixing it means giving the frontend a real pagination contract, which is out of scope here and
   would truncate the screen if done unilaterally. Recommend filing it now as a follow-up.
3. **`GET /jobs/{id}` still returns 200** (it does today; it now issues 2 statements instead of 1).

---

## 7. Reported for the record, deliberately NOT fixed here

**7a. The frontend has been swallowing this outage for four weeks — its own defect.**
`apps/web/src/app/dashboard/applications/page.tsx:472-475`:

```tsx
try {
  setJobs(await apiRequest<Job[]>("/jobs"));
} catch {
  /* pipeline stages are progressive enhancement */
}
```

A bare `catch {}` with no state change, no log, no user-visible degradation notice. Per the
reviewer's `git blame` this has been live since `9dd4411d` (2026-07-12). The Application Tracker's
pipeline stages have therefore been silently missing rather than reporting an error, which is why a
100%-failing core endpoint went unnoticed. Not fixed in this change (task §6). Note the same pattern
exists at `apps/api/app/agents/scout_agent.py:127-131`, where a failed history read is logged but
downgraded to "history is an optimisation" — honest logging, but it also masked this outage.

**7b. The other `list_by_user` call sites — assessed as task §4 asked.**
They are **already fixed by this change, with zero additional edits**, because they all go through
the same repository method:

| call site | reads | action taken |
|---|---|---|
| `apps/api/app/agents/matcher_agent.py:47` | `list_by_user(user_id, sort="fitScore")` → top row | none needed — bounded now |
| `apps/api/app/agents/salary_intelligence_agent.py:124` | `list_by_user(user_id)` | none needed — bounded now |
| `apps/api/app/agents/company_research_agent.py:183` | `list_by_user(user_id)` | **not in the task's list** — same, bounded now |
| `apps/api/app/agents/market_trends_agent.py:138` | `list_by_user(user_id)` | **not in the task's list** — same, bounded now |
| `apps/api/app/agents/scout_agent.py:127` | `list_by_user(user_id)` → fitScore history | **not in the task's list** — same, bounded now |

Three call sites beyond the two the task named were found and are reported here so they are not lost.

**Follow-up, NOT done (scope):** none of these five agents reads `tailoredResumeId`,
`tailoredResumeStatus` or `autopilotSuppressedUntil`, so they still pay for the tailored-résumé
subqueries and the suppression map they do not use — now bounded and cheap, but wasted. Each wants
its own narrow projection (BLOCKER-007's pattern), which is a separate change per agent, not a
one-line read-path swap. Filed here as a follow-up rather than expanded into this diff.

---

## 8. Exact counts

| measurement | result |
|---|---|
| new tests, fail-before (pre-fix tree) | 3 failed / 5 passed (the 5 are declared non-regression guards) |
| new tests + ML-W25 lockstep suite, pass-after | 20 passed / 0 failed |
| 14 affected suites, pass-after | 162 passed / 0 failed |
| full backend suite, final tree | **2728 passed, 1 skipped, 0 failed, 0 errors** (exit 0) = baseline 2720 + this diff's 8 |
| `ruff check` on the 2 changed/added files | clean |
| production rows read by the new path | 5932 of 5932, 5932 distinct ids, 24 fields each |
| field-by-field diff vs the pre-fix projection (5932 rows × 24 fields) | **0 differences** |
| suppression-value equivalence, independent probe | **0 mismatches**, 38 suppressed both ways |
| worst statement, before → after | 5006.1 ms (CANCELED) → 104.5 ms |
| endpoint read, before → after | never completed → 1016.8 ms |
| pagination added | no (deliberate — §1.3) |
| truncation | none |
| index needed | no |
| migration required | no |

## 9. Files changed

```
apps/api/app/repositories/job.py                          +233 / -85   (one file)
apps/api/tests/test_blocker008_jobs_list_read_path.py      new, 8 tests
uat/reports/evidence/gold-master-v2/blocker008/            this evidence directory
```

Committed to local `main` with `git commit --only <these paths>`.
**Not deployed and not pushed** — both orchestrator-authorised.

Note on the probes: `probe_prod_readonly.py`, `probe2_prod_readonly.py` and
`probe3_equivalence_readonly.py` import `_autopilot_suppressed_until_subquery`, which this fix
removes — they are the artifacts of record for the PRE-fix state and are not re-runnable against the
fixed tree. `probe4_after_fix_readonly.py` inlines its own copy of the pre-fix projection and IS
re-runnable; it re-proves the equivalence over all 24 fields, superseding probe3's single-field check.

This fixer does not approve its own work. BLOCKER-008 remains OPEN pending independent review and
the production verification listed in §6.
