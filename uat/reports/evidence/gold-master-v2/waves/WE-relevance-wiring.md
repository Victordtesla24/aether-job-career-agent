# W-E — closing the last red test: relevance-filtering capability wired into `build_story_evidence`

Agent: ai-loop-engineer (this session). Scope: GOLD-MASTER-V2 §7.3.5, the single
outstanding red test left by the prior fixer-medium session
(`uat/reports/evidence/gold-master-v2/waves/WE-ENT-fix-report.md`, §4).
Repo: `/home/ubuntu/github_repos/aether-job-career-agent`. Stay-out list honored:
`app/repositories/story.py`, `app/routers/stories.py`, `app/routers/cover_letters.py`,
`app/services/story_paraphrase.py`, `app/services/story_relevance.py`,
`app/services/story_dedup_migration.py`, `app/routers/admin.py`, `app/db.py`,
`apps/web/**` — none of these files were opened for edit (only `story_relevance.py`
was **imported and called**, never modified — confirmed by `git diff` below touching
only `apps/api/app/agents/tailor_agent.py`).

All timestamps are wall-clock UTC from this session, 2026-07-31.

## 1. What §4 of the prior report specified

The prior agent (fixer-medium) correctly refused to touch
`app/agents/tailor_agent.py` because it was on ITS stay-out list, and documented a
ready-to-apply, evidence-checked fix instead of editing it:

```python
def build_story_evidence(
    user_id: str,
    repo: StoryRepository | None = None,
    job_description: str | None = None,
) -> str:
    repo = repo or StoryRepository()
    stories = repo.list_by_user(user_id)
    if job_description:
        from app.services.story_relevance import filter_stories_by_relevance
        stories = filter_stories_by_relevance(stories, job_description)
    # ...existing flattening loop, unchanged, now over `stories`...
```

It also flagged that all the actual scoring machinery (`story_relevance_score`,
`relevance_threshold`, `filter_stories_by_relevance`) already existed, fully built
and tested, in `app/services/story_relevance.py` — nothing new needed to be built,
only wired.

## 2. What I implemented

`app/agents/tailor_agent.py` is the ONLY file this session's stay-out list assigns
me, and it is exactly the file the failing test pins its contract against
(`inspect.signature(build_story_evidence)` must contain `"job_description"`). I
implemented the prior agent's own ready-to-apply snippet essentially verbatim:

* `build_story_evidence(user_id, repo=None, job_description=None)` — the new
  third parameter is optional and defaults to `None`, so **every existing call
  site is byte-identical in behavior** unless a caller explicitly starts passing
  a job description.
* When `job_description` is truthy, the story list is narrowed via
  `app.services.story_relevance.filter_stories_by_relevance` (lazy import,
  matching the prior report's own snippet and this codebase's existing
  lazy-import precedent for cross-module reuse) — the SAME function
  `GET /stories?job_id=` already uses, reusing `story_relevance_score` and the
  `AETHER_STORY_RELEVANCE_THRESHOLD`-driven `relevance_threshold()` unchanged.
  No new scoring logic was written (§13.1 — no duplication).
* The flattening loop that turns each story into evidence text is otherwise
  **completely unchanged** — same fields, same metric handling, same empty-corpus
  behavior.

### Deliberate scope decision — call sites NOT changed

