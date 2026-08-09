# GOLD-MASTER-V2 §15 STEP 5 — Independent Review of BLOCKER-008

Reviewer role only. Did not author `6c41243`. No code edited, no commit of source, no push, no deploy.
Repo `/home/ubuntu/github_repos/aether-job-career-agent`, branch `main`. Production:
`https://5cb5f0620.abacusai.cloud`. Review performed 2026-08-09.

Commit under review: `6c41243` "fix(BLOCKER-008): bound the board list read and compute autopilot
suppression set-wise". Author's evidence: `uat/reports/evidence/gold-master-v2/blocker008/FIX.md`.

Method: read the full diff (`git show 6c41243`), read every probe script and every probe JSON/log
byte-for-byte, cross-checked the SQL the fixer claims is shipped against what is actually in
`apps/api/app/repositories/job.py` on `HEAD`, re-ran the new test file and the two load-bearing
regression suites myself against the live `main` tree (targeted files only, under the shared
`flock`, no full-suite run per standing rules), and ran one independent READ-ONLY production probe
of my own (below) to close a gap I found in the evidence bundle. No secrets were printed at any
point; the production DSN was read the same way the fixer's own probe scripts read it
(`uat/reports/evidence/gold-master-v2/blocker008/probe_prod_readonly.py:read_prod_url`) and never
echoed.

---

## 1. Cost attribution — HOLDS [VERIFIED-WITH-FRESH-EVIDENCE]

`probe-before-20260809T094614Z.json` and `probe2-before-20260809T094817Z.json` on disk report
exactly the figures FIX.md §1.1 cites: `base_columns_only_no_subqueries` 265.8 ms,
`base_plus_autopilot_subquery` 6010.2 ms (+5744.4 ms over base = the claimed 87% of 6885.9 ms),
`autopilot_gate_eligible_rows` 5505 of 5932, `agentrun_coverletter_rows` 3277. These are read
straight from the JSON artifacts, not re-derived from prose.

I independently confirmed the "no index can serve this join" premise: `probe-before...json`'s
`indexes` array lists every index on `AgentRun` and `Job` in production —
`AgentRun_pkey`, `AgentRun_status_heartbeatAt_idx`, `AgentRun_status_idx`, `AgentRun_userId_idx`,
`Job_pkey`, `Job_status_idx`, `Job_userId_idx`, `Job_userId_sourceUrl_key` — none on `AgentRun.input`
or any expression index on `input->>'job_id'`. The claim holds.

The pass count (~11,000 nested-loop passes) is correctly labelled `[INFERRED]` in FIX.md itself
rather than asserted as measured — appropriately hedged.

## 2. Equivalence — HOLDS, genuinely independent (not a self-comparison) [VERIFIED-WITH-FRESH-EVIDENCE]

Read `probe3_equivalence_readonly.py` end to end. It computes `truth` by importing and calling the
OLD `_autopilot_suppressed_until_subquery()` (still present in the pre-fix tree the probe ran
against) and separately runs a `set_sql` string that is **hand-copied into the probe file**, not
imported from the shipped function. I diffed that hand-copy against the actual shipped
`_autopilot_suppression_expiry_sql()` in `job.py` (normalizing whitespace only): identical modulo the
final column alias (`expiry` in the probe vs `"autopilotSuppressedUntil"` shipped) and cosmetic comma
spacing — same query. So this is old-implementation vs. independently-duplicated-new-SQL, not
new-vs-new. `probe3-equivalence-20260809T095150Z.json` on disk: `mismatches: 0` at both page sizes
(500 and 1000), `shipped_non_null: 38`, `non_null: 38` both ways.

`probe4_after_fix_readonly.py` goes further: it imports and calls the REAL, shipped
`job_repo.JobRepository().list_by_user()` (verified by reading the import and call, not the fixer's
prose) and separately reconstructs the pre-fix single-statement projection **inline in the probe**
(not imported — the pre-fix function no longer exists post-commit). I diffed that inline
reconstruction against the pre-fix subquery body preserved in `git show 6c41243`'s diff context: same
`CASE WHEN ... THEN (SELECT ... OFFSET {limit-1} LIMIT 1) ELSE NULL END` shape, same predicates. Result
on disk (`probe4-after-20260809T095938Z.json`): `differences: 0`, `extra_rows_in_new: []`, `rows_compared: 5932`.
Genuine equivalence proof, not a tautology.

## 3. One encoding — HOLDS [VERIFIED-WITH-FRESH-EVIDENCE]

