# GMV4-ats-001 — Adversarial Code Review (§22 STEP 5)

Reviewer: reviewer sub-agent (never authored this change). Repo:
/home/ubuntu/github_repos/aether-job-career-agent. Timestamp: 2026-07-31T17:55:38Z.

## Verdict: **FAIL**

`ats_engine.py` itself is correct and honest. But the fix stops at the engine boundary:
every production consumer of `ATSScore` (2 API routers, the tailoring loop, the tailor
agent) reads `semantic_similarity`/`overall` WITHOUT checking the new `semantic_path`
field, so a degraded placeholder (50.0) can still reach a paying user labelled as a real
score — the exact defect this fix exists to close, now one layer up the call stack. The
contract test file's own docstring (line 54-59) states `semantic_path` exists "so
startup logging and **the UI warning** can be truthful" — no UI warning was built.

## Findings (file:line — problem — required change)

1. `apps/api/app/routers/resumes.py:179` — `"semantic_similarity": round(score.semantic_similarity, 1)`
   returned to the frontend with **no `semantic_path` in the payload at all**, and no
   check of it server-side. `apps/web/src/app/dashboard/resume/page.tsx:573` renders it
   as `"Semantic similarity (40%)"` unconditionally. [VERIFIED-WITH-FRESH-EVIDENCE
   direct read 2026-07-31T17:55Z] When degraded, a paying user is shown `50.0` as if it
   were a real embedding score, with zero visual indication — BLOCKER, this is the
   defect class GMV4-ats-001 was filed to eliminate. **Required change**: add
   `semantic_path` to the `/resumes/{id}/ats` response and to the TS type; render a
   visible degraded-state badge/tooltip in `page.tsx` when `semantic_path !== "local"`
   (or at minimum `=== "degraded"`).

2. `apps/api/app/routers/jobs.py:298,317` — `sem = float(score.semantic_similarity)` then
   `culture_fit = _round(0.5 * sem + 0.5 * exp)` inside `_build_insights` (job
   `/insights` endpoint), no `semantic_path` check. [VERIFIED-WITH-FRESH-EVIDENCE direct
   read] Same defect: a degraded 50.0 silently blends into the "Culture Fit" score shown
   on the job insights panel. **Required change**: same as #1 — surface path, and either
   exclude the semantic term from `culture_fit`'s blend or flag the insight as degraded
   when `semantic_path == "degraded"`.

3. `apps/api/app/services/tailoring_loop.py:176,181,188,193,200` — `ats_score =
   self._ats.score(...)`; every consumer of `ats_score.overall` (iteration record,
   `best_score`, the `target_score` convergence check, the next-pass directive) uses the
   blended `overall`, which itself silently contains the degraded semantic term whenever
   `semantic_path == "degraded"` (since `overall` is computed inside `.score()` before the
   caller ever sees `semantic_path`). [VERIFIED-WITH-FRESH-EVIDENCE direct read] This is
   worse than #1/#2: it is an **automated business decision** (loop success/failure,
   `requires_review`) silently made against a fabricated number, with no `semantic_path`
   recorded anywhere in `iterations[]` for post-hoc audit. **Required change**: thread
   `ats_score.semantic_path` through the iteration record; the loop must not report
   `success=True` (or silently keep iterating against a fake target) while degraded —
   at minimum surface a `degraded: true` flag on the run result.

4. `apps/api/app/agents/tailor_agent.py:101-115` — `baseline_score`/`tailored_score` =
   `engine.score(...).overall`, exposed as `baselineATSScore`/`tailoredATSScore`, no
   `semantic_path` check on either call. [VERIFIED-WITH-FRESH-EVIDENCE direct read] Same
   class of gap — the reported "lift" percentage can be computed off two silently
   degraded numbers. **Required change**: same as #3.