The only two existing call sites (`TailoringAgent.run`, line ~392 of
`tailor_agent.py`, and `cover_letters.py:717`, which is on my explicit stay-out
list) still call `build_story_evidence(user_id, self._stories)` / `(user_id)` with
**no** `job_description` argument, so their behavior is provably unchanged (see
regression evidence, §4). I evaluated wiring `job_description=jd` into
`TailoringAgent.run` (the `jd` variable already exists in scope right before the
`build_story_evidence` call) but rejected it after computing the actual relevance
score of the `test_tailoring_agent_wires_story_bank_into_evidence` regression
fixture (`tests/test_gap_p6_tailoring_ats.py`) against its own JD: the story's
"Kubernetes migration ... Deployed Kubernetes clusters and Kafka pipelines"
text scores **2/11 ≈ 0.18** against that test's `_JD` (TF-weighted overlap:
`kubernetes` + `kafka` match out of 11 weighted JD terms) — strictly below the
0.4 default floor. Passing `job_description` there would silently empty the
evidence corpus and break that explicitly-protected regression test (an
outcome this task's own brief lists as impermissible: "W-C is code-complete at
13/13 and must stay green" plus the general "must stay green" instruction for
`test_gap_p6_tailoring_ats.py`). The task's own scope line — *"Your job is ONLY
to make `build_story_evidence` ... support relevance filtering, per the
contract the test defines"* — bounds this fix to the function's capability, not
to rewiring callers; the single RED test asserts only the signature contract,
never that any specific caller invokes it. Wiring a caller that breaks a
protected regression would be exactly the kind of scope creep the hard rules
prohibit. The capability is now real, tested, and available for whichever
future task legitimately owns `cover_letters.py`/`cover_letter_agent.py` (or a
JD-aware variant of `TailoringAgent.run`) to opt into per-job filtering without
touching `tailor_agent.py` again.

## 3. Env var name and default

`AETHER_STORY_RELEVANCE_THRESHOLD`, default `0.4` — unchanged, defined and read
entirely inside `app/services/story_relevance.py::relevance_threshold()`
(untouched by this diff; only imported/called). Naming confirmed against this
codebase's established convention: every other runtime-tunable in
`apps/api/app` uses the `AETHER_` prefix (`AETHER_CONVERSION_BASELINE_RATE`,
`AETHER_LLM_BUDGET_SECONDS`, `AETHER_MODEL_FALLBACK`, `AETHER_ENV`, etc. —
`[VERIFIED]` via `grep -rn 'os.environ.get("AETHER_' apps/api/app --include=*.py`,
2026-07-31T07:57Z).

## 4. Verbatim before/after test output

### Before (fresh, self-verified — NOT reusing the prior report's quoted output)

Reverted only `apps/api/app/agents/tailor_agent.py` via `git stash push -- apps/api/app/agents/tailor_agent.py`
(confirmed via `git status --short` showing the file un-modified), then ran the
target test against the clean, unmodified file:

```
$ date -u +"%Y-%m-%dT%H:%M:%SZ"
2026-07-31T07:57:41Z
$ flock /tmp/aether-pytest.lock -c "scripts/run-tests.sh tests/test_we_story_dedup_relevance.py::TestSelectionThreshold -v"
...
>       assert "job_description" in sig.parameters, (
E       AssertionError: build_story_evidence(user_id, ...) has no job_description parameter (found only ['user_id', 'repo']) — it cannot filter stories by relevance to the job being applied for, so every story the user owns is included indiscriminately in every cover-letter / tailoring generation run
E       assert 'job_description' in mappingproxy(OrderedDict({'user_id': <Parameter "user_id: 'str'">, 'repo': <Parameter "repo: 'StoryRepository | None' = None">}))
...
=========================== short test summary info ============================
FAILED tests/test_we_story_dedup_relevance.py::TestSelectionThreshold::test_build_story_evidence_supports_relevance_filtering_for_generation
======================== 1 failed, 5 warnings in 0.23s =========================
```
`[VERIFIED]` — fresh fail-before reproduced in this session, 2026-07-31T07:57:41Z.

Restored the fix via `git stash pop` (confirmed via `git diff --stat` showing
`apps/api/app/agents/tailor_agent.py | 25 ++++++++++++++++++++++---`, i.e. the
exact diff below, back in place).

### After — full target file

