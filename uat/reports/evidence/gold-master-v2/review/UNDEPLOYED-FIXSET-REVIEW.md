# GOLD-MASTER-V2 §15 STEP 5 — Independent review of the undeployed fix set

Reviewer: `reviewer` sub-agent. Did NOT author any of this work. No code edited, nothing committed
by this review except this artifact (`git commit --only`, per standing rules). No sub-agents/forks
used — serial work only. Full pytest suite NOT run (per standing rules); targeted files run directly
where a claim needed checking, all under `flock /tmp/aether-pytest.lock` so as not to collide with
other sessions' queued runs on the shared `aether_test` schema.

Repo: `/home/ubuntu/github_repos/aether-job-career-agent`, branch `main`. Review performed
2026-08-09, ~09:00–09:25Z. Production: `/var/log/aether/api.log` read directly (read-only) for
live-log corroboration; no production DB writes, no secrets printed.

Commits reviewed: `c25bfa2` (BLOCKER-007), `f5d7139` (ATS-KW-001), `a090f81`+`0ce7098` (F-02),
`9d3be57` (F-03), `5f9e775` (F-04). One adjacent commit inspected because it is materially relevant
to the fake-green hunt the task specifically asked for: `19d4c65` (`test(WC-INTERVIEW-SEED-001)`),
which patches a vacuous test inside 5f9e775's own new test file.

---

## 1. BLOCKER-007 — `POST /agents/fit-scorer/run` 500s on every discovery cycle

**Verdict: PASS**

### 1.1 Real fix, not a symptom patch

`apps/api/app/agents/fit_scorer.py:81` now reads through `JobRepository.iter_scoring_candidates`
instead of `list_by_user` (`apps/api/app/repositories/job.py:373`, the board's 21-column,
3-correlated-subquery, no-`LIMIT` projection). The new method
(`apps/api/app/repositories/job.py:413-468`) is a genuine keyset-paged, narrow-projection read
(`_JOB_SCORING_COLUMNS`, `job.py:50`; `_SCORING_BATCH_SIZE=500`, `job.py:58`) — this removes the
actual cost driver (the per-row correlated subqueries and the missing `LIMIT`), not just adds a
try/except around the timeout or catches the exception. **[VERIFIED-WITH-FRESH-EVIDENCE, code
read 2026-08-09T09:xx]**

### 1.2 Live production confirmation the defect is real and this is the only active outage

Read directly from `/var/log/aether/api.log` (not from the fixer's own artifacts):

```
$ grep -c 'POST /agents/fit-scorer/run HTTP/1.1" 500' since 2026-08-07T22:05:51Z .. 2026-08-09T09:05:10Z
71
$ grep 'POST /agents/fit-scorer/run HTTP/1.1" 200' in the same window
0
$ grep '" 500 ' in the last 2 calendar days, excluding fit-scorer
0
```
First occurrence in-window: `370163: 2026-08-07T22:05:51Z ... 500`. Last: `427043:
2026-08-09T09:05:10Z ... 500`. Every failure carries the identical traceback through
`routers/agents.py:2534 run_fit_scorer` ending in `psycopg2.errors.QueryCanceled: canceling
statement due to statement timeout`. This exactly matches the task's own count (71 failures, 0
successes) and confirms "the ONLY live recurring error." **[VERIFIED-WITH-FRESH-EVIDENCE,
`/var/log/aether/api.log`, read 2026-08-09]**

### 1.3 Fake-green hunt — the depth-0 parsing fix holds, and I found no second instance in this diff

`apps/api/tests/test_blocker007_fit_scorer_read_path.py:160-172` (`_outer_query`) strips every
parenthesised group by depth before searching for `LIMIT`, which is what stops the correlated
subqueries' own `ORDER BY ... LIMIT 1` from satisfying the "outer query is bounded" assertion. I
traced this by hand against the captured pre-fix SQL in
`uat/reports/evidence/gold-master-v2/blocker007/blocker007-failbefore2-20260809T064237Z.log` (the
raw unbounded `SELECT` with all three subqueries, each carrying its own `LIMIT 1`) and confirmed the
depth-tracking is correct: only a `(`/`)`-depth-0 token contributes to the stripped string, so a
`LIMIT` inside any subquery is invisible to the check. I independently reran the four new tests plus
the two renamed-stub suites fresh myself (not trusting the artifact log alone):

