# GMV4-ats-002 — Round 2 Adversarial Code Review (§22 STEP 5, ROUND 2)

Reviewer: `reviewer` sub-agent (did not author any of this diff). Repo:
/home/ubuntu/github_repos/aether-job-career-agent. Timestamp: 2026-07-31T18:39:40Z.
Scope: uncommitted working-tree diff (round 1 + round 2 material, still unstaged —
round 1 was never committed because round 1 review FAILED).

## Verdict: **FAIL**

Round 2 closed the four leak sites *as measured by the 12 contract tests*, and the
`os.listdir` guard is genuinely fixed (double-guarded: inner try/except in
`_load_embedding_model`, outer try/except in `main.py`'s warm-up wrapper). But two
concrete, live leak sites remain — one of them the exact ADR-GMV4-001 named example
("ATS delta / lift ... withheld or flagged") — and the `semantic_path` default
change is fail-open on the one axis this workstream exists to protect, adopted
substantially to keep pre-existing tests green, which is the reasoning §0.5
forbids.

## Findings (file:line — problem — required change)

1. **`apps/web/src/app/dashboard/jobs/page.tsx:31-55` (`Insights` type) + `apps/api/app/routers/jobs.py:322,325,330,332,337,351-352,357`** —
   `culture_fit` (`0.5*sem+0.5*exp`), `north_star` (`0.6*overall+0.4*sem`), the
   "Industry Match" dimension, and the risk narrative ("X% semantic overlap")
   are all still computed **unconditionally** from `sem`, which is the degraded
   50.0 placeholder whenever `sem_path=="degraded"`. The backend now emits
   `semanticPath`/`semanticDegraded` (jobs.py:378-379) but the frontend
   `Insights` TS interface never declares those two fields and the radar chart
   (`RadarChart dims={selectedInsights.dimensions}` at page.tsx:1308) and risk
   list (page.tsx:1341) render every one of these numbers with **zero visual
   indication**. This is round 1 finding #2, reopened one layer down —
   confirmed by grep: `grep -rn "semanticPath\|semanticDegraded" apps/web/src`
   returns only the `resume/page.tsx` file, never `jobs/page.tsx`.
   **Required**: add `semanticPath?`/`semanticDegraded?` to `Insights`, and
   either exclude `sem` from `culture_fit`/`north_star`/narrative when degraded
   or badge the affected radar dimensions/risk line the same way
   `resume/page.tsx` badges "Semantic similarity."

2. **`apps/web/src/app/dashboard/resume/page.tsx:370-372,379`** (`ATS Conversion
   Impact` panel) renders `conversion.baselineATSScore`, `.tailoredATSScore`,
   and `.estimatedConversionLift` **unconditionally** whenever `conversion` is
   non-null — never reading `conversion.scoringDegraded` /
   `.baselineDegraded` / `.tailoredDegraded`, even though `resumes.ts:68-70`
   now types all three and `tailor_agent.py:126-133` now computes all three.
   This is the literal example named in ADR-GMV4-001's binding condition:
   "Any derived metric (ATS delta / 'lift' / conversion estimate) computed
   from a degraded endpoint must be withheld or flagged." It is neither.
   **Compounding bug**: `apps/api/app/agents/tailor_agent.py:511` —
   `conversion_metrics["requires_review"] = loop_result.requires_review`
   **overwrites** the just-computed `scoringDegraded` signal with the loop's
   own (independently-computed, potentially different-outcome) verdict. Since
   `_compute_conversion_metrics` (tailor_agent.py:504) re-scores
   `baseline_bullets`/`loop_result.final_bullets` with two **fresh**
   `ATSEngine().score()` calls made *after* the loop finished — not reused
   from any loop iteration — a transient HF-API failure on just these two
   calls degrades the conversion metrics while `loop_result.requires_review`
   stays `False`: `tailorWarning` never fires (resume/page.tsx:388-394) and
   the Before/After/lift panel shows fabricated-derivative numbers with no
   warning anywhere on the page. **Required**: gate the panel on
   `!conversion.scoringDegraded` (or badge it), and OR
   `conversion_metrics["scoringDegraded"]` into `requires_review` at
   tailor_agent.py:511 instead of overwriting.

3. **`apps/api/tests/test_ats_semantic_path_propagation.py:160-169`** —
   `test_job_insights_does_not_blend_degraded_semantic_into_culture_fit`
   asserts `not culture_fit_dims or _degradation_flagged(result)`, where
   `_degradation_flagged` (line 130-135) accepts a match on **any** key in
   `("semanticPath","semantic_path","semanticDegraded","scoringDegraded")`
   **anywhere in the top-level payload** — not scoped to the Culture Fit
   dimension itself. Because round 2 added a top-level `semanticPath`/
   `semanticDegraded` pair to `_build_insights`'s return dict unconditionally,
   this test is satisfied by that addition alone, **regardless of whether
   Culture Fit is actually contaminated** — and per finding 1 above, it still
   is. This is a genuinely weak contract test that lets finding 1 through; I
   have not modified it (out of my mandate) but flag it as insufficient
   evidence for "leak site #2 closed."

## Focal question — the `semantic_path` default (`"degraded"` → `None`)

**Construction-site inventory** (`grep -rn "ATSScore(" apps/api/app --include="*.py"`):
exactly **one** production site — `ats_engine.py:294`, inside `ATSEngine.score()`.
Traced both branches feeding it: the try branch sets
`semantic_path=detailed.path` (`"local"`/`"hf_api"`, never `"degraded"` —
`_SemanticSimilarityResult` is frozen and its own docstring guarantees this);
the `except SemanticScoringUnavailableError` branch sets `semantic_path="degraded"`
unconditionally. **The author's claim is TRUE**: the real engine always sets the
field explicitly; `None` is genuinely unreachable from `ATSEngine.score()` today.

**Test-double inventory** (`grep -rln "ATSScore(" apps/api/tests`): 5 files.
Two IN today's explicit contract (`test_ats_semantic_path_propagation.py`,
`test_tailoring_loop_degraded_guard.py`) always set `semantic_path` explicitly.
Three do **not**: `test_wc_tailoring_loop.py` (a keep-green file!),
`test_tailor_persistence_db.py`, `test_tailor_response_contract.py`.

