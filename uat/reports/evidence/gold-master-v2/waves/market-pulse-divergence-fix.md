# GAP-market-pulse-interview-count-divergence — fix report

Repo: `/home/ubuntu/github_repos/aether-job-career-agent`
File changed: `apps/api/app/routers/analytics.py`
New test file: `apps/api/tests/test_market_pulse_interview_count_divergence.py`
Timestamp of this run: 2026-07-31T09:06:02Z (America/UTC), all commands run from repo root under `flock /tmp/aether-pytest.lock`.

## 1. The defect

`GET /analytics/market-pulse` (`market_pulse()` in `analytics.py`) computed its "Interview
conversion" probability factor (and the `marketVsYou` "Interview rate" comparison, which reuses
the same `interview_rate` variable) from a raw `COUNT(*) FROM "Application"` query
(pre-fix lines 362-372), instead of the canonical `get_application_counts()` helper
(`DISTINCT "jobId"`) that every other cumulative "applications" figure on the platform must use
per that function's own docstring (data-consistency ruling MV-dashboard-001 et al.). One job can
carry many `Application` rows (draft / re-tailored cover-letter versions), so the raw row-count
diverges from the canonical per-job count whenever a job has more than one row. This is
user-visible because `apps/web/src/app/dashboard/analytics/page.tsx` renders both the canonical
conversion rate and `<MarketPulse />` on the same page — a user could see two different interview
figures side by side.

The function's own docstring already named this exact divergence and marked it "out of scope" —
this fix closes that gap.

## 2. Reproduction — failing test BEFORE the fix

Test: `tests/test_market_pulse_interview_count_divergence.py::TestMarketPulseInterviewCountDivergence::test_market_pulse_interview_conversion_matches_canonical_distinct_job_count`

Seed data: 1 job with 3 `Application` rows (`draft`, `draft`, `interview` — simulating 2
re-tailored letter-version drafts plus the row that reached interview) + 4 jobs with 1
`submitted` row each.

- Canonical (`get_application_counts`): `total=5` distinct jobs, `interviewed=1` distinct job →
  `round(1/5*100) = 20`.
- Pre-fix raw `COUNT(*)`: `7` raw Application rows, `1` raw interview row →
  `round(1/7*100) = 14`.

Command (run BEFORE the fix was applied, from repo root):

```
flock /tmp/aether-pytest.lock -c "scripts/run-tests.sh tests/test_market_pulse_interview_count_divergence.py -v"
```

Verbatim result (failed for the right reason — `14 != 20`, an assertion on the actual computed
values, not a collection/import error):

```
tests/test_market_pulse_interview_count_divergence.py::TestMarketPulseInterviewCountDivergence::test_market_pulse_interview_conversion_matches_canonical_distinct_job_count FAILED [100%]

...
>       assert factors["Interview conversion"] == canonical_interview_rate, (
E       AssertionError: Market Pulse 'Interview conversion' factor (14) diverges from the canonical get_application_counts()-derived figure (20) for the SAME data set — raw COUNT(*) inflates/deflates against jobs with multiple Application (letter-version) rows.
E       assert 14 == 20

tests/test_market_pulse_interview_count_divergence.py:130: AssertionError
========================== 1 failed, 6 warnings in 2.82s ===========================
```

[VERIFIED-WITH-FRESH-EVIDENCE — command output above, captured this run before any code edit]

## 3. The fix

`apps/api/app/routers/analytics.py`, inside `market_pulse()` — replaced the raw `COUNT(*)` query
with a call to the canonical `get_application_counts()`, mirroring the existing `f_last_month`
call 20 lines below it:

```diff
             # --- Funnel counts for probability + market-vs-you -------------
-            cur.execute(
-                '''
-                SELECT
-                    COUNT(*) AS total,
-                    COUNT(*) FILTER (WHERE "status" IN ('interview','offer')) AS interviews,
-                    COUNT(*) FILTER (WHERE "status" = 'offer') AS offers
-                FROM "Application" WHERE "userId" = %s
-                ''',
-                (user_id,),
-            )
-            f_total, f_interviews, _f_offers = cur.fetchone()
+            pulse_counts = get_application_counts(cur, user_id)
+            f_total, f_interviews = pulse_counts["total"], pulse_counts["interviewed"]
```