`grep -n "_autopilot_suppressed_until_subquery"` across `apps/api/` (excluding the evidence dir)
returns nothing — the old function is fully removed, not left as dead code alongside the new one.
`job.py:92-107`'s THIRD-COPY WARNING comment still names exactly three copies
(`board_sweep.py` source of truth, `scripts/clear_cover_suppression.py` ops tool, and this module),
and `list_by_user`/`get_by_id` both route through the single new
`_autopilot_suppression_map`/`_autopilot_suppression_expiry_sql` pair. Confirmed by reading
`board_sweep.py:287-528`, which independently encodes the same predicate as claimed (source of
truth, untouched by this diff). One encoding here, as claimed.

## 4. Pagination judgment — CORRECT CALL, catalog is complete [VERIFIED-WITH-FRESH-EVIDENCE]

Read `list_by_user` on `HEAD`: the `while True` loop only exits when a page comes back empty,
`rows.extend(page)` runs unconditionally on every non-empty page, and there is no `LIMIT`/`OFFSET`
parameter reachable from the method signature or the router. `probe4`'s field-by-field diff
(5932 rows returned, 5932 distinct ids, `all_rows_covered: true`, 0 differences vs. the pre-fix
projection) is real evidence the walk is not silently truncating, not just a code-reading inference.
I independently confirmed the 8 frontend call sites and their bare-array typing
(`Job[]`, `DashboardJob[]`, `JobRow[]`, `Array<{...}>`) by grepping each file myself, and read
`apps/web/src/app/dashboard/jobs/page.tsx:470-489` directly: `all.length` genuinely feeds
`historyCount`, the BLOCKER-006 "you have N persisted jobs" disclosure. A page/offset parameter here
would indeed make that number wrong. Judgment: correct — "bounded per statement, complete in
aggregate" is the right trade-off, not truncation in disguise.

## 5. Fake-green hunt — one new-code finding (see §6.2 below); tests are clean

Read the full `test_blocker008_jobs_list_read_path.py`. `_outer_query`/`_is_bounded` is the same
depth-0-parenthesis-stripping idiom as `test_blocker007_fit_scorer_read_path.py:160-175` (compared
byte-for-byte via grep), correctly generalized to also accept an explicit `"id" = ANY(%s)`/`"id" = %s`
bound (needed because the suppression CTE bounds via an id set, not a `LIMIT`). Not a naive substring
check.

I reran the suite myself against the live tree rather than trusting the logged numbers:

```
$ scripts/run-tests.sh tests/test_blocker008_jobs_list_read_path.py -q
8 passed, 6 warnings in 21.26s
$ scripts/run-tests.sh tests/test_ml_w25_autopilot_suppression_visibility.py tests/test_blocker007_fit_scorer_read_path.py -q
16 passed, 6 warnings in 37.54s
$ ruff check app/repositories/job.py tests/test_blocker008_jobs_list_read_path.py
All checks passed!
```

All three match the FIX.md claims exactly. I also read `blocker008-failbefore-20260809T095512Z.log`
directly: the captured pre-fix SQL in the failure output for `test_jobs_list_read_is_bounded_per_statement`
is the exact 3-subquery unbounded statement removed by this diff (`OFFSET 2 LIMIT 1` = the pre-fix
`limit=3` autopilot subquery's own internal `LIMIT`, correctly distinguished from the missing
depth-0 `LIMIT` on the outer query). `short test summary info` in that log lists exactly the 3
structural tests as `FAILED` and no others — matches "3 failed, 5 passed" precisely, not a rounded
or approximate match. No unredacted bearer tokens anywhere in the log bundle (`grep -v REDACTED`
on every `Bearer ` occurrence returns nothing). Hashes in FIX.md §5
(`job.py` → `89320c53...`, test file → `ec1acc64...`) match `sha256sum` on the current committed
files exactly — the full-suite run was genuinely against the frozen, shipped tree.

Prohibited-pattern grep across the diff's added lines (`TODO|FIXME|@ts-ignore|eslint-disable|
type:\s*ignore|noqa|Math\.random|except:|except Exception:|placeholder|dummy|hardcod`): one hit,
`# noqa: A002` on `test_blocker008_jobs_list_read_path.py:115` (`def execute(self, query, vars=None)`)
— a single, narrowly-scoped ruff rule suppression for a parameter name (`vars`) that shadows a
builtin, required because it mirrors psycopg2's own `cursor.execute(query, vars)` signature. Not a
blanket suppression, not hiding an error. No other hits.

## 6. Behaviour deltas

