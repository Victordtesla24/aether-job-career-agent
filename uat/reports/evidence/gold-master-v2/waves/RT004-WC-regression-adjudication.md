# RT-004 / W-C regression adjudication

**Task**: GOLD-MASTER-V2 fixer-medium. This run's own W-C work (commit
`18be1a8`, TailoringLoop / `interview_conversion_rate`) added an
`'interviewed'` key to the canonical application-counts payload returned by
`app/routers/analytics.py::get_application_counts`, which broke
`tests/test_rt_004_application_card_dedup.py::TestCountsCountJobsNotRows::test_canonical_counts_are_per_job`
(strict dict equality). Both contracts are real and both must hold
simultaneously — this is a judgement call, not a mechanical patch.

Owned files for this task: `apps/api/app/routers/analytics.py`,
`apps/api/tests/test_rt_004_application_card_dedup.py` (repo layout note: the
task brief referenced `app/...` / `tests/...`; actual paths are under
`apps/api/`).

## What RT-004 protects

`tests/test_rt_004_application_card_dedup.py` (`TestCountsCountJobsNotRows`
class, docstring lines 1–17) locks the "one board card per job" contract
established after a real production incident (2026-07-24: one Plenti job
displayed as 11 duplicate cards because every cover-letter draft/refine
inserted a new `Application` row, and counts were computed over raw rows
instead of distinct jobs). `test_canonical_counts_are_per_job` specifically
seeds two jobs — `job_a` with 2 "submitted" letter-version rows + 1 "draft"
row (3 rows, 1 job), `job_b` with 1 "draft" row (1 row, 1 job) — and asserts
that `get_application_counts` reports **2 total jobs / 1 submitted job**, not
4 rows / 2 submitted rows. The contract is: *count DISTINCT jobs, never
Application rows*. It was never a contract about the payload's exact key
set — the previous author simply wrote `assert counts == {...}` because at
the time those were the only two keys that existed.

## What W-C needs

`tests/test_wc_interview_conversion_rate.py` (docstring lines 1–20,
`WC-INTERVIEW-SEED-001` comment at lines 43–52) requires `GET
/analytics/conversion` to expose a real `interview_conversion_rate` computed
as interviews-booked ÷ applications-submitted, and is explicit that this MUST
route through the same canonical `get_application_counts()` — specifically
to avoid repeating a previously-shipped divergence bug (Market Pulse's
separate `interview_rate` factor used a raw `COUNT(*)` denominator instead of
the canonical DISTINCT-jobId "submitted" count, producing internally
inconsistent numbers across the app: MV-mobile-dashboard-005, "you 14" vs
"Applied 7"). `get_application_counts`'s own docstring (lines 34–79 of
`analytics.py`) states it is "the single source of truth every CUMULATIVE
'applications' figure across the dashboard ... must derive from" and that
prior attempts to keep a second, divergent counting query in a sibling
endpoint were disproven live. Adding `interviewed` here — computed with the
exact same `COUNT(DISTINCT "jobId") FILTER (...)` discipline as `total` and
`submitted` — is the same distinct-jobId invariant RT-004 protects, extended
to one more stage, not a departure from it.

## Decision: (a) relax the test

**Rejected: (b) move the key.** Sourcing the interview count from a
different, parallel query outside `get_application_counts` would reintroduce
the exact class of bug this function was created to eliminate (divergent
inline "applications" queries producing inconsistent numbers across
surfaces) — the very failure mode `get_application_counts`'s docstring
documents as already having happened once and been fixed. All existing call
sites (`app/routers/applications.py:61`, `analytics.py:114`, `:207`, `:380`,
`:662`) already access this dict **by key** (`["submitted"]`, `["total"]`,
`["interviewed"]`), never by asserting its exact shape — so nothing in
production code is coupled to a 2-key payload. Moving `interviewed` out
would be scope creep with no compensating benefit and a real regression
risk.

**Chosen: relax `test_canonical_counts_are_per_job`** to assert the two keys
it actually protects (`total`, `submitted`) rather than exact dict equality,
so the payload may legitimately grow more DISTINCT-jobId sub-counts without
breaking this guard. This preserves the jobs-not-rows protection exactly —
proven below via the mandatory tamper-test.

