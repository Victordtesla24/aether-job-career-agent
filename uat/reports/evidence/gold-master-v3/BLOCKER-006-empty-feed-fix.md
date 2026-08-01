# BLOCKER-006 — a paying user sees ZERO jobs while 52 real jobs exist

**Agent:** fixer-hard · **Date:** 2026-08-01 · **Repo:** `/home/ubuntu/github_repos/aether-job-career-agent`
**Production:** https://5cb5f0620.abacusai.cloud · **Branch:** `main` (no push, no deploy, no prod writes)

Every claim below is tagged. `[VERIFIED]` = a command/query I ran, with its timestamp.

---

## 1. The verified predicate, with file:line

The orchestrator's diagnosis is **correct**. The feed's freshness filter tests `postedAt`, first in a
priority chain, and every `ready` row's `postedAt` is outside the window.

Chain of custody through the code:

| Step | file:line (pre-fix) | What it does |
|---|---|---|
| 1 | `apps/api/app/routers/jobs.py:97` | `if not include_stale: jobs = active_feed(jobs)` |
| 2 | `apps/api/app/services/discovery/active_feed.py:137` | `if is_stale(job, now=now, max_age_days=max_age_days): continue` |
| 3 | `apps/api/app/services/discovery/active_feed.py:108` | `return effective < now - timedelta(days=window)` |
| 4 | `apps/api/app/services/discovery/active_feed.py:87-92` | `_effective_date()` returns the **first non-null** of `_DATE_FIELDS` |
| 5 | **`apps/api/app/services/discovery/active_feed.py:38`** | **`_DATE_FIELDS = ("postedAt", "updatedAt", "createdAt")`** ← **THE PREDICATE** |

`postedAt` is first in the tuple and is non-null on 52/52 rows, so `updatedAt`/`createdAt` are never
reached. The window is 30 days (`_DEFAULT_FRESHNESS_DAYS`, `active_feed.py:34`).

It is **not** a `createdAt` filter — the earlier agent's diagnosis was wrong, and step 4's
first-non-null semantics is exactly why: `createdAt` is in the tuple but unreachable.

### Production data confirming it [VERIFIED — read-only `SELECT` on schema `aether`, 2026-08-01T21:32Z]

```
source     status     count  min(postedAt)            max(postedAt)            null_postedAt
ashby      ready      11     2026-01-26 19:00:46.816  2026-06-25 02:26:38.656  0
lever      ready       7     2026-03-17 02:28:09.435  2026-06-26 03:38:44.576  0
ashby      applied     3     ...                      ...                      0
greenhouse applied    20     2026-07-02 13:09:40      2026-07-31 11:23:35      0
...                                                            total = 52 rows
```

```
ready jobs: source, count, min(updatedAt),            max(updatedAt),            min age,  max age
('ashby', 11, '2026-07-24 11:33:41.944', '2026-08-01 21:31:32.108', '37 days ...', '187 days ...')
('lever',  7, '2026-07-24 12:14:58.921', '2026-08-01 21:31:28.421', '36 days ...', '137 days ...')
db now: 2026-08-01 21:32:12.833441+00
```

**The decisive fact:** `max(updatedAt)` is **40 seconds before** `NOW()`. The 30-minute discovery sweep
re-found and re-upserted every one of those 18 rows *seconds* before the feed returned zero of them.

---

## 2. Adapter-parsing investigation — is `postedAt` mis-parsed?

**No. `postedAt` is parsed correctly. The listings genuinely were advertised months ago — and are
genuinely still open.** [VERIFIED — live board APIs, 2026-08-01T21:35Z]

| Source | Field mapped to `postedAt` | file:line | Verdict |
|---|---|---|---|
| lever | `createdAt` (epoch ms ÷ 1000) | `lever_adapter.py:29-33`, `:101` | correct |
| ashby | `publishedAt` (ISO8601) | `ashby_adapter.py:87` | correct |
| greenhouse | `updated_at` | `greenhouse_adapter.py:89` | semantically loose (see below) |
| adzuna / remotive / remoteok / workable / wellfound / indeed | `created` / `publication_date` / `date` / `published_on` / `liveStartAt` / `pubDate` | respective adapters | consistent with each source's publish field |