**6.1 Deterministic tie ordering — ACCEPTABLE.** Read `_order_board_rows`: Python's `list.sort` is
stable, so equal-key rows now keep walk order (`id` ASC) instead of Postgres's unspecified tie order
under a bare `ORDER BY col DESC NULLS LAST`. I traced the actual consumer,
`apps/web/.../active_feed.py:195-229`: it walks its input in order and keeps the FIRST row per
`(company, title, location)` fingerprint, so which cross-posted duplicate survives can indeed change.
But the pre-fix behaviour was **already unspecified** or a given tiebreaker — Postgres does not
guarantee tie order without an `ORDER BY` tiebreaker, so two identical requests could already return
different survivors. The new behaviour is a strict improvement (deterministic, reproducible) over an
already-nondeterministic baseline, exactly as FIX.md frames it. Not a regression. Minor note for the
record: which duplicate wins is still an accident of `id` ordering rather than a deliberate
"most recent" or "most complete" choice — worth a follow-up ticket, not a blocker.

**6.2 Text-sort collation — TRUE, but the evidence bundle did not contain its own proof; I closed
that gap myself.** FIX.md and the `job.py` docstring both assert "production is `pg 17.9`,
`datcollate=C.UTF-8`" and call this "verified empirically... not left as an assumption." I searched
every file in `uat/reports/evidence/gold-master-v2/blocker008/` for `collate`, `UTF-8`, `datcollate`,
`version()`, `PostgreSQL ` — **zero hits outside FIX.md itself**. None of the five probe scripts
queries `pg_database` or `version()`. This is a real finding: a claim stated as "verified, not
assumed" that has no filed artifact backing it — the same category of overclaim the task asked me to
hunt for, just in prose rather than in a test.

I closed the gap with my own READ-ONLY probe, using the identical `read_prod_url`/`translate`
helpers the fixer's own scripts use (`probe_prod_readonly.py`), reading no secret values and
printing none:

```
version: PostgreSQL 17.9 (Ubuntu 17.9-1.pgdg24.04+1) on aarch64-unknown-linux-gnu ...
collate:  ('<dbname-redacted-not-a-secret-but-omitted-for-hygiene>', 'C.UTF-8', 'C.UTF-8')
```
[VERIFIED-WITH-FRESH-EVIDENCE, this review, 2026-08-09] — the underlying factual claim is TRUE:
production really is `C.UTF-8`, so Python codepoint order really does agree with the database's own
collation for the `title`/`company` sorts, and `test_sort_order_still_matches_the_databases_own_ordering`
(read in full) does genuinely assert Python's output against the test DB's own `ORDER BY` rather than
hard-coding an assumed order. The delta is safe. But this is a **documentation/evidence-discipline
gap in the shipped artifact bundle**, not a code defect — see "must change first" below.

**6.3 Non-atomic READ COMMITTED walk — ACCEPTABLE, correctly reasoned.** Confirmed `get_connection()`
(`apps/api/app/db.py:146-154`) opens one plain psycopg2 connection with no isolation-level override
(Postgres default = READ COMMITTED) and the whole 25-statement walk runs on that one connection/one
transaction with no intermediate commits — so the description is accurate: each statement sees its
own fresh READ COMMITTED snapshot, not one frozen transaction-wide snapshot. Confirmed `"id"` is
never the target of any `UPDATE ... SET` in `job.py` (grepped every `UPDATE "Job" SET` site) — the
keyset cursor genuinely cannot skip or repeat a row. The stated risk window (~1 s walk vs. 20 s UI
poll) is honestly bounded, and the "cannot drop/duplicate/invent a row" claim is structurally true,
not just asserted.

## 7. Scope — HOLDS [VERIFIED-WITH-FRESH-EVIDENCE]

Grepped `list_by_user` across `apps/api/app/agents/`: `matcher_agent.py:47`,
`salary_intelligence_agent.py:124`, `market_trends_agent.py:138`, `company_research_agent.py:183`,
`scout_agent.py:127` all call it exactly as FIX.md §7b claims — confirmed transitively fixed with
zero additional edits, since they all route through the one repository method this diff bounds.
`git show 6c41243 --stat --name-only` (excluding the evidence directory) touches exactly two files:
`apps/api/app/repositories/job.py` and the new test file. `git diff HEAD~1 HEAD -- apps/api/app/routers/jobs.py`
and `git diff HEAD~1 HEAD -- apps/web/` both return empty — router and frontend genuinely untouched,
matching "no frontend or router change" verbatim. No DDL anywhere in the diff (`grep -n
"CREATE\|ALTER\|DROP"` on the changed file: no hits); the two `ensure_job_*_column()` lazy-DDL guards
called are pre-existing, unmodified functions called the same way as before.