```
$ date -u +"%Y-%m-%dT%H:%M:%SZ"
2026-07-31T07:57:48Z
$ flock /tmp/aether-pytest.lock -c "scripts/run-tests.sh tests/test_we_story_dedup_relevance.py -v"
...
tests/test_we_story_dedup_relevance.py::TestParaphraseFingerprintDedup::test_paraphrase_of_existing_achievement_merges_not_inserts PASSED [ 14%]
tests/test_we_story_dedup_relevance.py::TestParaphraseFingerprintDedup::test_real_duplicate_titles_from_evidence_report_do_not_double_insert PASSED [ 28%]
tests/test_we_story_dedup_relevance.py::TestFalsePositiveGuard::test_two_genuinely_different_achievements_are_both_stored PASSED [ 42%]
tests/test_we_story_dedup_relevance.py::TestBulkDedupMigration::test_bulk_dedup_migration_merges_duplicates_and_is_idempotent PASSED [ 57%]
tests/test_we_story_dedup_relevance.py::TestStoryRelevanceScore::test_story_relevance_score_returns_bounded_plausible_score PASSED [ 71%]
tests/test_we_story_dedup_relevance.py::TestRelevanceExposedOnList::test_get_stories_with_job_id_exposes_relevance_score PASSED [ 85%]
tests/test_we_story_dedup_relevance.py::TestSelectionThreshold::test_build_story_evidence_supports_relevance_filtering_for_generation PASSED [100%]
...
======================== 7 passed, 6 warnings in 9.13s =========================
```
`[VERIFIED]` 2026-07-31T07:57:48Z. **7/7 passed, 0 failed** — this is the FULL
content of `test_we_story_dedup_relevance.py` (7 test functions total across its
6 test classes); the task brief's "target 11 passed, 0 failed" figure refers to
this file plus `test_adv_ent_001_refine_entitlement_gate.py` (5 tests) combined,
per the prior report's own "Total (11 target tests)" table (§1 of
`WE-ENT-fix-report.md`). Ran that combined pair too, for full parity with the
prior report's evidence shape:

```
$ date -u +"%Y-%m-%dT%H:%M:%SZ"
2026-07-31T07:55:41Z
$ flock /tmp/aether-pytest.lock -c "scripts/run-tests.sh tests/test_we_story_dedup_relevance.py tests/test_adv_ent_001_refine_entitlement_gate.py -v"
...
collected 12 items
tests/test_we_story_dedup_relevance.py::TestParaphraseFingerprintDedup::test_paraphrase_of_existing_achievement_merges_not_inserts PASSED [  8%]
tests/test_we_story_dedup_relevance.py::TestParaphraseFingerprintDedup::test_real_duplicate_titles_from_evidence_report_do_not_double_insert PASSED [ 16%]
tests/test_we_story_dedup_relevance.py::TestFalsePositiveGuard::test_two_genuinely_different_achievements_are_both_stored PASSED [ 25%]
tests/test_we_story_dedup_relevance.py::TestBulkDedupMigration::test_bulk_dedup_migration_merges_duplicates_and_is_idempotent PASSED [ 33%]
tests/test_we_story_dedup_relevance.py::TestStoryRelevanceScore::test_story_relevance_score_returns_bounded_plausible_score PASSED [ 41%]
tests/test_we_story_dedup_relevance.py::TestRelevanceExposedOnList::test_get_stories_with_job_id_exposes_relevance_score PASSED [ 50%]
tests/test_we_story_dedup_relevance.py::TestSelectionThreshold::test_build_story_evidence_supports_relevance_filtering_for_generation PASSED [ 58%]
tests/test_adv_ent_001_refine_entitlement_gate.py::TestUngatedRefineIsBlockedForUnentitledUser::test_lapsed_subscriber_refine_returns_402_not_200 PASSED [ 66%]
tests/test_adv_ent_001_refine_entitlement_gate.py::TestUngatedRefineIsBlockedForUnentitledUser::test_lapsed_subscriber_refine_makes_no_llm_call PASSED [ 75%]
tests/test_adv_ent_001_refine_entitlement_gate.py::TestEntitledRefineIsMeteredAndAudited::test_entitled_refine_reserves_quota_and_creates_agent_run_audit_row PASSED [ 83%]
tests/test_adv_ent_001_refine_entitlement_gate.py::TestEntitledRefineIsMeteredAndAudited::test_entitled_refine_respects_the_spend_cap PASSED [ 91%]
tests/test_adv_ent_001_refine_entitlement_gate.py::TestGateRunsBeforeResourceLookup::test_bogus_letter_id_for_unentitled_user_returns_402_not_404 PASSED [100%]
...
======================= 12 passed, 6 warnings in 21.69s ========================
```
`[VERIFIED]` 2026-07-31T07:55:41Z — **12/12 passed, 0 failed** (the
false-positive guard, `TestFalsePositiveGuard::test_two_genuinely_different_achievements_are_both_stored`,
is GREEN in this run, confirming the two-genuinely-different-achievements
non-regression guard still holds).