## Implementation

`apps/api/tests/test_rt_004_application_card_dedup.py`, `test_canonical_counts_are_per_job`:

```diff
-        # job_a was actually sent (submitted); job_b only drafted.
-        assert counts == {"total": 2, "submitted": 1}
+        # job_a was actually sent (submitted); job_b only drafted. Assert the
+        # jobs-not-rows contract on the keys this test exists to protect —
+        # NOT exact dict-key equality. ...
+        assert counts["total"] == 2, counts
+        assert counts["submitted"] == 1, counts
```

`apps/api/app/routers/analytics.py` — **unchanged** (confirmed
byte-identical to pre-tamper state via `diff` after the tamper-test revert
below).

## Tamper-proof [MANDATORY, performed]

To prove the relaxed assertion still guards the row-vs-job contract (not
just "any 2 keys"), `get_application_counts`'s query was temporarily changed
from `COUNT(DISTINCT "jobId")` to `COUNT(*)` (counting rows, the exact bug
RT-004 exists to catch), and the relaxed test was re-run:

```
$ flock /tmp/aether-pytest.lock -c "scripts/run-tests.sh tests/test_rt_004_application_card_dedup.py::TestCountsCountJobsNotRows::test_canonical_counts_are_per_job -v"
...
>       assert counts["total"] == 2, counts
E       AssertionError: {'total': 4, 'submitted': 2, 'interviewed': 0}
E       assert 4 == 2

tests/test_rt_004_application_card_dedup.py:288: AssertionError
...
=========================== short test summary info ============================
FAILED tests/test_rt_004_application_card_dedup.py::TestCountsCountJobsNotRows::test_canonical_counts_are_per_job
======================== 1 failed, 6 warnings in 2.58s =========================
```

[VERIFIED-WITH-FRESH-EVIDENCE command output above, run 2026-07-31T08:4x UTC]
With row-counting, `total` becomes 4 (all 4 seeded Application rows: 2
submitted + 1 draft on job_a, 1 draft on job_b) and `submitted` becomes 2
(the 2 submitted rows on job_a) instead of 1 (the 1 submitted *job*) — the
relaxed test catches the regression exactly as the strict-equality version
did. The tamper was then reverted:

```
$ diff /tmp/.../analytics.py.orig apps/api/app/routers/analytics.py && echo "IDENTICAL - revert clean"
IDENTICAL - revert clean
```

## Verification — both suites green simultaneously

Single combined run [VERIFIED-WITH-FRESH-EVIDENCE, 2026-07-31T08:51 UTC]:

```
$ flock /tmp/aether-pytest.lock -c "scripts/run-tests.sh tests/test_rt_004_application_card_dedup.py tests/test_wc_interview_conversion_rate.py tests/test_wc_tailoring_loop.py tests/test_wc_tailoring_persistence.py -v"
...
tests/test_rt_004_application_card_dedup.py::TestOneActiveCardPerJob::test_most_advanced_status_wins_over_recency PASSED [  4%]
tests/test_rt_004_application_card_dedup.py::TestOneActiveCardPerJob::test_draft_versions_still_collapse_to_newest PASSED [  9%]
tests/test_rt_004_application_card_dedup.py::TestOneActiveCardPerJob::test_closed_and_active_cards_coexist_deduped PASSED [ 13%]
tests/test_rt_004_application_card_dedup.py::TestPromotionGuards::test_submit_conflicts_when_job_already_applied PASSED [ 18%]
tests/test_rt_004_application_card_dedup.py::TestPromotionGuards::test_move_draft_conflicts_when_job_already_applied PASSED [ 22%]
tests/test_rt_004_application_card_dedup.py::TestPromotionGuards::test_moving_the_active_card_between_stages_still_works PASSED [ 27%]
tests/test_rt_004_application_card_dedup.py::TestPromotionGuards::test_promoting_the_only_draft_still_works PASSED [ 31%]
tests/test_rt_004_application_card_dedup.py::TestCountsCountJobsNotRows::test_funnel_sankey_counts_distinct_jobs PASSED [ 36%]
tests/test_rt_004_application_card_dedup.py::TestCountsCountJobsNotRows::test_canonical_counts_are_per_job PASSED [ 40%]
tests/test_wc_interview_conversion_rate.py::TestInterviewConversionRate::test_interview_conversion_rate_is_a_real_computation_not_a_placeholder PASSED [ 45%]
tests/test_wc_interview_conversion_rate.py::TestInterviewConversionRate::test_interview_conversion_rate_denominator_is_distinct_submitted_jobs PASSED [ 50%]
tests/test_wc_interview_conversion_rate.py::TestInterviewConversionRate::test_interview_conversion_rate_zero_when_no_interviews_yet PASSED [ 54%]
tests/test_wc_interview_conversion_rate.py::TestInterviewConversionRate::test_interview_conversion_rate_green_threshold_is_one_in_five PASSED [ 59%]
tests/test_wc_tailoring_loop.py::test_loop_uses_discovered_default_of_five_and_stops_once_target_reached PASSED [ 63%]
tests/test_wc_tailoring_loop.py::test_clean_gap_keywords_strips_tokenization_noise PASSED [ 68%]
tests/test_wc_tailoring_loop.py::test_loop_embeds_clean_gap_keywords_directive_into_next_iteration PASSED [ 72%]
tests/test_wc_tailoring_loop.py::test_loop_exits_immediately_once_target_score_is_met PASSED [ 77%]
tests/test_wc_tailoring_loop.py::test_loop_stops_at_max_iterations_when_score_never_reaches_target PASSED [ 81%]
tests/test_wc_tailoring_loop.py::test_loop_surfaces_honest_warning_with_best_achieved_score_when_capped_out PASSED [ 86%]
tests/test_wc_tailoring_loop.py::test_loop_never_lets_a_fabricated_keyword_close_the_gap PASSED [ 90%]
tests/test_wc_tailoring_persistence.py::TestTailoringLoopPersistence::test_tailored_resume_persists_per_iteration_history PASSED [ 95%]
tests/test_wc_tailoring_persistence.py::TestTailoringLoopPersistence::test_tailor_run_never_claims_success_below_the_85_target PASSED [100%]
======================= 22 passed, 6 warnings in 36.04s ========================
```

RT-004: **9/9 green**. W-C suites (`test_wc_interview_conversion_rate.py` 4 +
`test_wc_tailoring_loop.py` 7 + `test_wc_tailoring_persistence.py` 2):
**13/13 green**. Total 22/22, both contracts hold simultaneously.

### Fail-before baseline (pre-fix, for record)

```
$ flock /tmp/aether-pytest.lock -c "scripts/run-tests.sh tests/test_rt_004_application_card_dedup.py -v"
...
>       assert counts == {"total": 2, "submitted": 1}
E       AssertionError: assert {'total': 2, ...terviewed': 0} == {'total': 2, 'submitted': 1}
...
=================== 1 failed, 8 passed, 6 warnings in 17.15s ===================
```
[VERIFIED-WITH-FRESH-EVIDENCE, 2026-07-31T08:4x UTC] — matches the reported
regression exactly (1 failed / 8 passed in that file).

## Residual risks

- `analytics.py`'s docstring (lines 76–79) already flags a **known,
  pre-existing, out-of-scope** divergence: Market Pulse's separate
  "Interview conversion" probability factor still computes its own
  `interview_rate` from a raw `COUNT(*)` denominator, not
  `get_application_counts`. That divergence predates this fix, is explicitly
  out of scope for RT-004/W-C, and is not touched here — flagging it again
  so it isn't lost.
- The relaxed assertion checks `total` and `submitted` explicitly but does
  not also pin `interviewed == 0` in this specific test (the seed data has
  no interview-stage rows, so it would trivially be 0). This is intentional:
  pinning it here would re-introduce exact-shape coupling between an
  unrelated feature (W-C's interview metric) and RT-004's job-not-rows
  guard, the opposite of the fix. `interviewed`'s correctness is covered by
  `test_wc_interview_conversion_rate.py` instead.
- No DB schema change was needed or made; no migration required.

## Commit

`fix(ML-RT004-WC): relax RT-004 canonical-counts assertion to key-level, preserving jobs-not-rows guard`