## 8. Not fixed here, correctly left alone (task said don't touch)

Confirmed `apps/web/src/app/dashboard/applications/page.tsx:472-475` still has the bare `catch {}`
(unchanged by this diff — I only observe, did not touch), and `scout_agent.py:127-131` still has its
downgrade-to-optimisation logging. Both correctly out of scope per the task and per FIX.md §7a.

---

## Verdict

| # | Claim | Holds | Evidence |
|---|---|---|---|
| 1 | Cost attribution (87% / 5744 ms) | true | probe-before/probe2-before JSON, cross-checked against `pg_indexes` list; no expression index exists |
| 2 | Equivalence proven twice, not self-compared | true | probe3 (old-fn vs. independently duplicated new-SQL, diffed byte-for-byte against shipped code) + probe4 (real shipped call vs. inline pre-fix reconstruction), both artifacts on disk with 0 mismatches/0 differences |
| 3 | One encoding, not two | true | old function fully removed (grep), THIRD-COPY WARNING count unchanged at 3, `board_sweep.py` independently confirmed as the separate source of truth |
| 4 | No pagination is the correct call; catalog complete | true | code walk-to-empty confirmed by reading; field-by-field diff 5932/5932 rows, 0 differences; `.length` consumer confirmed at `jobs/page.tsx:479-480` |
| 5 | Fail-before genuine, no fake-green | true (one prose-level gap found, §6.2) | reran tests myself (8/8, 16/16, ruff clean); fail-before log's captured SQL matches the removed pre-fix statement; hashes match; depth-0 LIMIT idiom correctly reused, not a naive substring check |
| 6 | Three behaviour deltas | (1) acceptable (2) true but unfiled evidence — closed by this review (3) acceptable | see §6.1–6.3 |
| 7 | Scope: 5 other call sites transitively fixed, nothing else touched | true | grepped all 5 call sites; diff touches exactly 2 non-evidence files; router/frontend diff empty |

**returns_complete_catalog: true.**

**fake_green_found:** one instance, at the evidence-bundle level rather than in a test: FIX.md and
the `job.py` docstring both assert the `datcollate=C.UTF-8` production fact as "verified empirically...
not left as an assumption," but no artifact in `uat/reports/evidence/gold-master-v2/blocker008/`
actually establishes it — I had to run my own probe to confirm it. The claim turned out to be TRUE,
so this is an evidence-discipline defect, not a substantive one, but it is exactly the "claims stated
stronger than what is on disk" pattern this review exists to catch.

**must_change_first (before this finding can be marked VERIFIED-CLOSED, not before deploy):**
1. Add a probe artifact (a two-line `SELECT version(); SELECT datcollate FROM pg_database WHERE
   datname = current_database();` against production, READ ONLY) to
   `uat/reports/evidence/gold-master-v2/blocker008/`, so the collation claim in `job.py`'s own
   docstring is backed by something other than prose. Low effort, does not require touching the fix
   itself.

**deploy_risks:**
- §6 of FIX.md is honest that `GET /jobs` returning 200 post-deploy is NOT YET verified live — that
  is the correct next step immediately after deploy, not before (cannot verify a 200 without
  deploying the fix that stops the 500).
- The 10.6 MB active-feed payload (`probe2`'s `approx_response_bytes_full_rows`) is pre-existing,
  unrelated to this diff, and correctly filed as a separate follow-up rather than folded in here.
- §6.1's duplicate-survivor delta for cross-posted listings is low-risk but worth a visual spot-check
  on the live board post-deploy (which of two duplicate cards shows) since it is a real, if minor,
  user-visible change.
- Statement count per request rises from 1 to up to 25 (still one connection, one transaction, ~1 s
  total per FIX.md's own measurement) — bounded and measured, not a concern at current volume, but
  worth watching in whatever the team uses for production latency/CPU monitoring after deploy.

**overall: SHIP**

The database-level defect (deterministic 500 on the primary jobs screen for the paying account) is
severe and the fix is minimal, single-file, additive-only (no DDL/migration), honestly bounded (no
truncation), and its central technical claims independently reproduce against the live production
database and the live test suite. The one gap found — an unfiled-but-true claim about production's
collation — is a documentation completeness issue, not a functional defect, and I have supplied
fresh verifying evidence for it in this review. It should not block the deploy; it should be closed
as a fast follow-up to the evidence bundle.

Artifact: `uat/reports/evidence/gold-master-v2/review/BLOCKER-008-REVIEW.md`