```
$ flock -w90 /tmp/aether-pytest.lock scripts/run-tests.sh tests/test_blocker007_fit_scorer_read_path.py \
    tests/test_v5_thin_description_scoring.py tests/test_v5_thin_score_remediation.py -q
22 passed, 6 warnings in 32.84s
```
**[VERIFIED-WITH-FRESH-EVIDENCE, pytest run 2026-08-09T09:1xZ]**

I also confirmed `probe_after_fix_readonly.py` (the "after" cost measurement) calls the real,
shipped `JobRepository().iter_scoring_candidates` — not a re-implementation — with only
`get_connection` swapped for a read-only equivalent that opens a fresh connection per batch exactly
like the real generator does; the "13 statements / 107.7 ms slowest / 1831.7 ms wall" figures in
`FIX.md` and the module docstring (`job.py:421-429`) are therefore measuring the actual code path,
not a stand-in. The apparently-conflicting "12 batches / 31.1 ms / 180.7 ms" figure quoted in the
test file's own docstring (top of `test_blocker007_fit_scorer_read_path.py`) comes from a *different*
probe (`probe_prod_readonly.py`'s `narrow_batched`, a single reused connection, no per-batch
reconnect) — both numbers are legitimate and internally consistent once you know which script
produced which; this is not a discrepancy, but it is worth noting that citing two different
"batches"/"ms" figures for "the same" measurement without labelling which probe each came from is
sloppy documentation, not a fabrication. **[VERIFIED-WITH-FRESH-EVIDENCE, code read]**

### 1.4 The four load-bearing claims, checked rather than accepted

- **Batching honesty (5848/5848, no truncation, no repeats).** The cursor advances on `"id"`
  (`WHERE "id" > %s ORDER BY "id" LIMIT 500`, `job.py:454-458`), which is the primary key and is
  never written by any scorer mutation (`update_fit_score`/`clear_fit_score`/`advance_status` all
  touch other columns, confirmed at `job.py:490-531`). Standard keyset pagination over an immutable,
  unique, totally-ordered key cannot skip or repeat a row within one run. I did not re-run the
  production 5848-row probe myself (that would mean this review connecting to the production
  database, which is outside a reviewer's remit); I instead independently verified the *mechanism*
  is correct by code inspection and by the dedicated test
  `test_batched_read_is_honest_every_job_is_still_visited` (batch size forced to 2, 5 seeded jobs,
  asserts `result.scored == 5` and all 5 end with non-NULL `fitScore`), which I reran and it passes.
  The 5848/5848/5848-distinct-ids production figure itself is **[INFERRED from the fixer's
  `probe_after_fix_readonly.py` output + code review of the mechanism, not independently
  re-measured against production by this review]**.
- **Row SET genuinely unchanged (no `fitScore IS NULL` filter added).** Confirmed:
  `_JOB_SCORING_COLUMNS`/the new SQL carry no such predicate (`job.py:454-457`), and
  `fit_scorer.py:88-119` still computes `has_persisted_score` and runs the retire/self-heal branches
  over already-scored rows exactly as before — only the loop's *source* changed, not the body. The
  claim that this is what retires pre-gate junk scores and self-heals `discovered`-stuck jobs holds
  up against the actual code, not just the commit message. **[VERIFIED-WITH-FRESH-EVIDENCE, code
  read]**
- **Statement timeout not raised anywhere.** `grep -rn "statement_timeout" apps/api/app/
  apps/api/tests/` returns only the *docstring prose* describing the production timeout — no `SET
  statement_timeout` / `SET LOCAL statement_timeout` was added to production code. **[VERIFIED, grep
  2026-08-09]**
- **Evidence gate stays in Python, no second SQL copy.** `has_scorable_evidence`/`job_evidence_text`
  (`app/services/fit_evidence.py:32-58`) are unchanged and are still what `fit_scorer.py:92-96` calls;
  no length/`LENGTH()` predicate was added to the new SQL. **[VERIFIED, code read]**

### 1.5 Deploy risk — confirmed as stated, plus one risk the task's framing understates

- **No index, no migration required — confirmed.** `git show c25bfa2 --stat` touches no migration
  file; `grep` across the diff for `CREATE (TABLE|INDEX)|ALTER TABLE` is empty. The keyset predicate
  is served by `Job_pkey`, consistent with the EXPLAIN output in `FIX.md` §4.
- **The CPU-bound-scoring-after-the-fixed-read caveat is real, and the author disclosed it
  honestly** (`FIX.md` §6.3) rather than hiding it. I traced the mitigating factor the author does
  not spell out: each job's write (`update_fit_score`/`clear_fit_score`/`advance_status`,
  `job.py:490-531`) commits on its own short-lived connection *inside the loop*, so if the
  synchronous HTTP request is killed by a gateway/HTTP timeout partway through the 1116-job backlog,
  every job scored before the cutoff is already durably persisted — a timed-out first run degrades to
  "partial progress, retried by the next 30-minute cycle," not to "zero progress," which is a strict
  improvement over the current 100%-failure state. Worth watching post-deploy exactly as the author
  says, but it does not change the SHIP recommendation.