(plus explanatory comments — see `git diff` for the full context). `get_application_counts()`
itself was NOT modified — its `total`/`submitted`/`interviewed` computation and return shape are
byte-for-byte unchanged, so every other caller (`funnel()`, `conversion()`, `_dashboard()`) is
unaffected. Also updated the stale docstring paragraph inside `get_application_counts()` that
called this divergence "out of scope" (now says it's fixed), since leaving that comment as-is
would have been actively misleading post-fix.

No DB schema change was needed — this is a pure query-logic fix, no DDL.

## 4. Verify — verbatim output AFTER the fix

Single combined run, from repo root, under the required flock:

```
flock /tmp/aether-pytest.lock -c "scripts/run-tests.sh tests/test_rt_004_application_card_dedup.py tests/test_wc_interview_conversion_rate.py tests/test_wc_tailoring_loop.py tests/test_wc_tailoring_persistence.py tests/test_analytics.py tests/test_market_pulse_interview_count_divergence.py -v"
```

```
tests/test_rt_004_application_card_dedup.py::TestOneActiveCardPerJob::test_most_advanced_status_wins_over_recency PASSED [  2%]
tests/test_rt_004_application_card_dedup.py::TestOneActiveCardPerJob::test_draft_versions_still_collapse_to_newest PASSED [  5%]
tests/test_rt_004_application_card_dedup.py::TestOneActiveCardPerJob::test_closed_and_active_cards_coexist_deduped PASSED [  8%]
tests/test_rt_004_application_card_dedup.py::TestPromotionGuards::test_submit_conflicts_when_job_already_applied PASSED [ 11%]
tests/test_rt_004_application_card_dedup.py::TestPromotionGuards::test_move_draft_conflicts_when_job_already_applied PASSED [ 14%]
tests/test_rt_004_application_card_dedup.py::TestPromotionGuards::test_moving_the_active_card_between_stages_still_works PASSED [ 17%]
tests/test_rt_004_application_card_dedup.py::TestPromotionGuards::test_promoting_the_only_draft_still_works PASSED [ 20%]
tests/test_rt_004_application_card_dedup.py::TestCountsCountJobsNotRows::test_funnel_sankey_counts_distinct_jobs PASSED [ 23%]
tests/test_rt_004_application_card_dedup.py::TestCountsCountJobsNotRows::test_canonical_counts_are_per_job PASSED [ 26%]
tests/test_wc_interview_conversion_rate.py::TestInterviewConversionRate::test_interview_conversion_rate_is_a_real_computation_not_a_placeholder PASSED [ 29%]
tests/test_wc_interview_conversion_rate.py::TestInterviewConversionRate::test_interview_conversion_rate_denominator_is_distinct_submitted_jobs PASSED [ 32%]
tests/test_wc_interview_conversion_rate.py::TestInterviewConversionRate::test_interview_conversion_rate_zero_when_no_interviews_yet PASSED [ 35%]
tests/test_wc_interview_conversion_rate.py::TestInterviewConversionRate::test_interview_conversion_rate_green_threshold_is_one_in_five PASSED [ 38%]
tests/test_wc_tailoring_loop.py::test_loop_uses_discovered_default_of_five_and_stops_once_target_reached PASSED [ 41%]
tests/test_wc_tailoring_loop.py::test_clean_gap_keywords_strips_tokenization_noise PASSED [ 44%]
tests/test_wc_tailoring_loop.py::test_loop_embeds_clean_gap_keywords_directive_into_next_iteration PASSED [ 47%]
tests/test_wc_tailoring_loop.py::test_loop_exits_immediately_once_target_score_is_met PASSED [ 50%]
tests/test_wc_tailoring_loop.py::test_loop_stops_at_max_iterations_when_score_never_reaches_target PASSED [ 52%]
tests/test_wc_tailoring_loop.py::test_loop_surfaces_honest_warning_with_best_achieved_score_when_capped_out PASSED [ 55%]
tests/test_wc_tailoring_loop.py::test_loop_never_lets_a_fabricated_keyword_close_the_gap PASSED [ 58%]
tests/test_wc_tailoring_persistence.py::TestTailoringLoopPersistence::test_tailored_resume_persists_per_iteration_history PASSED [ 61%]
tests/test_wc_tailoring_persistence.py::TestTailoringLoopPersistence::test_tailor_run_never_claims_success_below_the_85_target PASSED [ 64%]
tests/test_analytics.py::TestAnalytics::test_funnel_aggregates_match_seeded_data PASSED [ 67%]
tests/test_analytics.py::TestAnalytics::test_time_period_filter_works PASSED [ 70%]
tests/test_analytics.py::TestAnalytics::test_agent_roi_includes_cost_and_time PASSED [ 73%]
tests/test_analytics.py::TestAnalytics::test_ats_distribution_histogram PASSED [ 76%]
tests/test_analytics.py::TestAnalytics::test_probability_counts_measured_zero_conversion PASSED [ 79%]
tests/test_analytics.py::TestAnalytics::test_source_donut_colors_are_unique PASSED [ 82%]
tests/test_analytics.py::TestAnalytics::test_conversion_rates PASSED     [ 85%]
tests/test_analytics.py::TestAnalytics::test_sources_donut_label_is_not_mislabeled_as_applications PASSED [ 88%]
tests/test_analytics.py::TestAnalytics::test_avg_runs_per_week_divides_by_12_week_window PASSED [ 91%]
tests/test_analytics.py::TestAnalytics::test_market_vs_you_does_not_fabricate_market_benchmark PASSED [ 94%]
tests/test_analytics.py::TestAnalytics::test_applications_total_consistent_across_dashboard_funnel_market_pulse PASSED [ 97%]
tests/test_market_pulse_interview_count_divergence.py::TestMarketPulseInterviewCountDivergence::test_market_pulse_interview_conversion_matches_canonical_distinct_job_count PASSED [100%]

================== 34 passed, 7 warnings in 61.21s (0:01:01) ===================
```

[VERIFIED-WITH-FRESH-EVIDENCE — command output above, captured this run after the fix, single combined invocation]

Suite-by-suite breakdown from the same run:
- **New test** (the reproduction): 1/1 PASSED (was 1/1 FAILED before the fix).
- **`tests/test_rt_004_application_card_dedup.py`**: 9/9 PASSED — unchanged, still green.
- **`tests/test_wc_interview_conversion_rate.py`**, **`test_wc_tailoring_loop.py`**,
  **`test_wc_tailoring_persistence.py`**: 4 + 7 + 2 = 13/13 PASSED — unchanged, still green.
- **`tests/test_analytics.py`** (the existing analytics/market-pulse suite): 10/10 PASSED —
  unchanged, still green (includes
  `test_probability_counts_measured_zero_conversion`, which already exercised the
  "Interview conversion" factor and still passes since its seed data has no multi-row jobs, so
  raw-count and canonical-count coincided there).

**No regressions.** All 34 tests across the six files passed on this single combined run.

## 5. Residual risk — other raw-count sites in `analytics.py`

Grep for `COUNT(*)` in the file after the fix:

```
$ grep -n 'COUNT(\*)' apps/api/app/routers/analytics.py
```

Sites that are `Application`-table raw `COUNT(*)` and NOT routed through
`get_application_counts()` (i.e. NOT distinct-jobId), found by cross-referencing every
`COUNT(*)` hit against its query's `FROM` clause:

1. **`funnel()`, lines ~118-124** — `screened`, `interviewed`, `offers` in the funnel endpoint are
   still raw `COUNT(*) FROM "Application"` (only `applied` on that same endpoint was migrated to
   the canonical helper, per RT-004). A job with multiple Application rows in
   `screening`/`interview`/`offer`-adjacent statuses could inflate these three figures the same
   way market-pulse's did. **Not in scope for this finding** (the finding named only
   analytics.py:362-372) — flagged here, not touched.