## 5. Regression results

```
$ date -u +"%Y-%m-%dT%H:%M:%SZ"
2026-07-31T07:56:08Z
$ flock /tmp/aether-pytest.lock -c "scripts/run-tests.sh tests/test_tailoring_agent.py tests/test_gap_p5_tailoring.py tests/test_gap_p6_tailoring_ats.py tests/test_wc_tailoring_loop.py tests/test_wc_tailoring_persistence.py tests/test_wc_interview_conversion_rate.py -v"
```

All 36 collected tests PASSED (0 failed):

```
tests/test_tailoring_agent.py::TestTailoring::test_tailoring_does_not_invent_skills PASSED
tests/test_tailoring_agent.py::TestTailoring::test_every_changed_bullet_has_evidence_ref PASSED
tests/test_tailoring_agent.py::TestTailoring::test_format_hash_unchanged_after_tailoring PASSED
tests/test_tailoring_agent.py::TestTailoring::test_tailored_resume_is_child_of_base PASSED
tests/test_tailoring_agent.py::TestTailoring::test_retailoring_corrupted_parent_stays_consistent PASSED
tests/test_tailoring_agent.py::TestTailoring::test_resume_list_and_diff_endpoints PASSED
tests/test_gap_p5_tailoring.py::test_conversion_lift_is_non_negative_for_noop PASSED
tests/test_gap_p5_tailoring.py::test_conversion_lift_is_strictly_positive_for_clear_match PASSED
tests/test_gap_p5_tailoring.py::test_rewrite_dropping_a_jd_keyword_is_reverted PASSED
tests/test_gap_p5_tailoring.py::test_truthful_evidence_backed_terminology_is_accepted PASSED
tests/test_gap_p5_tailoring.py::test_fabricated_capitalized_skill_is_rejected PASSED
tests/test_gap_p5_tailoring.py::test_quantified_metric_is_preserved PASSED
tests/test_gap_p5_tailoring.py::test_section_structure_is_unchanged PASSED
tests/test_gap_p5_tailoring.py::test_strip_bullet_lines_keeps_context_drops_bullets PASSED
tests/test_gap_p5_tailoring.py::test_jd_only_domain_term_injection_is_rejected PASSED
tests/test_gap_p5_tailoring.py::test_rewrite_dropping_most_metrics_is_rejected PASSED
tests/test_gap_p5_tailoring.py::test_evidence_corpus_excludes_job_description PASSED
tests/test_gap_p5_tailoring.py::test_truthful_evidence_backed_jd_keyword_is_accepted_and_lifts_ats PASSED
tests/test_gap_p6_tailoring_ats.py::test_evidence_extra_is_passed_to_the_llm_prompt PASSED
tests/test_gap_p6_tailoring_ats.py::test_story_backed_keywords_lift_ats_strictly_without_fabrication PASSED
tests/test_gap_p6_tailoring_ats.py::test_unsupported_keyword_stays_rejected_even_with_story_bank PASSED
tests/test_gap_p6_tailoring_ats.py::test_build_story_evidence_flattens_story_bank PASSED
tests/test_gap_p6_tailoring_ats.py::test_tailoring_agent_wires_story_bank_into_evidence PASSED
tests/test_wc_tailoring_loop.py::test_loop_uses_discovered_default_of_five_and_stops_once_target_reached PASSED
tests/test_wc_tailoring_loop.py::test_clean_gap_keywords_strips_tokenization_noise PASSED
tests/test_wc_tailoring_loop.py::test_loop_embeds_clean_gap_keywords_directive_into_next_iteration PASSED
tests/test_wc_tailoring_loop.py::test_loop_exits_immediately_once_target_score_is_met PASSED
tests/test_wc_tailoring_loop.py::test_loop_stops_at_max_iterations_when_score_never_reaches_target PASSED
tests/test_wc_tailoring_loop.py::test_loop_surfaces_honest_warning_with_best_achieved_score_when_capped_out PASSED
tests/test_wc_tailoring_loop.py::test_loop_never_lets_a_fabricated_keyword_close_the_gap PASSED
tests/test_wc_tailoring_persistence.py::TestTailoringLoopPersistence::test_tailored_resume_persists_per_iteration_history PASSED
tests/test_wc_tailoring_persistence.py::TestTailoringLoopPersistence::test_tailor_run_never_claims_success_below_the_85_target PASSED
tests/test_wc_interview_conversion_rate.py::TestInterviewConversionRate::test_interview_conversion_rate_is_a_real_computation_not_a_placeholder PASSED
tests/test_wc_interview_conversion_rate.py::TestInterviewConversionRate::test_interview_conversion_rate_denominator_is_distinct_submitted_jobs PASSED
tests/test_wc_interview_conversion_rate.py::TestInterviewConversionRate::test_interview_conversion_rate_zero_when_no_interviews_yet PASSED
tests/test_wc_interview_conversion_rate.py::TestInterviewConversionRate::test_interview_conversion_rate_green_threshold_is_one_in_five PASSED

======================= 36 passed, 6 warnings in 58.60s ========================
```
`[VERIFIED]` 2026-07-31T07:56:08Z — **36/36 passed, 0 failed, 0 regressions.**
`test_tailoring_agent_wires_story_bank_into_evidence` (the fixture whose relevance
score I hand-computed at ≈0.18 against its own JD, §2) stayed green precisely
because `TailoringAgent.run`'s call site was deliberately left unchanged.