5. `apps/api/app/services/ats_engine.py` (`warm_up_semantic_model`, `_load_embedding_model`'s
   new `local_files_only=True`, and `apps/api/app/main.py`'s daemon-thread wiring) —
   **zero test coverage**. `grep -rn "warm_up_semantic_model\|local_files_only"
   apps/api/tests/` returns nothing. [VERIFIED-WITH-FRESH-EVIDENCE grep, this session]
   This is the mechanism that makes the LOCAL path reachable at all in a fresh prod
   deploy (the root cause was literally "the model was not cached") — it shipped with no
   failing-before test and no passing-after test. Not a hard blocker standing alone, but
   a TDD-discipline gap on the single most load-bearing new function in the diff.
   **Required change**: a test-author-written test (e.g., monkeypatching
   `SentenceTransformer`/env) asserting `warm_up_semantic_model()` returns the correct
   path string and that `_lifespan` launches it as non-blocking daemon thread.

None of 1-5 touch `ats_engine.py`'s own internal correctness — items 6-9 below found no
additional defects inside the engine itself.

## Answers to items 1-9

1. **Silent-fallback path in `score()`**: None found. Traced every branch:
   `_semantic_similarity_detailed` → local (full try, exceptions in `_load_embedding_model`
   already swallowed to `None` and re-tried via HF) → `_call_hf_inference_api` (raises
   `SemanticScoringUnavailableError` on missing token / non-2xx / bad JSON / bad shape) →
   caught once in `score()`, which sets `semantic_path="degraded"` explicitly (ats_engine.py:262-271).
   `SemanticScoringUnavailableError` is never swallowed anywhere without setting
   `semantic_path`. [VERIFIED-WITH-FRESH-EVIDENCE direct read] — engine-internal
   behavior is correct. The defect is one layer up (findings 1-4).

2. **`_DEGRADED_SEMANTIC_SCORE = 50.0`**: Yes, it is a placeholder value on a
   user-reachable path, and per findings 1-4 above, **callers do not check
   `semantic_path` before trusting it**. `resumes.py:179` renders it to a user as a real
   score; `jobs.py:298/317` blends it into "Culture Fit"; `tailoring_loop.py` and
   `tailor_agent.py` use it in automated scoring decisions. This is a BLOCKER — the fix
   is incomplete at the integration boundary. Confirmed via direct grep + read of every
   consumer of `semantic_similarity`/`ATSScore` in `apps/api/app`.

3. **Rounding to 4dp**: Legitimate, not a fudge — `overall` (the field every downstream
   consumer actually keys decisions on) is still separately `round(..., 2)`, and every
   external caller re-rounds `semantic_similarity` itself (`resumes.py` to 1dp; `jobs.py`
   consumes the raw float only to feed another `_round()`-wrapped blend). The extra
   precision doesn't leak past `ATSScore` in any user-facing or persisted form I could
   find (no DB write of `ATSScore` fields located).

4. **`local_files_only=True`**: Plausible and confirmed via source inspection of the
   installed `sentence-transformers==5.6.1` here: `sentence_transformer/model.py:1086`
   — `if not local_files_only: self.model_card_data.set_base_model(...)` — a Hub call
   gated exactly on this flag. [VERIFIED-WITH-FRESH-EVIDENCE, this session, different
   venv than prod but same package/behavior] Cold machine / no cache: `_load_embedding_model`
   checks `os.path.isdir(cache) and os.listdir(cache)` *before* even instantiating
   `SentenceTransformer`, so it returns `None` immediately and falls through to
   HF-API-or-degraded — honest, no crash. A race during first-ever download (cache dir
   exists but only partially populated) can make `SentenceTransformer(local_files_only=True)`
   raise; that's caught by the existing broad `except Exception: return None` — still
   honest degradation, not a crash, just a possible spurious transient "degraded" window
   at first boot. Non-blocking observation, not a defect.

5. **Startup warm-up thread**: Cannot kill startup — wrapped in `try/except Exception`
   in `_warm_up_ats_semantic_model` (main.py) and run as `daemon=True`, started
   immediately before `yield` (not awaited), so `_lifespan` proceeds to serve
   `/api/health` without waiting. Race: `_load_embedding_model` is `@lru_cache`, and
   CPython's `lru_cache` releases its lock during the wrapped call (only serializes
   cache reads/writes, not concurrent misses) — so the warm-up thread and a concurrent
   real request thread (FastAPI runs sync endpoints via threadpool) can both construct a
   `SentenceTransformer` instance simultaneously on a cold cache. This wastes memory/CPU
   transiently but returns a fully-valid model either way — not a "half-initialised"
   result, no thrash/retry loop found (warm-up runs once, no retry).

