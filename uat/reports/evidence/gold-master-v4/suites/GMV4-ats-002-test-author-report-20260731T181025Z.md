# GMV4-ats-002 — Test-Author Report (§22 STEP 2, SECOND ROUND, W-HF review FAIL)

Role: test-author (failing-tests-only, never implements). Repo:
`/home/ubuntu/github_repos/aether-job-career-agent`. Timestamp: 2026-07-31T18:10:25Z.

Governance: `/home/ubuntu/aether-gold-master-execution-v4.md` §5 (W-HF) + §0.5.
Context: a BLOCKER fix (GMV4-ats-001) replaced ATS token-overlap scoring with
genuine `all-MiniLM-L6-v2` embeddings and added `ATSScore.semantic_path` in
`{local, hf_api, degraded}`. An adversarial review FAILED that fix: the
engine is internally correct, but **no consumer checks `semantic_path`**, so
the honest `_DEGRADED_SEMANTIC_SCORE = 50.0` placeholder leaks outward and is
treated as a real measurement. These tests pin that it cannot, at 3 confirmed
leak sites plus one previously-untested load-bearing function.

## Files (3, all committed `6db8934`)

- `apps/api/tests/test_ats_semantic_path_propagation.py` — 4 tests.
- `apps/api/tests/test_tailoring_loop_degraded_guard.py` — 4 tests.
- `apps/api/tests/test_ats_warm_up.py` — 4 tests.

All 12 are DB-free (no `client`/`db_session` fixtures) — each targets a
router/service function directly with duck-typed stubs (matching the
established `test_tailor_response_contract.py` convention) or a
`sys.modules`-injected `sentence_transformers` stub, so none needed
`/tmp/aether-pytest.lock` and none touch the shared `aether_test` schema.

## Run command

```
timeout 180 scripts/run-tests.sh tests/test_ats_semantic_path_propagation.py \
  tests/test_tailoring_loop_degraded_guard.py tests/test_ats_warm_up.py \
  -v --tb=short --no-header
```

Verbatim output: `GMV4-ats-002-fail-before-20260731T181025Z.txt` (9 failed, 3
passed, 1.50s). Non-regression check on the two suites this work must never
touch: `GMV4-ats-002-baseline-green-unaffected-20260731T181033Z.txt`
(`test_wc_tailoring_loop.py` + `test_ats_engine_semantic.py`, 14/14 PASSED).

## Per-test results

### File 1 — `test_ats_semantic_path_propagation.py` (4/4 FAILED, right reason)

| Test | Verbatim failure | Verdict |
|---|---|---|
| `test_resume_ats_response_includes_semantic_path` | `AssertionError: ... assert 'semantic_path' in {'resume_id': ..., 'semantic_similarity': ...}` — key absent from payload | RIGHT REASON |
| `test_resume_ats_response_flags_degraded_scoring` | `assert None == 'degraded'` — `resp.get("semantic_path")` is `None` | RIGHT REASON |
| `test_job_insights_does_not_blend_degraded_semantic_into_culture_fit` | `assert (not [{'label': 'Culture Fit', 'score': 70}] or False)` — Culture Fit=70 built from the degraded 50.0 placeholder, no flag anywhere in the payload | RIGHT REASON |
| `test_degraded_score_is_never_returned_as_an_unqualified_number` | `assert None == 'degraded'` on the resumes endpoint (fails before even reaching the jobs-insights half) | RIGHT REASON |

### File 2 — `test_tailoring_loop_degraded_guard.py` (4/4 FAILED, right reason)

| Test | Verbatim failure | Verdict |
|---|---|---|
| `test_loop_records_semantic_path_per_iteration` | `assert None is not None` — iteration dict is `{'iteration': 1, 'score': 40.0, 'bullets': [...], 'changes': 1, 'gapKeywords': [], 'rejected': []}`, no path key | RIGHT REASON |
| `test_loop_does_not_declare_success_on_degraded_scores` | `assert True is False` — `TailoringLoopResult(..., best_score=90.0, success=True, requires_review=False, warning=None)` on a single degraded-path iteration | RIGHT REASON — this is the flagship: an automated success decision made off a fabricated 40%-weight number |
| `test_baseline_and_tailored_scores_are_flagged_when_degraded` | `assert (False or False)` — `{'baselineATSScore': 40.0, 'tailoredATSScore': 78.0, 'estimatedConversionLift': '+2.4%', ...}` with baseline degraded, no flag, nothing withheld | RIGHT REASON |
| `test_loop_succeeds_normally_on_genuine_scores` (positive control) | `assert None == 'local'` on the per-iteration path readback | RIGHT REASON — fails on the SAME missing-field defect as test 1, not on success/requires_review/warning/best_score (which are already correct and asserted equal to today's values in the same test body) |

### File 3 — `test_ats_warm_up.py` (1/4 FAILED, right reason; 3/4 PASSED — reported honestly, not forced)

| Test | Result | Verdict |
|---|---|---|
| `test_warm_up_downloads_and_caches_model_when_absent` | PASSED | Implementation genuinely correct: download call omits `local_files_only`, cache gets populated, a fresh post-warm-up `_load_embedding_model()` call sees it. |
| `test_warm_up_is_non_blocking_and_never_raises_into_startup` | **FAILED — real bug found.** `PermissionError: simulated permission failure listing .../unlistable_cache` propagates out of `ats_engine.warm_up_semantic_model()` at `app/services/ats_engine.py:241` -> `_load_embedding_model` at `app/services/ats_engine.py:203` (`os.listdir(cache)`), caught by `pytest.fail(...)`. `warm_up_semantic_model`'s own `try/except` (ats_engine.py's download block) only wraps the DOWNLOAD half; the path-resolution half (`_load_embedding_model.cache_clear()` + `_load_embedding_model()`) that runs right after is unguarded. A cache dir that exists but can't be listed (permission error, transient FS/NFS issue, remove-race) breaks the function's own documented "Never raises" contract. | RIGHT REASON — genuine defect |
| `test_load_embedding_model_uses_local_files_only` | PASSED | Implementation genuinely correct: verified via real dependency-swap (not asserting-the-mock) that `SentenceTransformer(..., local_files_only=True)` is passed on every construction against a warmed cache, across two independent `cache_clear()`+call cycles. |
| `test_cold_cache_degrades_honestly_rather_than_crashing` | PASSED | Implementation genuinely correct: cold cache + no `HF_TOKEN` + simulated-offline download resolves to `"degraded"`, and a real `ATSEngine.score()` call under the same state returns `semantic_path == "degraded"` rather than raising `SemanticScoringUnavailableError`. |