## 6. Anti-fabrication guarantee — provably preserved

* `filter_stories_by_relevance` (unmodified, reused) only ever **removes**
  entries from the list passed to the existing flattening loop; it cannot add,
  rewrite, synthesize, or duplicate a story. The loop body that turns a story
  dict into evidence text is byte-identical to before this diff — same five
  STAR fields, same tags, same metrics, nothing new is ever emitted.
* Default behavior (`job_description=None`, every existing call site) is
  **provably unchanged**: `stories = repo.list_by_user(user_id)` then
  immediately into the same loop, since the new `if job_description:` branch is
  skipped entirely. Confirmed by the unmodified regression suite (§5) — 36/36
  green, including the two tests that assert the corpus contains specific
  story text (`test_build_story_evidence_flattens_story_bank`,
  `test_tailoring_agent_wires_story_bank_into_evidence`).
* No downstream generation call site in this diff was newly wired to pass
  `job_description`, so no LLM prompt's evidence corpus composition changed at
  all as a result of this fix — the fabrication/entailment guard inside
  `ResumeTailorService`/`_refine_cover_letter_body` sees the exact same input
  it did before. The capability exists and is tested (the RED test itself,
  now green) for a future caller to opt in; opting in can only ever narrow the
  evidence set toward relevance, never widen it beyond the user's own stories
  or invent content — the docstring added to `build_story_evidence` states
  this guarantee explicitly for the next agent who wires a call site.

**Anti-fabrication preserved: yes, provably, both for existing callers (byte-
identical behavior) and for the new optional capability (can only narrow real
evidence, never fabricate).**

## 7. Threshold-interaction question (report only, not fixed — none required)

The prior report flagged a threshold-calibration risk: create-time paraphrase
dedup title Jaccard (`CREATE_TIME_THRESHOLDS`, 0.70) vs. bulk-migration title
Jaccard (`BULK_MIGRATION_THRESHOLDS`, 0.60) in `app/services/story_paraphrase.py`
— a narrow, evidence-calibrated band.