**Empirically verified the stated risk is real, not hypothetical.**
`test_wc_tailoring_loop.py:149` and `:214` assert `result.success is True`
against `_StepwiseATS` (line 116-121), which constructs `ATSScore(...)` with no
`semantic_path=` kwarg. With a `"degraded"` default, `any_degraded` in
`tailoring_loop.py` would be `True` for every iteration these tests produce,
flipping `success` to `False` and breaking two of the "14 keep-green" tests I
was told to re-verify as green. The other two files (`test_tailor_persistence_db.py`,
`test_tailor_response_contract.py`) use scores that never reach `target_score`
regardless (40-44 vs. target 85), so `reached_target` is already `False` there —
the default wouldn't flip those. So the *actual* casualty count of a fail-closed
default is smaller than the author's blanket framing implies (2 tests, not "tests"
generally), but it is not zero, and one of the two is explicitly in this round's
own keep-green set.

**Is the third state meaningful, or convenience?** Judgment: **accommodation, not
engineering.** The stated purpose — "callers/test doubles that construct an
`ATSScore` without tracking provenance at all" — is a legitimate concept in the
abstract, but its concrete effect is fail-**open** on the exact axis this whole
workstream protects: "I don't know" is treated identically to "genuinely
measured," not identically to "degraded." A provenance-agnostic caller should be
the one that has to opt IN to being trusted, not opt OUT of being distrusted. The
author's own justification text ("would flip currently-passing success=True
assertions to False") is, verbatim, the §0.5-forbidden reasoning the task brief
warned to watch for — and I independently found the exact two assertions it
refers to, so this isn't a strawman.

**Compounding structural risk**: every production consumer checks
`semantic_path == "degraded"` (blacklist), never `semantic_path in ("local",
"hf_api")` (whitelist) — confirmed at resumes.py, jobs.py, tailoring_loop.py,
tailor_agent.py. Combined with the `None` default, this means `None`, a future
third path value, or a typo all silently resolve to "trust it." Safe today
(single production construction site, always explicit) but a landmine for the
next caller — e.g. a future cache/serialization layer round-tripping `ATSScore`
through JSON, or a new endpoint that builds a partial score.