**On the 3 passes**: each exercises the real function with a swapped
dependency (never asserts "the mock was called," always asserts real
resulting state — disk contents, exact kwargs recorded, or the real
`ATSEngine.score()` / `SemanticScoringUnavailableError` contract) — none are
tautological or over-mocked-to-pass-regardless. Two additional attack angles
were tried before accepting these as genuinely green: (1) an
`sentence_transformers.SentenceTransformer.__init__` signature check in the
pinned `5.6.1` confirms `local_files_only` is a real, honored kwarg (not
silently dropped by a library API drift); (2) a pre-poisoning scenario
(seed the shared `lru_cache` with `None` from a simulated early request
*before* warm-up runs) still resolves correctly, because
`warm_up_semantic_model` unconditionally calls `_load_embedding_model.cache_clear()`
before its own re-check. Per the brief's own anti-tautology rule ("no
over-mocking that would pass regardless of implementation"), forcing an
assertion to fail here would itself be a test defect in the other direction —
so these are reported as validated-passing coverage of a previously
zero-test-covered, load-bearing function, not silently dropped.

## `git status --porcelain` proof — no production file touched by this work

```
$ git status --porcelain apps/api/app/ apps/web/src/
 M apps/api/app/main.py
 M apps/api/app/services/ats_engine.py
```
Both modifications PRE-DATE this session (the GMV4-ats-001 implementation
itself, per commit `269d5f1` "W-HF implemented (awaiting review)" and prior
working-tree state observed at task start) — this test-author pass made zero
`Edit`/`Write` calls against any file under `apps/api/app/` or
`apps/web/src/`. `apps/api/tests/test_ats_engine_semantic.py` (the existing
7-test contract) is untouched (confirmed both by not appearing in this
diff — it is untracked, not modified — and by the 14/14 PASSED
non-regression run above).

## Product-decision note (required by task brief)

Pinning "the loop must not converge on degraded scores" **is** a product
decision. Two contracts are defensible:

- **(a) REFUSE-AND-ERROR** — raise before returning any `TailoringLoopResult`
  at all when the winning iteration's `semantic_path == "degraded"`.
- **(b) CONVERGE-BUT-FLAG** — never report `success=True` on a degraded
  score; return `requires_review=True` with a warning naming the
  degradation, exactly like the existing sub-target-score path already
  does.

`test_loop_does_not_declare_success_on_degraded_scores` pins **(b)**, because
it is the contract this codebase has already chosen twice for the identical
"no genuine signal available" situation: `ATSEngine.score()` itself never
raises on `SemanticScoringUnavailableError` — it degrades and stamps
`semantic_path="degraded"` (see that class's own "HONEST DEGRADATION"
docstring); and the cover-letter pipeline's prior incident (2026-07-21,
commit `56552e0`, per `aether-agent-pipeline-runtime-fixes.md`) was a
hard-fail-the-whole-pipeline bug on `FabricationError` that was itself
reverted in favor of graceful degradation, because hard-failing broke
user-facing flows worse than an honest flagged result did. **(a) is the
alternative** the orchestrator may prefer instead — if so, the one test to
rewrite is `test_loop_does_not_declare_success_on_degraded_scores` (assert a
raised exception instead of `success is False` + a named warning); every
other test in `test_tailoring_loop_degraded_guard.py` is contract-agnostic
(they only require semantic_path to be *recorded* and to *matter*, not which
of the two failure modes is chosen).

## Commit

`6db8934` — `test(GMV4-ats-002): failing tests for semantic_path leak — no
consumer honors the ATS degraded-scoring signal`. 3 files, 698 insertions,
0 production files, 0 modifications to `test_ats_engine_semantic.py`.