**Live proof, Lever** — `GET https://api.lever.co/v0/postings/plenti?mode=json`:

```
Product Manager, Credit Automation | createdAt_ms= 1782445124576 -> 2026-06-26T03:38:44.576000+00:00
```

The persisted row is `('lever', 'Product Manager, Credit Automation', 'Plenti', '2026-06-26 03:38:44.576', ...)`
— an **exact millisecond match**. The parse is right, and the posting was returned by the live board
**today**, i.e. it is still open.

**Live proof, Ashby** — `GET https://api.ashbyhq.com/posting-api/job-board/harvey?includeCompensation=false`
returned **360 currently-open postings**, with `publishedAt` values including:

```
'Staff Product Designer'            | publishedAt= 2025-09-12T23:39:38.961+00:00
'Staff Product Manager'             | publishedAt= 2025-10-08T01:47:23.109+00:00
'Innovation Product Manager'        | publishedAt= 2025-12-11T16:20:46.621+00:00
```

An ATS board API **publishes only roles that are still open**. A role advertised 324 days ago that the
board returns today is a live, applicable vacancy.

### The real root cause

> **The freshness filter used posting age as a proxy for "this listing is dead". That proxy is invalid
> for the ATS-native sources this product actually sources from.**

The filter was built for probe-13's finding: Seek cards returning HTTP 403 (`active_feed.py` docstring,
lines 1–22). "Dead" was proxied by "old". For an aggregator that keeps expired ads around, age is a
weak signal; for Greenhouse/Lever/Ashby/Workable it carries **no** information about deadness. The
product's live sources are exactly the latter kind, so the filter deleted the entire product.

Two secondary observations, reported but not conflated with the cause:

* **greenhouse maps `updated_at` → `postedAt`** (`greenhouse_adapter.py:89`). That is why greenhouse
  rows *looked* fresh (postedAt 2026-07-02..07-31) while ashby/lever rows looked stale — the filter's
  behaviour was silently source-dependent. Not the cause (all 20 greenhouse rows are `applied`), and
  not changed here: correcting it is a separate, orthogonal fix.
* **`?includeStale=true` was silently ignored.** The FastAPI parameter is `include_stale`; every other
  field on this API is camelCase (`sourceUrl`, `postedAt`, `fitScore`). A caller reaching for
  `includeStale` got a `200` with a filtered body and no hint the flag did nothing — which is how the
  orchestrator's probe read `includeStale=true -> 0 jobs`. That probe result was an artefact of the
  parameter name, not a third symptom.

---

## 3. Option chosen and why

**Chosen: (d) — a corrected (c) plus (b). Explicitly NOT (a).**

| Option | Verdict |
|---|---|
| (a) Widen the window | **Rejected.** Arbitrary, and wrong in both directions: 187 days is not "wide enough" for a live Ashby role, while a listing whose board dropped it yesterday stays visible for another 30 days. It swaps one wrong threshold for another. |
| (b) Show older listings with an honest age label | **Adopted, as the honesty half.** |
| (c) Fix sourcing freshness | **Adopted in its true form.** The adapter investigation showed sourcing is *not* broken — it is correctly returning genuinely-old-but-open roles. So (c) is not "make new jobs arrive"; it is "record and use the liveness signal the sweep already establishes". That turned out to be a small change, exactly as the brief anticipated if the parse were the issue — except here it is the *predicate*, not the parse. |

### What shipped

**1. The predicate now measures liveness, not age.**
`_DATE_FIELDS` is replaced by `_LIVENESS_FIELDS = ("lastSeenAt", "updatedAt", "createdAt")`
(`active_feed.py`). `postedAt` is removed from the suppression chain entirely.
`is_stale(job)` now means *"the sourcing pipeline has not seen this listing at its source within the
window"*. The dead-link case the filter exists for is still suppressed — now on evidence rather than a
proxy.