**Recommendation**: keep the default fail-**closed** (`"degraded"`), and instead
of touching the disallowed test doubles, add a **new, explicit third sentinel**
distinct from both, e.g. `semantic_path: str = "untracked"` as the default —
this (a) never silently satisfies `== "degraded"` checks (so it can't ever be
*mis-flagged* as a known-bad measurement), (b) never silently satisfies a
future whitelist `in ("local","hf_api")` check either (so it fails closed there
too), and (c) keeps `test_wc_tailoring_loop.py`'s existing `success is True`
assertions passing today exactly as `None` does, since neither `"untracked"`
nor `None` equals `"degraded"`. This gets the author's stated goal (don't touch
tests I don't own) without ALSO making the default indistinguishable from "known
good" to any future whitelist-style consumer. The author's chosen `None` gets
partial credit for at least being a distinct sentinel from `"local"`/`"hf_api"`/
`"degraded"`, but a bare `None` on a `str | None` field is a weaker signal than a
named string — every consumer still has to remember `None` is not `"local"`
before it means anything, and the docstring is the only thing enforcing that.
Net judgment: the default change was the ONLY viable move under the
"don't modify tests you don't own" constraint, but `None` is a worse choice of
sentinel than a named `"untracked"`/`"unknown"` string would have been, for zero
extra cost.

## Answers to hunt items 1-7

1. **Remaining unqualified-degraded-number paths**: YES — findings 1 and 2
   above (jobs.py insights/radar/risks; resume conversion-impact panel).
   `resumes.py`'s own ATS panel (component grid + "not measured" badge/em-dash)
   IS correctly guarded; verified `row.degraded ? "—" : row.value` at
   page.tsx:589 and the note at page.tsx:596-601.
2. **ADR-GMV4-001 compliance**: `success=True` is unreachable when any
   *loop-internal* iteration was degraded (verified: `any_degraded` computed
   over `iterations`, `success = reached_target and not any_degraded`,
   `requires_review = not success`) — CONFIRMED via
   `test_loop_does_not_declare_success_on_degraded_scores` (passing). Two
   distinct, specific, named warning strings (not generic prose) — confirmed
   by reading tailoring_loop.py's two branches. BUT the binding condition
   "any derived lift/delta ... must be withheld or flagged" is violated for
   the conversion-metrics path per finding 2 (computed, typed, never
   consumed/gated).
3. **UI copy** (resume/page.tsx only — jobs/page.tsx has none): honest, not
   alarmist ("could not be measured... treated as directional"). Value IS
   replaced with an em-dash (`row.degraded ? "—" : row.value`, line 589), not
   shown. Progress bar width forced to 0 when degraded. `ats.semantic_degraded`
   is read with `Boolean(...)` coercion and the note uses `ats.semantic_degraded
   ?` (truthy check), so an older cached response missing the field entirely
   (`undefined`) renders as NOT degraded — same fail-open pattern as finding
   in the focal question, one layer up in the frontend. No test file (vitest)
   exists for this new UI at all — zero automated coverage guards it.
4. **Guarded `os.listdir`**: YES, degrades honestly — `_load_embedding_model`
   wraps `os.path.isdir(cache) and os.listdir(cache)` in `try/except OSError`
   → `cache_populated=False` (ats_engine.py, in the `_load_embedding_model`
   diff hunk). Cannot raise into startup by any other route: `main.py`'s
   `_warm_up_ats_semantic_model` wraps the entire call in its own
   `try/except Exception`, and `warm_up_semantic_model()` itself wraps its
   download attempt and never lets `os.makedirs`/`SentenceTransformer(...)`
   escape. Verified empirically: `test_warm_up_is_non_blocking_and_never_raises_into_startup`
   simulates a `PermissionError` from `os.listdir` and passes.