- **A materially larger risk than the task's framing suggests: `GET /jobs` may ALREADY be broken
  the same way, not merely "latent."** The task states "`GET /jobs` currently returns 200 in
  production, so this is latent risk, not an active outage" and asks me to confirm that reading. I
  cannot confirm it, and the evidence points the other way:
  - `apps/api/app/routers/jobs.py:116` calls `JobRepository().list_by_user(current_user["id"],
    status=status, source=source, saved=saved, sort=sort)` — when no `status`/`source`/`saved` filter
    is supplied, this is **the exact same unbounded, 3-correlated-subquery SQL** BLOCKER-007's own
    read-only probe measured as `QueryCanceled` at 5005.9 ms for the **same owner account** with the
    **same 5848-row catalog**, *today* (`probe_prod_readonly.py` step 1, `FIX.md` §1). `sort=` only
    changes `ORDER BY`; it does not reduce the row count or subquery cost.
  - `apps/web/src/app/dashboard/applications/page.tsx:472` calls `apiRequest<Job[]>("/jobs")` with
    **no filters at all**, on every load of the Applications/Pipeline Tracker screen, wrapped in a
    silent `catch { /* pipeline stages are progressive enhancement */ }` (lines 473-475) — so a
    failure here is invisible to the user even though it would still hit `/var/log/aether/api.log`
    as a 500. `git blame` shows this call has existed since `9dd4411d` (2026-07-12) — long deployed,
    not new.
  - I looked for fresh log evidence either way and found none current: the last bare `"GET /jobs
    HTTP/1.1"` in the log is `2026-08-05T07:32:39Z ... 401` (never reached the query — auth
    rejected), and the last *successful* hit is `2026-08-04T10:38:46Z "GET /jobs?sort=fitScore" 200`
    — five days stale relative to today, using the *same* unbounded query, just differently ordered,
    and from before the catalog is confirmed to have reached 5848 rows.
  - **Conclusion:** the honest status of "does `GET /jobs` currently return 200" is **UNKNOWN, not
    confirmed-200** — the mechanism proven broken by this very fix set is present, unfixed, and
    exercised by a long-deployed, silently-swallowing frontend code path. This does not block
    shipping BLOCKER-007 (none of the 6 reviewed commits touch or worsen this path), but the task's
    framing that it is merely "latent" should not be taken at face value; it should be probed live
    immediately after this deploy and treated as its own candidate finding, not filed away as
    low-priority. **[VERIFIED-WITH-FRESH-EVIDENCE that the mechanism and the exposed call site both
    exist; ASSUMED-PENDING-PROBE on whether it is currently 200 or 500 in production today — no log
    evidence either way in the danger window]**

### 1.6 Item 6 — unbounded `list_by_user` call sites left unfixed, confirmed as reported