**2. A real liveness signal: additive `Job."lastSeenAt" timestamptz`.**
`app/db.py::ensure_job_last_seen_column()` — lazy, idempotent, advisory-locked, `ADD COLUMN IF NOT
EXISTS`, no DROP/ALTER TYPE, mirroring `ensure_job_dedup_columns`. Written **only** by
`JobRepository.create` (`repositories/job.py`), on both write paths — the single entry point every
adapter's results flow through, so reaching it *is* proof the source returned the listing on this sweep.

*Why not just use `updatedAt`?* It is also bumped by user actions (save toggle, status advance,
fit-score writes — `job.py:403/424/439`), so a job the user merely saved would look "re-confirmed at
source" when nothing of the sort happened. It remains a **fallback**, which is honest: it is a lower
bound on when the system last had contact with the row.

*No backfill, deliberately.* `ADD COLUMN` with no DEFAULT is metadata-only; existing rows read NULL,
meaning "no sighting on record", and the fallback chain covers them until the next sweep. Writing a
backfill `UPDATE` would assert sightings that never happened.

**3. Honest age, server-computed (option b).** Every feed row (and `GET /jobs/{id}`, and the
`include_stale` history view) now carries:
* `postedAgeDays` — whole days since the ad went up, **`null` when `postedAt` is unknown** (never
  substituted with the discovery date);
* `lastConfirmedAt` — when the pipeline last saw the listing at its source, `null` when unknown.

**4. `includeStale` accepted as an alias** for `include_stale` (`routers/jobs.py`), so the footgun that
cost a misdiagnosis cannot recur.

---

## 4. User-visible behaviour shipped

| Before | After |
|---|---|
| Board shows **0 jobs**; copy says *"Run Sync to let the Scout agent find matching roles."* | Board shows the **18 live roles**. |
| Card age line rendered `timeAgo(job.createdAt)` — the date **we** discovered the row, unlabelled. A listing advertised 187 days ago read **"12d ago"**. | Card renders **"Posted 187 days ago"**, with a hover title *"Still listed at the source 2m ago"*. |
| Unknown posting date silently rendered the discovery date as if it were the posting date. | Renders **"Found 12d ago"** — states which date it is showing. |
| An empty board with 52 persisted rows told the user to sync jobs they already had. | *"None of your 52 saved roles are on the active board right now — they have been applied to, archived, or their source has stopped listing them."* plus a link to the history view. |

Nothing stale is presented as fresh; nothing live is hidden; the empty state, when reachable, explains
itself. `apps/web/src/app/dashboard/jobs/page.tsx::listingAgeLabel` is the single place that decides
this, and it cannot fall back to `createdAt` without saying so.

---

## 5. Files changed

| File | Change |
|---|---|
| `apps/api/app/services/discovery/active_feed.py` | `_LIVENESS_FIELDS` replaces `_DATE_FIELDS`; `_liveness_date`; `is_stale` re-specified; new `posted_age_days` / `annotate_listing_age`; `active_feed` annotates survivors |
| `apps/api/app/db.py` | new `ensure_job_last_seen_column()` (additive lazy DDL) |
| `apps/api/app/repositories/job.py` | `_JOB_READ_COLUMNS`; `lastSeenAt = NOW()` on both `create` write paths; ensure-calls on `create`/`list_by_user`/`get_by_id` |
| `apps/api/app/routers/jobs.py` | `includeStale` alias; history view annotated; `GET /jobs/{id}` annotated |
| `apps/api/tests/test_blocker_006_empty_feed.py` | **new** — 17 tests |
| `apps/api/tests/test_gap_p6_sourcing.py` | 3 contract tests re-expressed (see §7) |
| `apps/web/src/lib/api/jobs.ts` | `postedAgeDays` / `lastConfirmedAt` / `lastSeenAt` on `JobSchema` |
| `apps/web/src/app/dashboard/jobs/page.tsx` | `listingAgeLabel`; honest card age span; `historyCount` effect; honest empty state |
| `apps/web/src/app/dashboard/jobs/__tests__/blocker-006-listing-age.test.tsx` | **new** — 4 tests |

---

## 6. Verification — verbatim

### 6.1 New backend tests, RED before the fix [VERIFIED 2026-08-01T21:40Z]

