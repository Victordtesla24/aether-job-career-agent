# GMV4-ats-002 — Round 3 Adversarial Code Review (§22 STEP 5, ROUND 3)

Reviewer: `reviewer` sub-agent, did not author any of this diff. Repo:
/home/ubuntu/github_repos/aether-job-career-agent. HEAD `79c4164`. Timestamp:
2026-08-01T00:25:42Z. Round 3 material lives inside the single WIP commit
`79c4164`, whose own message says "W-HF round 3 has NOT completed independent
review" — this review supplies that missing review.

## Verdict: **FAIL**

The five claimed fixes (sentinel rename, whitelist conversions, deliberate
`tailoring_loop.py` exception, `tailor_agent.py:511` OR-not-overwrite,
`resume/page.tsx` panel gating) are all real, committed, pass their tests
[VERIFIED-WITH-FRESH-EVIDENCE, this session]. But item 4's mandate — re-grep
EVERY consumer — surfaces a live, unguarded, user-facing consumer round 3
never touched. The "whitelist everywhere" claim is false.

## Findings (file:line — problem — required change)

1. **`apps/web/src/app/dashboard/jobs/page.tsx:570-572`** — `startTailoring`'s
   §12.3 score-refresh reads `out.conversionMetrics.tailoredATSScore` and
   writes it into `job.fitScore` with **no check of
   `tailoredDegraded`/`scoringDegraded`**, though both sit on the same
   `conversionMetrics` object this round added them to (`resumes.ts:68-70`).
   `fitScore` renders unguarded at `MatchRing value={job.fitScore}` (1125,
   card), `MatchRing value={selected.fitScore}` (1286, detail), the
   submission-gate score (1632), and the list-row span (1847) — including
   the confirm-before-apply modal. A transient HF Inference API failure on
   `_compute_conversion_metrics`'s two fresh re-scores (same mechanism round
   2 found at `tailor_agent.py:511`) silently paints a placeholder score as
   the job's real match score, no badge anywhere. Violates ADR-GMV4-001
   verbatim ("derived metric ... computed from a degraded endpoint must be
   withheld or flagged"). **Required**: gate on
   `!out.conversionMetrics.tailoredDegraded`, or thread a `fitScoreDegraded`
   flag onto `Job`/`MatchRing` as `resume/page.tsx` does for its panel.

No other unguarded consumer found — full inventory in item 4 below.

## Answers to hunt items 1-8

1. **Test runs**, foreground/bounded, this session: 12-test file group →
   **12 passed**, 1.24s; 14-test keep-green group → **14 passed**, 5.09s;
   `cd apps/web && npx tsc --noEmit` → **exit 0**, no output.
   [VERIFIED-WITH-FRESH-EVIDENCE, this session] — matches claim exactly.
2. **Culture Fit, right reason**: confirmed. Reran the round-2 scenario;
   before jobs.py had a per-dimension `degraded` key it FAILED, dict =
   `{'label': 'Culture Fit', 'score': 70}` (no signal). At HEAD, `jobs.py`'s
   `dimensions` list literally carries `{"label": "Culture Fit", "score":
   culture_fit, "degraded": not sem_trusted}` — the assertion, scoped to the
   Culture Fit dict itself, passes because that dict now carries the signal
   directly, not by payload-wide coincidence.
3. **`tailoring_loop.py` exception, walked**: `self._ats_engine = ats_engine
   or ATSEngine()` (`tailor_agent.py:351`), sole production `TailoringLoop(`
   call (`:453`) — never a custom engine, so production always gets real
   `ATSEngine.score()`, which (sole `ATSScore(` site, `ats_engine.py:303`)
   ALWAYS sets `semantic_path` explicitly, never `"untracked"`.
   `any_degraded` can never see `"untracked"` in production — exception
   unreachable outside tests. Reachable ONLY via `test_wc_tailoring_loop.py`'s
   `_StepwiseATS`, which omits `semantic_path` while asserting `success is
   True` — the two named keep-green assertions. No ADR-GMV4-001 violation
   today. Recommend `_StepwiseATS` declare `semantic_path="local"`
   explicitly so `tailoring_loop.py` can drop the special-cased blacklist.
4. **Whitelist completeness**, every site grepped both trees:
   `ats_engine.py:159,316` (source) · `resumes.py:184,189` (whitelist) ·
   `jobs.py:310,325,335,337,345,368,378,401` (whitelist, `sem_trusted`) ·
   `tailor_agent.py:124-125` (whitelist) · `tailoring_loop.py:220-228`
   (deliberate narrower blacklist, safe per #3) · `resume/page.tsx:216,223`
   (whitelist) · `jobs/page.tsx:506` (whitelist) · **`jobs/page.tsx:570-572`
   (NO CHECK — finding 1)**. `workers/tasks.py:235`, `agents.py:989,2371,
   2380` only pass `conversionMetrics` through or set `None` — safe. FAIL
   basis is finding 1 alone.
5. **RadarChart flooring**: `Math.max(4, d.degraded ? 0 : d.score)`
   (`jobs/page.tsx:227`) floors a degraded dim to the same minimal radius as
   an honest near-zero — but the chart has no per-axis labels for ANY
   dimension, and sits in the same section as the labeled grid (em-dash +
   badge) and the disclaimer note. Opinion: acceptable, not ideal (a
   dashed/distinct stroke would be stronger), not a standalone false claim
   given the co-located honest signals.
6. **Frontend honesty end-to-end**: no bare number in `resume/page.tsx` or
   `jobs/page.tsx`'s grid — em-dash confirmed both. Absent-field:
   `semanticTrusted`/`insightsSemanticTrusted` use `=== "local" ||
   === "hf_api"`, `undefined` reads untrusted (note shows). Exception:
   finding 1, zero gating. Zero new vitest coverage for any degraded-UI
   branch — round 2's gap, still open; only `tsc` (types) checked.
7. **Scope creep / test integrity**: `git diff 5c8da67 HEAD -- <6 test
   files>` empty — round-3 fixer touched none (last edit test-author's,
   `5c8da67`). W-HF diff touches exactly the 7 files claimed. Extra check:
   `test_tailor_persistence_db.py` has 1 pre-existing, self-documented RED
   test (`GMV4-tailor-001` gap, unrelated) — not a round-3 regression.
8. **Concurrent work**: `agents.py`, `services/agent_run_stream.py` (SSE),
   `test_story_dedup_invocation.py` correctly not touched/attributed;
   SSE's own FAILED review stands untouched.

## What would catch a round-4 defect

Re-derived production-reachability of the `tailoring_loop.py` exception from
first principles (every `ATSScore(`/`TailoringLoop(` construction site)
instead of trusting the docstring, and re-grepped every field name across
both trees instead of re-running only the named tests — that second step
caught finding 1, which rounds 1-3 missed by scoping their search to
`resumes.py`/`jobs.py` insights/`resume/page.tsx`'s panel and never
re-sweeping `jobs/page.tsx`'s unrelated §12.3 code for new consumers of the
same `conversionMetrics` object it already reads.