**This session's change does not interact with those thresholds at all.**
`story_paraphrase.py` was never opened, read past what was necessary to confirm
this, or modified. The relevance-filtering capability added here uses an
entirely separate module (`story_relevance.py`), a different algorithm
(TF-weighted keyword-overlap `story_relevance_score`, not Jaccard similarity),
a different config knob (`AETHER_STORY_RELEVANCE_THRESHOLD`, default 0.4, vs.
the dedup module's two hardcoded Jaccard-threshold presets), and a different
purpose (JD-aware evidence selection at generation time vs. duplicate-story
merging at create/migration time). The two systems are only related in that
they both operate on Story Bank rows; there is no shared threshold, shared
constant, or shared code path between them, and this diff touches neither the
dedup module nor its thresholds.

## 8. Files changed

* `apps/api/app/agents/tailor_agent.py` — `build_story_evidence` gains an
  optional `job_description: str | None = None` third parameter; when
  provided, narrows the story list via the existing, unmodified
  `app.services.story_relevance.filter_stories_by_relevance` before the
  unchanged flattening loop. No other file touched.

```
diff --git a/apps/api/app/agents/tailor_agent.py b/apps/api/app/agents/tailor_agent.py
index 345f88a..991aaf9 100644
--- a/apps/api/app/agents/tailor_agent.py
+++ b/apps/api/app/agents/tailor_agent.py
@@ -119,7 +119,11 @@ def _compute_conversion_metrics(
     }
 
 
-def build_story_evidence(user_id: str, repo: StoryRepository | None = None) -> str:
+def build_story_evidence(
+    user_id: str,
+    repo: StoryRepository | None = None,
+    job_description: str | None = None,
+) -> str:
     """Flatten the user's Story Bank into evidence text (GAP-P6-TAIL-001).
 
     The Story Bank holds real, user-authored STAR achievements whose skills are
@@ -128,10 +132,25 @@ def build_story_evidence(user_id: str, repo: StoryRepository | None = None) -> s
     genuinely proves (and pass the fabrication guard) — the only way a
     like-for-like ATS re-score can rise strictly without inventing anything.
     Every quantified result is kept so metric-bearing evidence survives. Empty
-    when the user has no stories (backward compatible)."""
+    when the user has no stories (backward compatible).
+
+    ``job_description`` (§7.3.5, optional/backward-compatible — default
+    ``None`` preserves the exact prior "every story unconditionally" corpus
+    for existing callers) narrows the story set to only those the SAME
+    scoring function ``GET /stories?job_id=`` already exposes
+    (``app.services.story_relevance.story_relevance_score``) rates >=
+    ``relevance_threshold()`` against this specific job. This can only ever
+    NARROW which of the candidate's own TRUE stories are included — it never
+    adds, rewrites, or invents story content, so the anti-fabrication
+    entailment guard downstream is unaffected."""
     repo = repo or StoryRepository()
+    stories = repo.list_by_user(user_id)
+    if job_description:
+        from app.services.story_relevance import filter_stories_by_relevance
+
+        stories = filter_stories_by_relevance(stories, job_description)
     parts: list[str] = []
-    for story in repo.list_by_user(user_id):
+    for story in stories:
         fields = [str(story.get("title") or ""), " ".join(story.get("tags") or [])]
         for key in ("situation", "task", "action", "result"):
             fields.append(str(story.get(key) or ""))
```

## 9. Residual risks / handoff

* **The new capability is not yet wired into any call site** (deliberately —
  see §2's scope decision). `TailoringAgent.run`'s own JD (`jd`, in scope right
  before its `build_story_evidence` call) could be passed once the owner of
  that generation path decides the product wants JD-narrowed evidence there,
  but doing so today would immediately fail `test_gap_p6_tailoring_ats.py::
  test_tailoring_agent_wires_story_bank_into_evidence` at the default 0.4
  threshold (measured score ≈0.18 for that fixture) — that test's Story Bank
  fixture and JD would need to be reconciled first, or `TailoringAgent.run`
  would need a documented fallback-to-unfiltered-when-empty policy, either of
  which is a product/test-authoring decision outside this fix's scope.
  `cover_letters.py:717` (`/refine`'s claim-guard evidence corpus) is on this
  session's stay-out list and was not touched, per the prior agent's own
  documented reasoning (§4 of `WE-ENT-fix-report.md`) that narrowing that
  specific corpus risks making the fabrication guard MORE aggressive.
* Threshold-band risk (§7 above) carried forward unchanged, unaffected by this
  diff — re-verify per the prior report's own guidance if `story_paraphrase.py`
  thresholds are ever retuned.
* `ML-CL-004` (from the prior report, §6 of `WE-ENT-fix-report.md`) remains
  open — out of this task's scope entirely, not touched or re-investigated.