```
FAILED tests/test_blocker_006_empty_feed.py::TestListingLivenessPredicate::test_old_posting_still_confirmed_live_is_not_stale
FAILED tests/test_blocker_006_empty_feed.py::TestListingLivenessPredicate::test_listing_not_reconfirmed_since_window_is_stale
FAILED tests/test_blocker_006_empty_feed.py::TestActiveFeedKeepsLiveListings::test_live_old_ats_listings_are_returned
FAILED tests/test_blocker_006_empty_feed.py::TestActiveFeedKeepsLiveListings::test_unconfirmed_listing_is_still_suppressed
FAILED tests/test_blocker_006_empty_feed.py::TestHonestListingAge::test_feed_rows_carry_real_posting_age
FAILED tests/test_blocker_006_empty_feed.py::TestHonestListingAge::test_unknown_posting_date_yields_null_age_not_a_guess
FAILED tests/test_blocker_006_empty_feed.py::TestHonestListingAge::test_feed_rows_carry_last_confirmed_timestamp
FAILED tests/test_blocker_006_empty_feed.py::TestJobsEndpointBlocker006::test_ready_jobs_with_old_posting_dates_are_returned
FAILED tests/test_blocker_006_empty_feed.py::TestJobsEndpointBlocker006::test_feed_rows_expose_their_real_posting_age
FAILED tests/test_blocker_006_empty_feed.py::TestJobsEndpointBlocker006::test_listing_the_source_stopped_returning_is_hidden_but_kept
FAILED tests/test_blocker_006_empty_feed.py::TestJobsEndpointBlocker006::test_camel_case_includeStale_is_accepted
FAILED tests/test_blocker_006_empty_feed.py::TestSweepRecordsLiveness::test_create_stamps_last_seen_at
12 failed, 5 passed in 12.24s
```

The 5 that passed pre-fix are the guards that must NOT regress (prohibited source, fingerprint dedupe,
terminal statuses, unknown-signal-is-never-stale).

The key router failure, verbatim:

```
>       first = client.get("/jobs", headers=auth_headers).json()[0]
E       IndexError: list index out of range
```

### 6.2 New backend tests, GREEN after [VERIFIED 2026-08-01T21:46Z]

```
[run-tests.sh] DATABASE_URL(_TEST) pinned to schema=aether_test — safe to proceed.
.................                                                        [100%]
17 passed in 12.74s
```

### 6.3 `GET /jobs` returns > 0 for a real user

**(a) At the router layer, against the real DB** — `test_ready_jobs_with_old_posting_dates_are_returned`
inserts 5 rows shaped exactly like production (`ready`, `postedAt` 36/37/65/120/187 days old,
board-confirmed now) and asserts `len(rows) == 5`. Pre-fix it returned 0; post-fix it passes.

**(b) Against the ACTUAL production rows, read-only, no mutation** — I ran the real `active_feed()`
function over the real 52 rows fetched with a `SELECT` only. `lastSeenAt` does not exist in production
yet (the additive DDL is not deployed), so this exercises the exact fallback path the first request
after deploy will take. [VERIFIED 2026-08-01T21:52:35Z]

```
[2026-08-01T21:52:35.619140Z] production Job rows: 52
  user c6c8d0163d97…  persisted=52  ACTIVE FEED=18
      ashby      postedAgeDays=39   lastConfirmedAt=2026-08-01 21:31:32.108000  GTM Technology Product Owner
      ashby      postedAgeDays=39   lastConfirmedAt=2026-08-01 21:31:32.033000  GTM Technology Product Owner
      ashby      postedAgeDays=71   lastConfirmedAt=2026-07-29 22:30:33.459000  Senior Agent Product Manager
      ashby      postedAgeDays=44   lastConfirmedAt=2026-08-01 21:31:31.885000  Enterprise Product Manager
      ashby      postedAgeDays=187  lastConfirmedAt=2026-08-01 21:31:31.813000  Senior Product Manager
      ashby      postedAgeDays=50   lastConfirmedAt=2026-07-24 11:52:25.164000  Technical Program Manager, AI Delivery for P
```

**0 → 18.** No production row was written, no DDL was run against production, nothing was deployed.