Confirmed by direct read: `apps/api/app/routers/jobs.py:116`, `apps/api/app/agents/matcher_agent.py:
47` (`self._jobs.list_by_user(user_id, sort="fitScore")`), and
`apps/api/app/agents/salary_intelligence_agent.py:124` (`self._jobs.list_by_user(user_id)`) are
unmodified by any of the six reviewed commits and still call the unbounded board projection. Correct
to leave out of scope for BLOCKER-007 (each needs its own narrow-projection design, not a copy-paste
of the scorer's). Per §1.5 above, I'd upgrade `jobs.py:116`'s urgency from "latent" to "probe this
immediately post-deploy," but that is a follow-up item, not a reason to hold this deploy.

### 1.7 Test-gate / prohibited-pattern check

No `TODO`/`FIXME`, no `@ts-ignore`/`eslint-disable` (N/A, Python), no broad `except:`/bare exception
swallow beyond the pre-existing, disclosed `except Exception as exc: result.errors.append(...)` in
`fit_scorer.py` (unchanged by this diff, and it records the error rather than hiding it), no
`Math.random`/fake data, no hardcoded metrics. Full backend suite evidence
(`blocker007-fullsuite-20260809T075936Z.log`) reads `2720 passed, 1 skipped, 134 warnings in
3996.06s (1:06:36)` / `EXIT=0`, and I confirmed the five changed/added files' mtimes
(`07:00:49Z`/`06:44:08Z`/`06:42:43Z`/`06:44:14Z`/`06:44:17Z`) are all before the run's start
(`07:59:35Z`) — the green run is genuinely on this tree, not a stale log. **[VERIFIED, `stat` +
log read, 2026-08-09]**

---

## 2. ATS-KW-001 — location scored as a required résumé keyword

**Verdict: PASS**

Real root-cause fix: `_extract_keywords` (`apps/api/app/services/ats_engine.py:752`) now strips
`_geographic_tokens(job_description)` before TF-IDF ranking, rather than patching the symptom
downstream (e.g. hand-excluding "sydney" from `missing_keywords`). The "every occurrence must be
inside a geographic span" safety rule (`ats_engine.py:372-463`) is a real, non-trivial disambiguation
mechanism (label lines, a closed carrier-phrase set, chain expansion with a "≥2 confirmed elements"
guard against walking an unrelated comma list) — not a blunt gazetteer strip. Same fix applied at its
second site, `resume_tailor.jd_keyword_terms()` (`apps/api/app/services/resume_tailor.py:36-58`), so
the ATS non-regression floor and the scoring engine agree on what counts as a "skill."

**Weights/thresholds unchanged, confirmed by grep**: `REVIEW_THRESHOLD = 60.0`
(`ats_engine.py:66`), `_MAX_KEYWORDS = 40` (`:73`), `_DEGRADED_SEMANTIC_SCORE = 50.0` (`:63`), and the
`0.4/0.4/0.2` weighting (docstring `:28`) are byte-identical to pre-fix.

**Tests assert the changed behaviour, not incidental passes.** I read
`apps/api/tests/test_ats_kw001_geography_guards.py:1-190` in full: the guard tests specifically
attack the over-match/under-match failure modes a naive gazetteer-strip would hit — a city that is
also a framework name ("Phoenix"/Elixir), a country name that is also a typeface ("Georgia"), an
ambiguous 2-letter abbreviation that is also a product prefix ("MS SQL Server" vs. "SA" in a location
chain), a suburb with zero vocabulary presence recognisable only via chain adjacency, and the
degenerate all-geography case (must not empty the keyword set to avoid a spurious flat 0.0 for every
résumé). These are targeted adversarial cases, not restatements of the implementation. Reran fresh:

```
$ flock -w90 /tmp/aether-pytest.lock scripts/run-tests.sh tests/test_ats_kw001_geography_guards.py \
    tests/test_gm2s15_ats_kw001_location_keyword.py tests/test_ats_engine.py -q
28 passed in 5.94s
```
**[VERIFIED-WITH-FRESH-EVIDENCE, pytest run 2026-08-09]**

No scope creep, no prohibited patterns, no secrets. No migration.

---

## 3. F-02 — job discovery derived from the signed-in user's profile

**Verdict: PASS**

Both halves genuinely close the defect rather than papering over the symptom:
- Frontend (`a090f81`): `apps/web/src/lib/discovery/search-target.ts` "owns no query of its own" —
  `deriveSearchTarget` can only resolve to `ready` (explicit or profile-sourced) or `needs-input`;
  there is no code path back to a hardcoded persona. Both call sites (`dashboard/jobs/page.tsx`,
  `dashboard/agents/page.tsx`) now route through it.
- Backend (`0ce7098`): `apps/api/app/routers/agents.py:1748-195` (`_resolve_scout_target`) is the
  single resolution seam for `/agents/scout/run`, `_pipeline_core`, and the async worker path;
  `_DEFAULT_QUERY`/`_DEFAULT_LOCATION` are deleted outright (not merely unused) at `agents.py:84-95`,
  and `build_scout_query("")` now raises `ValueError` (`query_builder.py:60-68`) instead of quietly
  returning the PM/BA role family — so reintroducing the fabricated persona would require adding a
  literal back, not just wiring an existing one differently. An empty profile gets an honest 422
  (`_missing_search_target_422`, `agents.py:1748-160`), raised *before* `_record_run`, so a refusal
  reserves no quota and leaves no audit row.

**Commit-procedure deviation, verified clean.** `0ce7098` discloses that `agents.py` carried another
session's in-flight CRITICAL-3b work at commit time, and that hunks were staged via
`git apply --cached` rather than `--only`. I checked the current merged file for conflict markers or
foreign content: `grep -n "<<<<<<<\|>>>>>>>\|======="  apps/api/app/routers/agents.py` — none. Both
F-02's `_resolve_scout_target` and CRITICAL-3b's circuit-breaker comments (`agents.py:681`, `:896`,
`:2128`) coexist cleanly, and `git log --oneline` confirms the CRITICAL-3b commits (`90fd15d`,
`267a1a9`) landed as their own separate commits after `0ce7098` — consistent with the disclosed
procedure, not evidence of corruption.

Reran both halves fresh:
```
$ flock -w90 /tmp/aether-pytest.lock scripts/run-tests.sh tests/test_f02_backend_user_scoped_discovery.py -q
14 passed, 11 warnings in 30.81s
$ npx vitest run src/lib/discovery/__tests__/search-target.test.ts \
    src/app/dashboard/agents/__tests__/f02-scout-run-params.test.tsx \
    src/app/dashboard/jobs/__tests__/f02-user-scoped-discovery.test.tsx
Test Files  3 passed (3) / Tests  23 passed (23)
```
**[VERIFIED-WITH-FRESH-EVIDENCE, 2026-08-09]**

Both `catch` blocks I found in the new frontend code (`page.tsx:246`, `applications`-unrelated;
`page.tsx:632`) surface an honest error/needs-input state to the user rather than silently
substituting a guess — consistent with the "no silent fallback" standard.

No migration. No secrets. Two `// eslint-disable-next-line import/first` lines
(`a090f81`, before a `vi.mock`-hoisted import in two test files) — standard vitest mock-ordering
idiom, not a suppressed correctness check; noted, not a defect.

---

## 4. F-03 — résumé-upload story extraction made opt-in

**Verdict: PASS**

`apps/api/app/routers/resumes.py:63-159`: `extract_stories: bool = Form(default=False)` — upload no
longer unconditionally dispatches the metered `storyExtractor` agent (previously: `costUsd 0.0010`,
one Free-plan run silently spent per upload). The response now separately reports
`storyExtractionRequested` and `storyExtraction` (null when not requested) so no client can render
copy claiming a run that never happened. The `except HTTPException: raise` /
`except Exception as exc: extraction = {"error": str(exc)}` split (unchanged logic, just now gated
behind the opt-in) correctly keeps a real API error (e.g. 402 paywall) propagating to the client while
containing a genuine extraction failure as a reported, non-fatal result — not a silent success.

Fail-before evidence for this one is textual (test-file docstring: "Fail-before (at 0ac3e82): tests
1-3 fail") rather than a captured raw pytest failure log the way BLOCKER-007's is — a materially
weaker evidence standard than the other four items, though I found nothing to contradict it: the
pre-fix code path described (unconditional `_dispatch`) matches what the diff actually removes.
Reran both halves fresh:
```
$ flock -w90 /tmp/aether-pytest.lock scripts/run-tests.sh tests/test_f03_upload_silent_quota_spend.py \
    tests/test_resume_upload.py -q
15 passed, 8 warnings in 31.77s
$ npx vitest run src/__tests__/settings/resume-upload-quota-disclosure.test.ts
Test Files  1 passed (1) / Tests  10 passed (10)
```
**[VERIFIED-WITH-FRESH-EVIDENCE, 2026-08-09]**

No migration, no secrets, no scope creep — the story-extractor *capability* is untouched
(`POST /agents/story-extractor/run` still runs the same extraction on demand).

---

## 5. F-04 — self-referential probability factor removed

**Verdict: PASS**

Real fix: the `market_demand_factor` (`sources_total / 50 * 100`, scaling the user's OWN saved-job
count and mislabelled "Market demand") is deleted outright, not down-weighted or renamed
(`apps/api/app/routers/analytics.py:581-650`, factor list rebuilt from `factor_specs`, no
market-demand entry). "Measured iff basis has rows" is now applied uniformly to all three remaining
factors (previously 2 of 4), so an unscored board and a genuine 0 are no longer conflated — a
zero-evidence factor ships `value: null, measured: false` and the composite returns `score: null` +
`unmeasuredReason` rather than a confident 0%. The false "likelihood of landing an offer in the next
60 days" headline is replaced with server-authored copy that explicitly discloses there is no
offer-outcome model (`_PROGRESS_METHODOLOGY`, `analytics.py:264-278`). `MarketPulse.tsx` now renders
`prob.label`/`prob.methodology` from the API instead of a hardcoded tooltip string, so copy cannot
drift from what the server computed.

**Second fake-green instance found (task explicitly asked me to keep hunting) — already self-caught
and fixed by the author, disclosed candidly, not concealed.** Follow-up commit `19d4c65`
(`test(WC-INTERVIEW-SEED-001)`) documents that `test_3_a_genuine_signal_change_still_moves_the_score`
— the ONLY guard in `5f9e775`'s own new test file against satisfying F-04 by freezing the score
against everything — never actually ran: it died in its own arrange step with a Postgres
`UniqueViolation` (`Application_user_job_active_key`, a partial unique index permitting at most one
active-status `Application` row per `(userId, jobId)`) because the original seed inserted a second
active-status row on the same four jobs. The module docstring's claim that "test 3 already passes"
was therefore never observable — an identical class of defect to the one the task told me to hunt for
(BLOCKER-007's substring-`LIMIT` self-catch), just in test *fixture* correctness rather than test
*assertion* correctness. The fix (`_promote_applications`, mirroring production's actual
`move_application` semantics rather than inserting a duplicate row) is correct and I reran it fresh
myself to confirm test 3 now reaches and passes its comparison:
```
$ flock -w90 /tmp/aether-pytest.lock scripts/run-tests.sh tests/test_gm2s15_f04_probability_self_reference.py \
    tests/test_f04_probability_score_honesty.py tests/test_analytics.py -q
23 passed, 7 warnings in 59.21s
```
`test_3_a_genuine_signal_change_still_moves_the_score` is present in that run and green.
**[VERIFIED-WITH-FRESH-EVIDENCE, 2026-08-09]** I flag this as a **positive** signal about this run's
rigor (self-caught and disclosed, not found by an external reviewer) rather than a defect in the
shipped fix — but it is exactly the pattern the task asked me to go hunting for, so it is recorded
here rather than passed over silently.

No migration, no secrets, no scope creep.

---

## Cross-cutting checks

- **Migrations:** none of the six commits touch a migration file or issue DDL (`grep` for
  `CREATE (TABLE|INDEX)|ALTER TABLE|DROP ` across every reviewed diff: no hits outside prose).
  Additive-only requirement: N/A, nothing schema-related shipped.
- **Secrets:** none printed or embedded; `.env`/`DATABASE_URL` reads in the probe scripts stay local
  to the fixer's own evidence tooling and are never echoed into a committed artifact.
- **Provider/billing separation (`/` in model id ⇒ OpenRouter, bare `claude-*` ⇒ direct
  Anthropic):** none of the six commits touch model routing, model selection, or LLM billing code —
  out of scope for this fix set, correctly so.
- **Suppressed errors / weakened tests:** no `xfail`, no `@pytest.mark.skip` added, no loosened
  assertion found in any reviewed diff. Two `eslint-disable-next-line import/first` occurrences are
  benign vitest mock-ordering idiom (§3), not suppressed correctness checks.
- **Ordering/interaction between the six commits:** no dependency conflicts found. F-02's two commits
  are sequential (frontend then backend) and the backend commit explicitly closes an "open residual"
  the frontend commit had documented — consistent staging, not contradiction. The F-02/CRITICAL-3b
  interleaving in `agents.py` is clean (§3). None of the five defect fixes touch the same file as
  another in a way that could conflict; BLOCKER-007 (`job.py`, `fit_scorer.py`) is fully disjoint from
  the other four.

---

## Summary

| id | verdict |
|---|---|
| BLOCKER-007 | PASS |
| ATS-KW-001 | PASS |
| F-02 | PASS |
| F-03 | PASS |
| F-04 | PASS |

**Fake-green findings:** none newly found by this review beyond what the authors already disclosed.
Confirmed the author's own self-caught instance (BLOCKER-007's depth-0 `LIMIT` parsing) is correctly
implemented. Found and confirmed a second, separately-disclosed instance from the same run
(`19d4c65`, F-04's vacuous `test_3`) — already fixed, verified green.

**Deploy risks:**
1. (Disclosed by author, confirmed genuine, self-limiting) BLOCKER-007's read fix does not touch the
   CPU-bound ATS scoring of the ~1116-job unscored backlog; the first post-deploy synchronous run may
   still exceed the HTTP/gateway timeout. Mitigated by per-job commits inside the loop (partial
   progress persists even if the request is killed), so this degrades gracefully rather than
   reproducing the current 100%-failure state — watch, do not block on it.
2. (Found by this review, NOT merely "latent" as the task's framing suggested) `GET /jobs` unfiltered
   (`routers/jobs.py:116`) runs the identical unbounded query mechanism BLOCKER-007 proved broken,
   against the same owner account/catalog size, and is exercised today by a long-deployed, silently-
   swallowing frontend call (`applications/page.tsx:472-475`). No fresh log evidence confirms it is
   currently 200; the last observed hit either didn't reach the query (401) or predates the confirmed
   5848-row catalog size by five days. Recommend probing this live immediately after deploy and
   opening it as its own finding — it is not blocking THIS deploy since none of the six reviewed
   commits touch or worsen it.
3. Negligible: F-04's frontend (`MarketPulse.tsx`) reads new response fields (`prob.methodology`,
   nullable `f.value`) that would be `undefined`/absent against a momentarily-still-old API during a
   non-atomic web/api restart; reviewed and this degrades to old-shaped rendering, not a crash.

**Overall: SHIP.**

BLOCKER-007 fixes a confirmed, currently 100%-failing production endpoint (71/71 failures verified
live in `/var/log/aether/api.log` over the last ~35 hours, zero other active 500 classes in the same
window) with a minimal, correctly-tested, non-destructive change (no migration, no timeout raised, no
scope creep). The other four items are genuine, well-tested defect fixes with no prohibited patterns
found. Nothing in this fix set should be held back.

**Must change before/around this deploy:** nothing blocking. Recommended immediately post-deploy
(not pre-deploy conditions):
- Verify `POST /agents/fit-scorer/run` returns 200 and drains the unscored backlog over the first few
  cycles (risk 1 above).
- Independently probe `GET /jobs` (no filters) against the owner account right after deploy to
  determine whether risk 2 above is already live; if so, file it as its own finding with the same
  urgency class as BLOCKER-007, since the mechanism and the exposure are now both confirmed.

Artifact: `uat/reports/evidence/gold-master-v2/review/UNDEPLOYED-FIXSET-REVIEW.md`
