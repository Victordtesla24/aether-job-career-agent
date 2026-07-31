# GOLD-MASTER-V2 §15 — raw-count-vs-canonical-job divergence CLASS closure

**Scope**: `apps/api/app/routers/analytics.py` (repo path; the prompt's `app/routers/analytics.py`
resolves here — this repo's FastAPI backend lives under `apps/api/`).

**Prior state**: commit `ad0b3a0` fixed ONE instance — `market_pulse()`'s "Interview conversion"
probability factor — to use the canonical `get_application_counts()` (`DISTINCT "jobId"`) instead of a
raw `COUNT(*) FROM "Application"`. That helper's own docstring already flagged that this was one
instance of a broader class: **one job can carry MANY `Application` rows** (each cover-letter
draft/refine inserts a new row — the studio's version history), so a raw row-count inflates any
"applications" figure against the true per-job figure. Live production evidence backing this run
(`app/db.py::ensure_application_unique_active_index` docstring, 2026-07-29 probe): **2 `(userId,
jobId)` pairs in production already carry 21 extra rows total** beyond the one-active-row-per-job
invariant — i.e. a real job can, today, contribute more than one row to a raw `COUNT(*)` even for
"active" statuses (submitted/screening/interview/offer), not just draft churn.

This task closes the class: 4 more raw-`COUNT(*)`-on-`Application` sites were found by grep. Each was
judged individually rather than blanket-converted.

## Per-site table

| Site | What the number means to the user | Per-job or per-row correct? | Changed or left | Justification |
|---|---|---|---|---|
| `funnel()` — `screened`/`interviewed`/`offers` (~lines 117-139) | Application-funnel stage counts: "how many of my **opportunities** reached screening / interview / offer". | **Per-job.** A funnel counts opportunities pursued, not letter-version rows. | **CHANGED.** `interviewed` now reuses `get_application_counts()["interviewed"]` (no new inline query). `screened`/`offers` have no canonical helper key (§15 forbids modifying `get_application_counts()` itself), so they're computed inline with `COUNT(DISTINCT "jobId") FILTER (...)` — same discipline, no duplicated counting logic added to the helper. | A user has ONE application to a job, however many draft/re-tailored letter-version rows or (per the live evidence above) duplicate active-status rows it carries. Raw `COUNT(*) FILTER` previously double-counted a job with e.g. two `'offer'` rows as 2 screened/interviewed/offers instead of 1 real opportunity — the exact defect class MV-mobile-dashboard-005 was about, just at a different call site. |
| `market_pulse()` heatmap — "Weekly Activity" (~line 355-366, `activityHeatmap`) | A GitHub-style intensity grid (`title="Week N, day M: intensity V"`, legend "less…more") labelled **"Weekly Activity"**, not "Applications" or "Jobs Applied". | **Per-row.** This is a system/user-activity intensity signal, not an opportunity count. | **LEFT AS-IS.** Raw `COUNT(*)` per day retained. | Every `Application` row *is* a real action (a draft created, a letter re-tailored, a submission) — that IS what "activity" means. A user who re-tailors one job's cover letter 3 times in a day genuinely did 3 things that day; showing that as higher-intensity than a day spent touching 3 different jobs once each is correct for an *activity* signal, not a defect. The label deliberately says "Activity", never "applications" or "jobs" — converting this to `DISTINCT "jobId"` would be the *inverse* mistake the task prompt warned against (turning a legitimate event count into an artificially job-scoped one), and would actually make the heatmap under-report real user/system activity on multi-draft days. |
| `market_pulse()` `app_week_rows` → "Your application velocity" trend indicator (~lines 438-454) | A trend-indicator tile explicitly labelled **"Your application velocity"** — the rate at which the user is *applying*. | **Per-job.** The label narrows to "application(s)", the same concept the platform-wide data-consistency ruling (`get_application_counts()` docstring) already governs for every other "applications" surface. | **CHANGED.** `COUNT(*)` → `COUNT(DISTINCT "jobId")`, all statuses retained unfiltered (that total-vs-submitted question is a separate, already-settled axis and out of this fix's scope — no scope creep). | This SAME `market-pulse` response already shows a canonical, `get_application_counts()`-derived "Applications / month" figure in `marketVsYou`. Before this fix, "Your application velocity"'s underlying series used a raw, un-deduplicated `COUNT(*)` — so a job re-tailored/re-drafted several times in one week inflated *that* trend's shape and %-delta while the *other* "applications" figure on the identical page stayed honest — two divergent "applications pace" numbers on one screen, precisely the anti-pattern this class-closure exists to eliminate. |
| `_dashboard()` — `interviews`/`offers` (~lines 658-695) | The dashboard-summary card. `totalApplications` on this SAME card is already canonical (`get_application_counts()["total"]`); `interviews`/`offers` sit right next to it. | **Per-job.** Same card, same "applications" concept, must not diverge from its own sibling field. | **CHANGED (most user-visible).** `interviews` now reuses `get_application_counts()["interviewed"]`. `offers` has no canonical helper key, so it's computed inline with `COUNT(DISTINCT "jobId") FILTER (WHERE status = 'offer')`. | Before this fix, `totalApplications` (canonical, per-job) and `interviews`/`offers` (raw, per-row) could be internally inconsistent on the exact same card a user is looking at right now — e.g. a job with 2 duplicate `'offer'` rows (live-evidenced shape) showed `offers: 2` next to a correctly-deduplicated `totalApplications`. This is the single most user-visible instance of the class per the task brief. |

## Failing tests written first (fail-before verbatim)

New file: `apps/api/tests/test_gm_v2_raw_count_class_closure.py` (3 tests, one per changed site — the
heatmap site has no test since it was deliberately left unchanged).

Run at `2026-07-31T09:13:58Z`, **before** any production-code edit:

```
tests/test_gm_v2_raw_count_class_closure.py::TestFunnelScreenedInterviewedOffersCountJobsNotRows::test_funnel_screened_interviewed_offers_are_distinct_job_counts FAILED
tests/test_gm_v2_raw_count_class_closure.py::TestMarketPulseApplicationVelocityCountsJobsNotRows::test_application_velocity_trend_counts_distinct_jobs_per_week FAILED
tests/test_gm_v2_raw_count_class_closure.py::TestDashboardInterviewsOffersCountJobsNotRows::test_dashboard_interviews_and_offers_are_distinct_job_counts FAILED
...
> assert data["screened"] == 1, data
E   AssertionError: {'period': 'all', 'jobs_found': 5, 'applied': 5, 'screened': 2, ...}
E   assert 2 == 1
...
> assert velocity["series"][-1] == 5, velocity
E   AssertionError: {'label': 'Your application velocity', 'delta': 'no change', 'direction': 'flat', 'series': [7.0]}
E   assert 7.0 == 5
...
> assert data["interviews"] == 1, data
E   AssertionError: {'totalApplications': 5, 'interviews': 2, 'offers': 2, 'jobsFound': 5, ...}
E   assert 2 == 1
======================== 3 failed, 6 warnings in 7.40s =========================
```

Each seeded a job with MULTIPLE `Application` rows (2× `'offer'`, or 3× `'draft'`) plus 4 single-row
jobs — exactly the shape that makes raw-row and canonical-job counts diverge — and each failure shows
the pre-fix code returning the raw (inflated) figure.

## Fix

`get_application_counts()` itself was **not modified** (RT-004 9/9 and W-C 13/13 depend on it exactly
as it is). Where an existing canonical key already matched the needed semantics
(`interviewed`), call sites now **reuse** it instead of a divergent inline query. Where no key exists
(`screened`, `offers` — a stage between submitted/interviewed, and an offer-only count respectively),
the fix writes a new inline query using the SAME `COUNT(DISTINCT "jobId")` discipline, not a duplicate
of the helper's logic.

## Pass-after verbatim

Run at `2026-07-31T09:14:37Z`, immediately after the fix, same 3 tests:

```
tests/test_gm_v2_raw_count_class_closure.py::TestFunnelScreenedInterviewedOffersCountJobsNotRows::test_funnel_screened_interviewed_offers_are_distinct_job_counts PASSED
tests/test_gm_v2_raw_count_class_closure.py::TestMarketPulseApplicationVelocityCountsJobsNotRows::test_application_velocity_trend_counts_distinct_jobs_per_week PASSED
tests/test_gm_v2_raw_count_class_closure.py::TestDashboardInterviewsOffersCountJobsNotRows::test_dashboard_interviews_and_offers_are_distinct_job_counts PASSED
======================== 3 passed, 6 warnings in 6.95s =========================
```

## Regression sweep (verbatim)

Run at `2026-07-31T09:14:49Z`, all required files in one invocation:

```
$ flock /tmp/aether-pytest.lock -c "scripts/run-tests.sh \
    tests/test_market_pulse_interview_count_divergence.py \
    tests/test_rt_004_application_card_dedup.py \
    tests/test_wc_interview_conversion_rate.py \
    tests/test_wc_tailoring_loop.py \
    tests/test_wc_tailoring_persistence.py \
    tests/test_analytics.py \
    tests/test_gm_v2_raw_count_class_closure.py -v"

collecting ... collected 37 items

tests/test_market_pulse_interview_count_divergence.py::TestMarketPulseInterviewCountDivergence::test_market_pulse_interview_conversion_matches_canonical_distinct_job_count PASSED [  2%]
tests/test_rt_004_application_card_dedup.py::TestOneActiveCardPerJob::test_most_advanced_status_wins_over_recency PASSED [  5%]
tests/test_rt_004_application_card_dedup.py::TestOneActiveCardPerJob::test_draft_versions_still_collapse_to_newest PASSED [  8%]
tests/test_rt_004_application_card_dedup.py::TestOneActiveCardPerJob::test_closed_and_active_cards_coexist_deduped PASSED [ 10%]
tests/test_rt_004_application_card_dedup.py::TestPromotionGuards::test_submit_conflicts_when_job_already_applied PASSED [ 13%]
tests/test_rt_004_application_card_dedup.py::TestPromotionGuards::test_move_draft_conflicts_when_job_already_applied PASSED [ 16%]
tests/test_rt_004_application_card_dedup.py::TestPromotionGuards::test_moving_the_active_card_between_stages_still_works PASSED [ 18%]
tests/test_rt_004_application_card_dedup.py::TestPromotionGuards::test_promoting_the_only_draft_still_works PASSED [ 21%]
tests/test_rt_004_application_card_dedup.py::TestCountsCountJobsNotRows::test_funnel_sankey_counts_distinct_jobs PASSED [ 24%]
tests/test_rt_004_application_card_dedup.py::TestCountsCountJobsNotRows::test_canonical_counts_are_per_job PASSED [ 27%]
tests/test_wc_interview_conversion_rate.py::TestInterviewConversionRate::test_interview_conversion_rate_is_a_real_computation_not_a_placeholder PASSED [ 29%]
tests/test_wc_interview_conversion_rate.py::TestInterviewConversionRate::test_interview_conversion_rate_denominator_is_distinct_submitted_jobs PASSED [ 32%]
tests/test_wc_interview_conversion_rate.py::TestInterviewConversionRate::test_interview_conversion_rate_zero_when_no_interviews_yet PASSED [ 35%]
tests/test_wc_interview_conversion_rate.py::TestInterviewConversionRate::test_interview_conversion_rate_green_threshold_is_one_in_five PASSED [ 37%]
tests/test_wc_tailoring_loop.py::test_loop_uses_discovered_default_of_five_and_stops_once_target_reached PASSED [ 40%]
tests/test_wc_tailoring_loop.py::test_clean_gap_keywords_strips_tokenization_noise PASSED [ 43%]
tests/test_wc_tailoring_loop.py::test_loop_embeds_clean_gap_keywords_directive_into_next_iteration PASSED [ 45%]
tests/test_wc_tailoring_loop.py::test_loop_exits_immediately_once_target_score_is_met PASSED [ 48%]
tests/test_wc_tailoring_loop.py::test_loop_stops_at_max_iterations_when_score_never_reaches_target PASSED [ 51%]
tests/test_wc_tailoring_loop.py::test_loop_surfaces_honest_warning_with_best_achieved_score_when_capped_out PASSED [ 54%]
tests/test_wc_tailoring_loop.py::test_loop_never_lets_a_fabricated_keyword_close_the_gap PASSED [ 56%]
tests/test_wc_tailoring_persistence.py::TestTailoringLoopPersistence::test_tailored_resume_persists_per_iteration_history PASSED [ 59%]
tests/test_wc_tailoring_persistence.py::TestTailoringLoopPersistence::test_tailor_run_never_claims_success_below_the_85_target PASSED [ 62%]
tests/test_analytics.py::TestAnalytics::test_funnel_aggregates_match_seeded_data PASSED [ 64%]
tests/test_analytics.py::TestAnalytics::test_time_period_filter_works PASSED [ 67%]
tests/test_analytics.py::TestAnalytics::test_agent_roi_includes_cost_and_time PASSED [ 70%]
tests/test_analytics.py::TestAnalytics::test_ats_distribution_histogram PASSED [ 72%]
tests/test_analytics.py::TestAnalytics::test_probability_counts_measured_zero_conversion PASSED [ 75%]
tests/test_analytics.py::TestAnalytics::test_source_donut_colors_are_unique PASSED [ 78%]
tests/test_analytics.py::TestAnalytics::test_conversion_rates PASSED     [ 81%]
tests/test_analytics.py::TestAnalytics::test_sources_donut_label_is_not_mislabeled_as_applications PASSED [ 83%]
tests/test_analytics.py::TestAnalytics::test_avg_runs_per_week_divides_by_12_week_window PASSED [ 86%]
tests/test_analytics.py::TestAnalytics::test_market_vs_you_does_not_fabricate_market_benchmark PASSED [ 89%]
tests/test_analytics.py::TestAnalytics::test_applications_total_consistent_across_dashboard_funnel_market_pulse PASSED [ 91%]
tests/test_gm_v2_raw_count_class_closure.py::TestFunnelScreenedInterviewedOffersCountJobsNotRows::test_funnel_screened_interviewed_offers_are_distinct_job_counts PASSED [ 94%]
tests/test_gm_v2_raw_count_class_closure.py::TestMarketPulseApplicationVelocityCountsJobsNotRows::test_application_velocity_trend_counts_distinct_jobs_per_week PASSED [ 97%]
tests/test_gm_v2_raw_count_class_closure.py::TestDashboardInterviewsOffersCountJobsNotRows::test_dashboard_interviews_and_offers_are_distinct_job_counts PASSED [100%]

================== 37 passed, 7 warnings in 64.84s (0:01:04) ===================
```

**Note on `test_analytics.py` count**: the task brief expected "10/10"; the file as it currently exists
on this branch collects **11** tests, and all 11 pass. Reported honestly rather than adjusted to match
the expected number — no test was skipped, hidden, or altered to produce this count; `pytest
--collect-only` and the run above both show 11.

**0 regressions.** `test_wc_tailoring_loop.py` / `test_wc_tailoring_persistence.py` do not touch
`analytics.py` at all (verified by grep before starting) and passed as an unaffected control.

## Final grep — raw `COUNT(*) FROM "Application"` survivors

```
$ grep -n 'FROM "Application"' apps/api/app/routers/analytics.py
90:        FROM "Application" WHERE "userId" = %s{period_clause}                      <- get_application_counts() — already COUNT(DISTINCT "jobId"), untouched (canonical helper)
135:                FROM "Application" WHERE "userId" = %s{job_filter}                <- funnel() screened/offers — NOW COUNT(DISTINCT "jobId") FILTER(...)
366:                'SELECT DATE("createdAt") AS day, COUNT(*) AS cnt FROM "Application" '   <- market_pulse() heatmap — raw COUNT(*), LEFT AS-IS (justified above)
406:                'FROM "Application" a JOIN "Job" j ON a."jobId" = j.id '           <- employer-activity feed, a row LISTING (ORDER BY ... LIMIT 5), not a count at all
460:                'FROM "Application" WHERE "userId" = %s '                         <- market_pulse() app_week_rows — NOW COUNT(DISTINCT "jobId")
694:                f'''SELECT COUNT(DISTINCT "jobId") FROM "Application"             <- _dashboard() offers — NOW COUNT(DISTINCT "jobId")
```

**One raw `COUNT(*) FROM "Application"` survives**: the `market_pulse()` "Weekly Activity" heatmap at
line 366. It is justified above (per-row activity-intensity signal, not an "applications"/"opportunity"
figure) — leaving it unchanged is a deliberate, reasoned decision per the task brief's instruction that
getting this judgment call wrong in the other direction (turning a legitimate event count into a job
count) is just as bad as the original defect.

## Commit

`fix(analytics): close raw Application row-count divergence class (GOLD-MASTER-V2 §15)` —
touches only `apps/api/app/routers/analytics.py` (production fix) and
`apps/api/tests/test_gm_v2_raw_count_class_closure.py` (new tests). No DB migration required (no schema
change). Not pushed.