6. **The 3 now-failing pre-existing tests**: **VERIFIED TRUE, independently, via my own
   `git stash` A/B this session** (not the author's numbers taken on trust). See below.

7. **Scope creep**: `warm_up_semantic_model()` + `main.py` thread + `local_files_only`
   flag are not directly asserted by any of the 7 contract tests (confirmed by grep —
   see finding 5), but they are necessary to make the fix operational in prod (the
   defect was literally "model not cached") — I judge this in-spirit, not creep, but
   flag it as untested (finding 5). `docs/delivery/GOLD-MASTER-V3-GOVERNANCE.md` and
   `uat/reports/evidence/gold-master-v2/runtime/monitor-errors-CORRECTED.log` also show
   as modified in the working tree, but a scoped `git stash push -- <4 fix files>` this
   session left them untouched/unaffected — they belong to a concurrent process in this
   shared repo (admin-credential rotation logging, unrelated content), not to this diff.
   Not attributed to this fix.

8. **Secrets**: `HF_TOKEN` read via `os.environ.get("HF_TOKEN", "").strip()` at call
   time in `_call_hf_inference_api` (never hardcoded). `warm_up_semantic_model` logs
   only `"<set>"`/`"<absent>"`, never the value. Compliant.

9. **Backward compatibility**: `ATSScore.semantic_path: str = "degraded"` is a new
   dataclass field with a default — existing positional/keyword construction sites
   unaffected. `semantic_similarity` stays a non-Optional float (no type change). No
   `ATSScore` persistence to DB found (routers hand-build response dicts, don't
   serialize the dataclass directly) — no schema-migration concern. Compliant.

## Independent stash A/B result (item 6)

`git stash push -- apps/api/app/services/ats_engine.py apps/api/app/main.py
apps/api/requirements.txt apps/api/requirements-ml.txt` (untracked test file untouched,
model/package installs untouched) → ran against **unmodified** `ats_engine.py` with the
model already installed+cached in this environment:

```
FAILED tests/test_ats_engine.py::test_perfect_keyword_overlap_scores_high
  AssertionError: assert 87.74 >= 90  (semantic_similarity=74.91 on the real model)
FAILED tests/test_gap_e2_conversion.py::TestConversionMetricsUnit::test_baseline_zero_does_not_divide_by_zero
  assert 4.75 == 0.0
FAILED tests/test_gap_e2_conversion.py::TestConversionMetricsUnit::test_env_override_of_baseline_rate_is_respected
  assert 23.7 == 24.0
3 failed, 1 passed in 7.89s
```

Identical failures/values to the post-fix run. **Author's claim CONFIRMED TRUE**: these
3 are pre-existing tests calibrated to the token-overlap fallback's numeric output, not
regressions introduced by this diff — they surface once the real model is genuinely
active, independent of any code change here. (A 4th test in `test_gap_e2_conversion.py`,
`test_tailor_run_response_includes_conversion_metrics`, errors with an unrelated 401
auth-fixture failure both before and after — pre-existing shared-test-DB/auth flakiness,
not attributable to this diff either way.) Stash was popped and restored; re-ran the 7
contract tests post-restore — still 7/7 passed.

## Contract tests — re-run by me, this session

```
$ timeout 120 scripts/run-tests.sh tests/test_ats_engine_semantic.py -v --tb=short --no-header
7 passed in 0.99s
```
[VERIFIED-WITH-FRESH-EVIDENCE, this session — matches author's reported 7/7]
`GMV4-ats-001-fail-before-20260731T172722Z.txt` (pre-existing artifact) confirms all 7
failed with `AttributeError`/missing-symbol errors before the fix — legible RED-before
evidence.

## story_relevance.py deferred item — recommendation: **IMPLEMENT WITH TESTS FIRST, as a separate follow-on item — not folded into this diff**

Reasoning: `story_relevance.py:10-18` is honestly, explicitly self-documented as
term-frequency keyword overlap and explicitly disclaims being TF-IDF or semantic — it
never claims to be an embedding score, so it is not the *same* silent-fallback defect
class as GMV4-ats-001 (which was about a function *labelled* semantic silently being
something else). `grep` confirms no test in `test_we_story_dedup_relevance.py` pins it
to an embedding path. If §5.2/§8.3/gate G-E genuinely require the same model path here
(I cannot independently verify the governance doc's exact text — it is not present
under `docs/delivery/` in this repo; [ASSUMED-PENDING-PROBE] on the citation, taken at
the orchestrator's word), then it is real, filed, spec-required work — not "genuinely
out of scope" — but pulling it into *this* diff would itself be scope creep on a
BLOCKER fix that is otherwise minimal and reviewable. The cost objection is now weak
(model is cached locally, CPU-only, batchable once per JD as suggested) — that argues
for scheduling it soon, not for skipping it. Recommend: file it as its own
GMV4/gate-G-E ticket, test-author writes a failing test first (pinning
`story_relevance_score` — or a new `story_relevance_score_semantic` — to
`_load_embedding_model`/HF path with the same honest-degradation contract), then a
fixer implements against it. Do not implement inside `ats_engine.py`'s diff.