2. **`market_pulse()` heatmap query, line ~356** — `COUNT(*) FROM "Application"` per day for the
   35-day activity heatmap. This is an activity-event count (not an "applications total" figure),
   so raw-row semantics may be intentional there, but it is still an unreconciled Application-row
   count worth a second look.
3. **`market_pulse()` `app_week_rows`, line ~440** — weekly `COUNT(*) FROM "Application"` feeding
   the "Your application velocity" `trendIndicators` series — same caveat as #2.
4. **`_dashboard()`, lines ~664-677** — `interviews` and `offers` in the dashboard-summary card are
   raw `COUNT(*) FROM "Application"`, while `totalApplications` on the SAME card correctly uses
   `get_application_counts()["total"]` a few lines above. This is the closest analog to the
   finding just fixed and the strongest candidate for a follow-up finding.

None of these were touched — the assigned finding scoped this fix to the Market Pulse
"Interview conversion" factor (pre-fix lines 362-372) only, and `get_application_counts()`
itself was left byte-for-byte unchanged so downstream callers (RT-004, W-C) stay green.
Recommend filing #4 (`_dashboard()` interviews/offers) as a follow-up finding — same bug class,
same user-visible risk (dashboard-summary card vs. funnel/conversion cards on the same
dashboard).

## 6. Scope discipline

- Only `apps/api/app/routers/analytics.py` (production code) and
  `apps/api/tests/test_market_pulse_interview_count_divergence.py` (new test) were changed.
- Files this run was told to stay out of (`app/routers/applications.py`, `app/routers/jobs.py`,
  `app/agents/email_agent.py`, `app/agents/submission_agent.py`, `app/routers/workspaces.py`,
  `apps/web/**`) were not touched — confirmed via `git diff apps/api/app/routers/analytics.py`
  showing only the two hunks above, and via `git status` showing no other files staged by this
  fix (unrelated concurrent changes from other agents in `app/routers/applications.py`,
  `apps/api/app/services/stage_transitions.py`, `.abacus.donotdelete`, and two runtime-monitor
  log files were observed in the working tree but were NOT staged or committed by this fix).
- `get_application_counts()`'s return values are unchanged — verified by RT-004 (9/9) and W-C
  (13/13) staying green.
- No DB/DDL change was needed.
- No placeholders, TODOs, suppressed errors, or silent fallbacks were introduced.