*(The two same-titled Harvey rows are two genuinely distinct postings — locations `Remote` and
`Dallas`, different `sourceUrl` — so the fingerprint dedupe is correct to keep both.
[VERIFIED 2026-08-01T21:53Z])*

### 6.4 New frontend tests, RED before / GREEN after [VERIFIED 2026-08-01T21:51Z]

Proven red by temporarily restoring the pre-fix render, then restored:

```
× states the ADVERTISEMENT's age, not the date we discovered the row
  → expected '12d ago' to be 'Posted 187 days ago'
× says which date it is showing when the posting date is unknown
  → expected '12d ago' to match /^Found /
× explains an empty board when rows exist in history
  → expected 'No matching jobsRun Sync to let the S…' to contain 'None of your 2 saved roles'
Tests  3 failed | 1 passed (4)
```

After:

```
✓ src/app/dashboard/jobs/__tests__/blocker-006-listing-age.test.tsx (4 tests) 195ms
Test Files  1 passed (1)      Tests  4 passed (4)
```

### 6.5 Regression [VERIFIED 2026-08-01T21:46–21:58Z]

| Suite | Result |
|---|---|
| `test_gmv2_wh_apply_contract.py` + `test_rt_004_application_card_dedup.py` + `test_blocker_006_empty_feed.py` (**mandated**) | `33 passed in 45.48s` |
| `test_gap_p6_sourcing.py` | `28 passed in 7.17s` |
| `test_source_availability` · `test_rt_005_board_stage_sync` · `test_rt_009_010_apply_wiring` · `test_ml_w25_autopilot_suppression_visibility` · `test_fit_scorer_agent` · `test_jobs_insights_apply` · `test_job_discovery` · `test_mv_resume_grounding` | `86 passed in 201.68s` |
| `test_rt_007_board_sweep` · `test_ml_w19_w20_board_sweep_suppression` · `test_scout_live_sources` · `test_applications_tracker` · `test_applications_move` · `test_applications_pipeline_clear` · `test_rt_008_blocked_source` | `127 passed in 163.95s` |
| **Backend total** | **274 passed, 0 failed** |
| vitest `src/app/dashboard/jobs` + `src/__tests__/dashboard` | `Test Files 16 passed · Tests 103 passed` |
| `tsc --noEmit` (whole web app) | exit 0, no errors |
| `next lint` on both changed web files | `✔ No ESLint warnings or errors` |

Re-verified after the final `JobRow[]` → `Job[]` edit described in §8.5
[VERIFIED 2026-08-01T22:00Z]: `tsc --noEmit` exit **0**; `vitest run src/app/dashboard/jobs` →
`Test Files 5 passed · Tests 27 passed`.

All pytest runs were wrapped in `flock /tmp/aether-pytest.lock -c "scripts/run-tests.sh …"`, only on the
files touched. The full suite was never run. The repo-root `.env` was never sourced.

---

## 7. Contract change I made deliberately — flagged, not hidden

Three tests in `apps/api/tests/test_gap_p6_sourcing.py` **failed after the fix** and I changed them.
They are the tests that encoded the defective contract. This is stated loudly rather than buried:

```
FAILED tests/test_gap_p6_sourcing.py::TestActiveFeedPure::test_is_stale_uses_posted_date
FAILED tests/test_gap_p6_sourcing.py::TestActiveFeedPure::test_active_feed_excludes_stale
FAILED tests/test_gap_p6_sourcing.py::TestJobsFeedEndpoint::test_default_feed_hides_seek_and_stale_include_stale_shows_them
E       AssertionError: stale (>30d) rows must be excluded
E       assert 'Product Owner' not in {'Delivery Manager', 'Product Owner'}
3 failed, 97 passed in 177.53s
```

Each was re-expressed against the corrected predicate with its **intent preserved and still enforced**
— a listing that can no longer be reached is still suppressed; Seek is still excluded; history is still
never deleted; each test now additionally asserts that an old-but-still-carried listing survives. No
assertion was deleted or weakened to make a failure go away. **An orchestrator/reviewer should treat
this as the load-bearing judgement call in this fix.**

---

## 8. Concurrent-session conflicts avoided