5. **Scope creep**: none beyond what's disclosed. `iterations`/`gapKeywords`
   additions in `tailor_agent.py` and the SSE endpoint in `routers/agents.py`
   are explicitly commented `GMV4-tailor-001`/`GMV4-sse-001` — a different,
   concurrent workstream per the brief's item 7; not attributed here, not
   reverted. `requirements.txt`/`requirements-ml.txt` changes are round-1
   carryover (unchanged from round 1's diff), not new in round 2.
6. **Test integrity**: `test_ats_semantic_path_propagation.py`,
   `test_tailoring_loop_degraded_guard.py`, `test_ats_warm_up.py` committed
   at `6db8934`, zero diff vs. HEAD (`git diff` empty) — unmodified.
   `test_wc_tailoring_loop.py` tracked, zero diff vs. HEAD — unmodified.
   `test_ats_engine_semantic.py` is untracked (round 1 never committed
   anything), so no git history to diff against; read in full — no
   xfail/skip/tautological assertions found, consistent with round 1's report.
   No `xfail`/`skip` markers anywhere in any of the 6 files (grepped).
7. **Concurrent work**: correctly not touched/attributed — see item 5.

## Test runs (executed by me, this session, foreground, bounded timeout)

```
$ timeout 120 scripts/run-tests.sh tests/test_ats_semantic_path_propagation.py \
    tests/test_tailoring_loop_degraded_guard.py tests/test_ats_warm_up.py \
    -v --tb=short --no-header
============================= test session starts ==============================
collecting ... collected 12 items
tests/test_ats_semantic_path_propagation.py::test_resume_ats_response_includes_semantic_path PASSED
tests/test_ats_semantic_path_propagation.py::test_resume_ats_response_flags_degraded_scoring PASSED
tests/test_ats_semantic_path_propagation.py::test_job_insights_does_not_blend_degraded_semantic_into_culture_fit PASSED
tests/test_ats_semantic_path_propagation.py::test_degraded_score_is_never_returned_as_an_unqualified_number PASSED
tests/test_tailoring_loop_degraded_guard.py::test_loop_records_semantic_path_per_iteration PASSED
tests/test_tailoring_loop_degraded_guard.py::test_loop_does_not_declare_success_on_degraded_scores PASSED
tests/test_tailoring_loop_degraded_guard.py::test_baseline_and_tailored_scores_are_flagged_when_degraded PASSED
tests/test_tailoring_loop_degraded_guard.py::test_loop_succeeds_normally_on_genuine_scores PASSED
tests/test_ats_warm_up.py::test_warm_up_downloads_and_caches_model_when_absent PASSED
tests/test_ats_warm_up.py::test_warm_up_is_non_blocking_and_never_raises_into_startup PASSED
tests/test_ats_warm_up.py::test_load_embedding_model_uses_local_files_only PASSED
tests/test_ats_warm_up.py::test_cold_cache_degrades_honestly_rather_than_crashing PASSED
======================== 12 passed, 6 warnings in 1.22s ========================
```
[VERIFIED-WITH-FRESH-EVIDENCE, this session, 2026-07-31T18:31Z] — matches
author's claimed 12/12. (Note: 12/12 green does NOT mean the leak class is
closed — see finding 3, the weak test at line 160-169.)

```
$ timeout 120 scripts/run-tests.sh tests/test_ats_engine_semantic.py \
    tests/test_wc_tailoring_loop.py -v --tb=short --no-header
============================= test session starts ==============================
collecting ... collected 14 items
tests/test_ats_engine_semantic.py::test_semantic_similarity_uses_local_model_when_available PASSED
tests/test_ats_engine_semantic.py::test_semantic_similarity_uses_hf_inference_api_when_local_unavailable PASSED
tests/test_ats_engine_semantic.py::test_hf_inference_response_parsed_and_clamped PASSED
tests/test_ats_engine_semantic.py::test_hf_inference_error_does_not_return_silent_token_overlap PASSED
tests/test_ats_engine_semantic.py::test_semantic_score_is_not_token_overlap_for_paraphrase_pair PASSED
tests/test_ats_engine_semantic.py::test_engine_reports_active_scoring_path PASSED
tests/test_ats_engine_semantic.py::test_ats_total_score_composition_unchanged PASSED
tests/test_wc_tailoring_loop.py::test_loop_uses_discovered_default_of_five_and_stops_once_target_reached PASSED
tests/test_wc_tailoring_loop.py::test_clean_gap_keywords_strips_tokenization_noise PASSED
tests/test_wc_tailoring_loop.py::test_loop_embeds_clean_gap_keywords_directive_into_next_iteration PASSED
tests/test_wc_tailoring_loop.py::test_loop_exits_immediately_once_target_score_is_met PASSED
tests/test_wc_tailoring_loop.py::test_loop_stops_at_max_iterations_when_score_never_reaches_target PASSED
tests/test_wc_tailoring_loop.py::test_loop_surfaces_honest_warning_with_best_achieved_score_when_capped_out PASSED
tests/test_wc_tailoring_loop.py::test_loop_never_lets_a_fabricated_keyword_close_the_gap PASSED
============================== 14 passed in 5.63s ==============================
```
[VERIFIED-WITH-FRESH-EVIDENCE, this session, 2026-07-31T18:31Z] — matches
author's claimed 14/14.

## Bottom line

Engine-internal correctness and the `os.listdir` guard are solid. The
API-boundary fixes for `resumes.py` + `resume/page.tsx`'s component grid are
correct and well-executed (em-dash, badge, honest note). But two live,
user-reachable leak sites remain — the jobs-insights radar/risk panel
(frontend never wired) and the resume conversion-impact panel (frontend never
wired, PLUS a backend bug that discards the one signal that would catch it) —
and the `semantic_path` default was chosen substantially to avoid touching
tests, which is the exact reasoning this run's own governance doc prohibits.
**FAIL. Round 3 required.**