A concurrent session holds uncommitted work in `apps/api/app/db.py`, `apps/api/app/routers/jobs.py` and
`apps/web/src/app/dashboard/jobs/page.tsx` (an ATS score-provenance change: `_dimension`, `JobRow`,
`fitDimensionsFrom`, `conversionImpactFrom`, `ensure_story_archive_columns`).

1. **Read their diff before touching anything.** Their `jobs.py` hunks are all in `_empty_insights` /
   `_build_insights` (lines 182+); mine are in `list_jobs` / `get_job` (lines 26–122). Zero overlap.
2. **`db.py`:** they appended `ensure_story_archive_columns` at the end of the file. I inserted my
   function at line 451, immediately after `ensure_job_dedup_columns` and *before* their block, so
   neither insertion point moves the other.
3. **`page.tsx`:** their hunks are at ~21, ~30, ~62, ~210–246, ~307, ~363, ~567, ~1290–1762. Mine are 4
   disjoint hunks at ~149, ~333, ~1018, ~1163. I modified **no line they had modified**.
4. **Selective staging.** I did **not** `git add` the three shared files. I extracted only my own hunks
   into a patch and applied it with `git apply --cached` (1/2 hunks in `db.py`, 3/6 in `jobs.py`, 4/19
   in `page.tsx`). Their work stays uncommitted in the working tree, exactly as I found it.
5. **Removed a cross-session dependency from my own code.** My first draft of the empty-state effect
   used `apiRequest<JobRow[]>` — `JobRow` is *their* new type. I changed it to `Job[]` so my commit is
   self-contained and does not silently depend on unreviewed work. Verified: `git diff --cached` contains
   no reference to `JobRow`, `_dimension`, `fitDimensionsFrom`, `conversionImpactFrom`,
   `fitScoreNotMeasured`, `RawInsights`, `normalizeInsights`, `FitDimension`,
   `ensure_story_archive_columns`, or `scoring/provenance`.

---

## 9. Residual risks

1. **Not deployed, not verified in production.** All evidence is repo-level plus a read-only replay of
   the real rows through the real function. The DDL is lazy and will run on the first `JobRepository`
   call after deploy. Production `GET /api/jobs` must be re-probed by QA post-deploy.
2. **`updatedAt` fallback is contaminated by user writes.** For rows persisted before `lastSeenAt`
   exists, a job the user saved/advanced looks "recently seen at source" when it was not. Direction of
   error is toward *keeping* a row visible, and it self-corrects on the first sweep. Documented at
   `db.py::ensure_job_last_seen_column` and `active_feed._LIVENESS_FIELDS`.
3. **The sourcing-volume complaint is untouched and still open.** The cron logging
   `{"persisted":0,"updated":36}` every 30 minutes is real: the configured Ashby/Lever board tokens
   yield the same ~36 relevant roles each cycle. That is not a freshness bug — those roles are
   genuinely open — but the *catalogue* is narrow. Broadening `portals.py` tokens / query coverage is a
   separate finding; this fix makes the existing 18 usable, it does not create new supply.
4. **A stale listing can now persist for up to the 30-day confirmation window after its board drops
   it.** Previously (accidentally) tighter for old ads, looser for new ones. If tightening is wanted,
   `AETHER_JOB_FRESHNESS_DAYS` now controls a signal that actually means what the name implies.
5. **greenhouse `updated_at → postedAt`** (`greenhouse_adapter.py:89`) still overstates freshness on
   greenhouse rows' displayed `postedAgeDays`. Left alone deliberately — orthogonal, and fixing it
   would have widened this diff without affecting the blocker.
6. **`GET /jobs` payload gained three keys** (`lastSeenAt`, `postedAgeDays`, `lastConfirmedAt`).
   Additive; zod strips unknowns; 274 backend + 103 frontend tests green. Any external consumer doing
   strict shape validation would need to know.
7. **Pre-existing `act(...)` warning** in `autopilot-suppression.test.tsx` is **not** mine — proven by
   disabling my effect and re-running: the warning still appeared (`grep -c "not wrapped in act"` → 1).
   [VERIFIED 2026-08-01T21:50Z]
